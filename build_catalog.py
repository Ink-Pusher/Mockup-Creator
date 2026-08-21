"""
build_catalog.py  (multi-site version)

Companion to build_color_template.py. Downloads clean, human-readable
front/back images per color -- named after YOUR product info (brand/style/
color), not any vendor's internal IDs -- and writes a catalog.json entry in
the exact shape the Ink Pusher Mockup Studio tool expects.

Supports five vendor sites/sources, each with its own small "extractor"
function (everything downstream -- renaming, writing catalog.json -- is
identical regardless of source):

    ssactivewear   S&S Activewear   (original, unchanged)
    sanmar         SanMar (saved HTML, one color per page)
    sanmar-pdf     SanMar Media Library PDF export (ALL colors in one run)
    royalapparel   Royal Apparel
    ascolour       AS Colour

SETUP (one time):
    pip install requests pillow numpy scipy pytoshop psd-tools six cloudscraper pymupdf

USAGE:
    python3 build_catalog.py --site <site> <html_file> <brand> <style> <product_name> <kind> [catalog.json]
        [--crop-top F] [--crop-bottom F] [--crop-left F] [--crop-right F]
        [--descriptions [product_descriptions.csv]] [--no-descriptions]

    Reading the write-up is ON BY DEFAULT. Pass --descriptions only to point it
    at a different CSV; pass --no-descriptions to skip it. It ALSO reads the product's write-up (description paragraph,
    spec bullets, responsible-supplier note) off the very same saved page and
    merges it into a CSV shaped for Product Admin's "Bulk tools -> Import
    descriptions (CSV)" importer -- so one run covers a product's photos, its
    catalog.json entry, AND its copy. See build_descriptions.py, which does
    the actual work and can also be run on its own; that file's docstring
    explains where the text is found and what to do when a page defeats it.
    Never fatal: if no write-up can be found, the photos and catalog entry are
    still written and the run just tells you to follow up.

    kind must be one of: tee, hoodie, cap, tote

    The --crop-* flags are optional and default to 0 (no cropping). Each
    takes a fraction between 0 and 0.49 and trims that much off the given
    edge of EVERY photo before saving -- e.g. --crop-top 0.18 removes the
    top 18% of each photo's height. Useful for vendors like Royal Apparel
    that only offer on-model photos (no flat product-only shots): crop the
    model's head off the top and legs off the bottom so only the
    torso/garment area remains, matching how flat shots from other sites
    fill the mockup tool's canvas.
    HOW TO DIAL THESE IN: run once with a guess (e.g. --crop-top 0.15
    --crop-bottom 0.12), check catalog_images/<product>/*_front.jpg for one
    color, and re-run with adjusted numbers -- downloaded photos are cached
    in downloaded_images/, so re-running with new crop values is instant
    and won't re-download anything. The same crop applies to every color in
    that run, which works well since a vendor shoots one style's photos
    with consistent framing across colors.

EXAMPLES:
    python3 build_catalog.py --site ssactivewear bella_3001.html "Bella/Canvas" 3001 "Unisex Heavyweight Tee" tee catalog.json
    python3 build_catalog.py --site sanmar sanmar_black.html "Port & Co" PC099 "Beach Wash Garment-Dyed Tee" tee catalog.json
    python3 build_catalog.py --site sanmar-pdf PC099.pdf "Port & Co" PC099 "Beach Wash Garment-Dyed Tee" tee catalog.json
    python3 build_catalog.py --site royalapparel royal_5051.html "Royal Apparel" 5051 "Unisex Short Sleeve Tee" tee catalog.json --crop-top 0.18 --crop-bottom 0.15
    python3 build_catalog.py --site ascolour ascolour_5026.html "AS Colour" 5026 "Classic Tee" tee catalog.json

IMPORTANT -- SanMar is different from the other three HTML-based sites:
S&S Activewear, Royal Apparel, and AS Colour all list every color on ONE
product page, so one saved page gives you the whole catalog entry in one
run. SanMar's *website* is structured with a SEPARATE page per color (the
URL itself contains the color, e.g. .../p/4664_Black vs .../p/4664_White).
That means for the plain `sanmar` site you save and run this script ONCE
PER COLOR -- each run adds or refreshes just that one color in
catalog.json, so running it five times for five saved SanMar color pages
builds up a five-color entry the same way the other sites do it in a
single run.

`sanmar-pdf` AVOIDS THIS: if you export a PDF from SanMar's Media Library
search results for a style (search the style number, select all results,
export/print to PDF), that single PDF contains every color's front AND
back images already embedded (with transparency baked in) plus their
filenames -- so one `sanmar-pdf` run does the whole product, no per-color
looping needed. Prefer this over the plain `sanmar` site whenever you have
or can get that PDF.

HOW TO SAVE A PAGE (all sites): open the product page in your browser, let
it fully load, then File > Save Page As > "Webpage, HTML Only" (or
"Webpage, Complete" -- either works, this script only reads the .html
file). Pass that saved file's path as <html_file>. Live URLs are NOT
supported for any of these four sites -- all of them either block scripted
requests or load their real product data via JavaScript after the initial
page load, which a saved-after-load page captures but a plain script
fetching the raw URL cannot.

OUTPUT:
    catalog_images/<brand-style-slug>/<color-slug>_front.jpg   (.png for sanmar-pdf,
    catalog_images/<brand-style-slug>/<color-slug>_back.jpg     which preserves the
                                                                  PDF's transparency)
    catalog.json  (created if missing; re-running for the same brand+style
                    merges new/updated colors into the existing list rather
                    than wiping previously-added ones -- this is what makes
                    SanMar's one-color-per-run workflow build up correctly)

WHAT STILL NEEDS A HUMAN EYE:
Each color's "hex" swatch is auto-sampled from the actual downloaded photo
(averaging pixels from the garment's center) so you don't have to hand-enter
one for every color -- but it's an approximation. Skim the output and nudge
any that look off before publishing.
"""

import argparse
import io
import os
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import build_color_template as bct

DOWNLOAD_CACHE_DIR = Path("downloaded_images")


# ---------------------------------------------------------------------------
# Shared helpers (identical regardless of which site the data came from)
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def sample_swatch_hex(img: Image.Image) -> str:
    """Approximate the garment's color by averaging pixels from a central
    crop of the photo (avoids the plain white margins most product shots
    have around the edges)."""
    w, h = img.size
    box = (int(w * 0.35), int(h * 0.35), int(w * 0.65), int(h * 0.65))
    crop = img.convert("RGB").crop(box)
    arr = np.array(crop).reshape(-1, 3)
    avg = arr.mean(axis=0).astype(int)
    return "#{:02x}{:02x}{:02x}".format(*avg)


def crop_fraction(img: Image.Image, top=0.0, bottom=0.0, left=0.0, right=0.0):
    """Crop off a fraction of each edge (0.0-0.49), e.g. top=0.18 removes the
    top 18% of the photo's height. Used to trim heads/legs out of on-model
    photos (Royal Apparel doesn't offer flat product-only shots) down to
    just the torso/garment area, since there's no reliable pixel-based way
    to detect 'this is a shirt vs. a face' -- a fixed crop dialed in by eye
    against one sample color is the practical fix, and it'll apply
    consistently since a vendor's product photos for one style are always
    shot with the same framing/model position across colors."""
    w, h = img.size
    box = (
        int(w * left),
        int(h * top),
        int(w * (1 - right)),
        int(h * (1 - bottom)),
    )
    return img.crop(box)


def load_catalog(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"  ! {path} exists but isn't valid JSON -- starting fresh.")
    return {"products": []}


def save_catalog(path: Path, catalog: dict):
    path.write_text(json.dumps(catalog, indent=2))


def download_image_url(url: str, cache_dir: Path):
    """Like build_color_template.download_image, but for the other three
    sites, which all give full absolute URLs directly (S&S is the only one
    needing a relative-path + CDN-template reconstruction)."""
    if not url:
        return None
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", url) + ".jpg"
    cache_file = cache_dir / safe_name
    if cache_file.exists():
        try:
            return Image.open(cache_file).convert("RGBA")
        except Exception:
            pass
    try:
        resp = bct.SESSION.get(url, timeout=30)
        if resp.status_code != 200 or len(resp.content) < 500:
            print(f"  ! download failed ({resp.status_code}) for {url}")
            return None
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        cache_dir.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(cache_file, quality=95)
        return img
    except Exception as e:
        print(f"  ! download failed for {url}: {e}")
        return None


def read_html(source: str) -> str:
    file_path = Path(source)
    if not file_path.exists():
        raise RuntimeError(
            f"'{source}' is not a file that exists. Save the product page from "
            "your browser (File > Save Page As > Webpage, HTML Only) and pass "
            "that file's path -- live URLs aren't supported for these sites."
        )
    return file_path.read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# Site extractors -- each returns a list of {"name", "front", "back"} dicts,
# where front/back are full absolute image URLs (or None if unavailable).
# ---------------------------------------------------------------------------

def _ss_fetch_from_html(html: str):
    """Duplicates build_color_template's JSON-block-finding logic, working
    from HTML text directly (that module's own fetch_color_data() expects
    a file path or URL, not a string already read into memory)."""
    marker = '[{"styleID":'
    start = html.find(marker)
    if start == -1:
        raise RuntimeError(
            "Could not find the color/image JSON block on this S&S page. "
            "S&S may have changed their page structure."
        )
    depth = 0
    end = None
    for i, ch in enumerate(html[start:], start=start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise RuntimeError("Found the color JSON start but couldn't find its end.")
    return json.loads(html[start:end])


def extract_ssactivewear(html: str):
    colors_raw = _ss_fetch_from_html(html)
    results = []
    for entry in colors_raw:
        front_path, back_path = bct.pick_front_back_paths(entry)
        results.append({
            "name": entry["name"],
            "front": bct.CDN_IMAGE_URL_TEMPLATE.format(path=front_path) if front_path else None,
            "back": bct.CDN_IMAGE_URL_TEMPLATE.format(path=back_path) if back_path else None,
            "_ss_relpath_front": front_path,
            "_ss_relpath_back": back_path,
        })
    return results


def sanmar_list_other_colors(html: str):
    """Every SanMar product page links to all its OTHER color pages in the
    swatch selector (e.g. /p/4664_Amethyst, /p/4664_Black, ...) even though
    only the current color's images are actually embedded. Harvest that
    list so the workflow can print a 'still need to save' checklist
    instead of you having to go find it on the site yourself each time."""
    m = re.search(r'/p/(\d+)_[A-Za-z]+', html)
    if not m:
        return None, []
    style = m.group(1)
    slugs = sorted(set(re.findall(rf'/p/{re.escape(style)}_([A-Za-z]+)', html)))
    return style, slugs


def extract_sanmar(html: str):
    """SanMar: one saved page = ONE color only (their site is structured
    per-color-per-page, unlike the other three). Color name and Front/Back
    are embedded directly in the image filenames. Prefers 'Flat' (clean
    product-only shot) over 'Model' (on-person) images when both exist."""
    pattern = re.compile(
        r'https://cdnp\.sanmar\.com/medias/sys_master/images/[^"\'>\s]*?'
        r'1200W[_-]\d+[_-]([A-Za-z]+)-\d+-\w*?(Flat|Model)(Front|Back)\d*\.jpg'
    )
    front_urls, back_urls, color = {}, {}, None
    for m in pattern.finditer(html):
        url = m.group(0)
        color, kind, view = m.groups()
        target = front_urls if view == "Front" else back_urls
        if kind == "Flat" or "Flat" not in target:
            target[kind] = url
    if not color:
        raise RuntimeError(
            "Couldn't find any SanMar product images on this page. Make sure "
            "you saved a SanMar PRODUCT page (e.g. sanmar.com/p/4664_Black), "
            "not a category/search results page."
        )
    front = front_urls.get("Flat") or front_urls.get("Model")
    back = back_urls.get("Flat") or back_urls.get("Model")
    return [{"name": color, "front": front, "back": back}]


def extract_sanmar_pdf(pdf_path: str):
    """SanMar Media Library PDF export: a 'Results for <style>' PDF where
    each color/view shot is a real embedded image (with proper alpha
    transparency baked in as a PDF soft-mask -- already a clean cutout)
    sitting directly above its own hyperlinked filename label, e.g.
    'PC099_Nordic Green_Flat_Front.tif'. This sidesteps SanMar's one-
    color-per-page HTML workflow entirely: one PDF export covers every
    color for the style in a single run.

    Matching images to filenames is done purely by position (each image's
    bounding box vs. the nearest filename label below it in the same
    column) since the PDF's embedded text/link objects don't reference
    the image xrefs directly. Handles filename labels that wrap onto two
    lines (seen when a color name pushes the label past the column width).

    Returns a list of {"name", "front_img", "back_img"} dicts where the
    images are already-loaded PIL RGBA Images (no download step needed).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError(
            "This needs PyMuPDF: pip install pymupdf --break-system-packages"
        )

    doc = fitz.open(pdf_path)

    def get_filename_labels(page):
        """Span-level text extraction, merging the rare two-line-wrapped
        filename label back into one (matched by close x0 + being the
        very next line down in the same block)."""
        raw_spans = []
        for block in page.get_text("dict")["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if span["text"].strip():
                        raw_spans.append((span["bbox"], span["text"]))
        labels, used = [], set()
        for i, (bbox, text) in enumerate(raw_spans):
            if i in used:
                continue
            t = text.strip()
            if t.lower().endswith(".tif") and re.match(r"^[A-Za-z]", t):
                labels.append((bbox, t))
                continue
            if re.match(r"^[A-Za-z]", t) and not t.lower().endswith(".tif"):
                for j in range(i + 1, min(i + 3, len(raw_spans))):
                    nb, nt = raw_spans[j]
                    if abs(nb[0] - bbox[0]) < 5 and nb[1] > bbox[1]:
                        combined = (t + nt).strip()
                        if combined.lower().endswith(".tif"):
                            used.add(j)
                            labels.append(
                                ((bbox[0], bbox[1], max(bbox[2], nb[2]), nb[3]), combined)
                            )
                        break
        return labels

    fname_re = re.compile(r"^[A-Za-z0-9]+_(.+?)_Flat_(Front|Back)\.tif$", re.I)

    def norm_key(s):
        return re.sub(r"[^a-z0-9]", "", s.lower())

    colors = {}  # norm_key -> {"names": set, "front": PIL, "back": PIL}
    unmatched_images = 0
    unparsed_labels = []

    for page in doc:
        smask_map = {im[0]: (im[1] or None) for im in page.get_images(full=True)}
        img_infos = page.get_image_info(xrefs=True)
        labels = get_filename_labels(page)

        for info in img_infos:
            bbox, xref = info["bbox"], info["xref"]
            best, best_dist = None, None
            for tb, t in labels:
                if abs(tb[0] - bbox[0]) > 5 or tb[1] < bbox[1]:
                    continue
                dist = tb[1] - bbox[3]
                if dist < -5:
                    continue
                if best_dist is None or abs(dist) < best_dist:
                    best_dist, best = abs(dist), t
            if not best:
                unmatched_images += 1
                continue
            m = fname_re.match(best)
            if not m:
                unparsed_labels.append(best)
                continue
            color_raw, view = m.group(1), m.group(2).lower()

            base = doc.extract_image(xref)
            img = Image.open(io.BytesIO(base["image"])).convert("RGB")
            smask_xref = base.get("smask") or smask_map.get(xref)
            if smask_xref:
                mask_img = Image.open(
                    io.BytesIO(doc.extract_image(smask_xref)["image"])
                ).convert("L")
                img = img.convert("RGBA")
                img.putalpha(mask_img)
            else:
                img = img.convert("RGBA")

            key = norm_key(color_raw)
            entry = colors.setdefault(key, {"names": set(), "front": None, "back": None})
            entry["names"].add(color_raw)
            entry[view] = img

    if unmatched_images:
        print(f"  ! {unmatched_images} image(s) in the PDF couldn't be matched to a filename label -- skipped.")
    if unparsed_labels:
        print(f"  ! {len(unparsed_labels)} filename label(s) didn't match the expected pattern -- skipped: {unparsed_labels[:5]}")

    # Flag likely same-color spelling inconsistencies (SanMar's own export
    # has these, e.g. "Cantaloupe" vs "canteloupe") without auto-merging --
    # safer to let a human confirm than to silently guess.
    import difflib
    keys = list(colors.keys())
    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1:]:
            if k1 != k2 and difflib.SequenceMatcher(None, k1, k2).ratio() > 0.8:
                print(f"  ! Possible duplicate color (different spelling in SanMar's export): "
                      f"{sorted(colors[k1]['names'])} vs {sorted(colors[k2]['names'])} -- "
                      f"both were kept as separate colors; merge/rename by hand if they're the same.")

    results = []
    for key, entry in colors.items():
        if not entry["front"] or not entry["back"]:
            missing = "back" if entry["front"] else "front"
            print(f"  ! {sorted(entry['names'])}: missing {missing} image -- skipped.")
            continue
        # Prefer a spaced/Title-Case name (e.g. "Nordic Green") over a
        # squished lowercase one (e.g. "nordicgreen") for display, since
        # SanMar's export sometimes has both for the same color.
        name = sorted(entry["names"], key=lambda n: (" " not in n, n))[0]
        results.append({"name": name.strip().title() if name.isupper() or name.islower() else name,
                         "front_img": entry["front"], "back_img": entry["back"]})

    return sorted(results, key=lambda r: r["name"])


def extract_royalapparel(html: str):
    """Royal Apparel: a full `var prodJSON = {...}` object is embedded with
    every color and every view (Front/Side/Back/Front2/Side2/Back2) all on
    one page."""
    m = re.search(r'var prodJSON\s*=\s*(\{.*?\});', html, re.S)
    if not m:
        raise RuntimeError(
            "Couldn't find Royal Apparel's embedded product data (prodJSON) "
            "on this page. Make sure you saved a product page, fully loaded."
        )
    data = json.loads(m.group(1))
    product = data["product"][0]
    colors_meta = {c["colorCode"]: c["description"] for c in product["color"] if c.get("showColor")}

    by_color = {}
    for av in product.get("altView", []):
        code = av.get("colorCode")
        if not code or code not in colors_meta:
            continue
        desc = av.get("altDesc")
        if desc not in ("Front", "Back"):
            continue
        by_color.setdefault(code, {})
        existing = by_color[code].get(desc)
        if existing is None or av["sortOrder"] < existing[1]:
            by_color[code][desc] = (av.get("imageLg") or av.get("imageZm"), av["sortOrder"])

    results = []
    for code, name in colors_meta.items():
        views = by_color.get(code, {})
        results.append({
            "name": name.title(),
            "front": views.get("Front", (None,))[0],
            "back": views.get("Back", (None,))[0],
        })
    return results


def extract_ascolour(html: str):
    """AS Colour: color name + view are embedded in each image filename
    inside the page's product-schema JSON-LD 'image' array:
    {style}_{PRODUCT_NAME}_{COLOR}__hash.jpg = front,
    {style}_{PRODUCT_NAME}_{COLOR}_BACK__hash.jpg = back. Generic
    non-color shots (MAIN/TURN/SIDE/LOOSE/etc) and _THUMB duplicates are
    skipped.

    PRODUCT_NAME (the marker word(s) between the style code and the color,
    e.g. "TEE" for a Classic Tee) is auto-detected per product rather than
    hardcoded -- it's whichever leading underscore-segment(s) are IDENTICAL
    across every color photo for that product, since only the color
    actually varies between them. This is what lets the same extractor
    handle any AS Colour product type (caps, totes, whatever comes next)
    without needing a code change for each new one."""
    m = re.search(r'"product-schema"[^>]*>\s*(\{.*?\})\s*</script>', html, re.S)
    if not m:
        raise RuntimeError(
            "Couldn't find AS Colour's product-schema JSON-LD block on this "
            "page. Make sure you saved a product page, fully loaded."
        )
    data = json.loads(m.group(1))
    images = data.get("image", [])
    GENERIC = {"MAIN", "FRONT", "TURN", "SIDE", "BACK", "LOOSE"}

    entries = []  # (rest_clean, is_back) per genuine color photo
    for url in images:
        fname = url.rsplit("/", 1)[-1]
        m2 = re.match(r'\d+_(.+?)__\d+.*\.jpg', fname, re.I)
        if not m2:
            continue
        rest = m2.group(1)
        if rest.upper().endswith("_THUMB"):
            continue
        is_back = rest.upper().endswith("_BACK")
        rest_clean = rest[:-5] if is_back else rest
        entries.append((rest_clean, is_back, url))

    if not entries:
        return []

    # Auto-detect how many leading underscore-segments are the shared
    # product-name marker (vs. the first segment that's actually the
    # color, which differs photo to photo). Always leaves at least one
    # trailing segment as the color, even in the pathological case where
    # nothing varies.
    split_upper = [rc.upper().split("_") for rc, _, _ in entries]
    min_len = min(len(parts) for parts in split_upper)
    marker_word_count = 0
    for i in range(min_len - 1):
        if len({parts[i] for parts in split_upper}) == 1:
            marker_word_count = i + 1
        else:
            break

    if marker_word_count == 0:
        raise RuntimeError(
            "Couldn't figure out AS Colour's product-name marker word from "
            "the image filenames (expected something like "
            "STYLE_PRODUCTNAME_COLOR__hash.jpg, shared across every color "
            "photo). The page may not have all its color swatches loaded -- "
            "try re-saving after clicking through a couple of colors first."
        )

    front_by_color, back_by_color = {}, {}
    for rest_clean, is_back, url in entries:
        cname_parts = rest_clean.split("_")[marker_word_count:]
        if not cname_parts:
            continue
        cname = "_".join(cname_parts)
        if cname.upper() in GENERIC:
            continue
        target = back_by_color if is_back else front_by_color
        target.setdefault(cname, url)

    colors = sorted(set(front_by_color) | set(back_by_color))
    return [
        {"name": c.replace("_", " ").title(), "front": front_by_color.get(c), "back": back_by_color.get(c)}
        for c in colors
    ]


EXTRACTORS = {
    "ssactivewear": extract_ssactivewear,
    "sanmar": extract_sanmar,
    "sanmar-pdf": extract_sanmar_pdf,
    "royalapparel": extract_royalapparel,
    "ascolour": extract_ascolour,
}
# Sites whose extractor returns ready-to-save PIL images directly
# (front_img/back_img) instead of URLs to download.
PREEXTRACTED_IMAGE_SITES = {"sanmar-pdf"}


# ---------------------------------------------------------------------------
# Main pipeline -- identical regardless of which site the data came from
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Multi-colour swatches
# ---------------------------------------------------------------------------
# A two-tone product ("White/ Charcoal", a ringer tee, a raglan, most trucker
# hats) gets ONE sampled hex, because sample_swatch_hex averages the middle of
# the photo. On a swatch that reads as a single muddy colour that matches
# neither half -- "Grey Heather/ Black" sampled as #cac6c7, which is just the
# grey.
#
# The colour NAME already carries the answer, and the catalog itself is the
# colour dictionary: "Charcoal" and "Black" both exist as solid colours on
# other products, with hexes sampled from real photos. So component hexes are
# resolved by looking each half of the name up against every solid colour in
# the catalog. No hand-maintained colour table to keep current, and it gets
# better on its own as more solid colours are added.
#
# Writes `hexes: [...]` alongside the existing `hex`, which is left untouched
# as the fallback for the ~23% whose parts never appear as a solid anywhere
# (e.g. "Quarry", "Biscuit", "Arid Multicam").

MULTI_NAME_RE = re.compile(r"\s*/\s*")


def _norm_colour_name(name):
    n = (name or "").lower()
    n = re.sub(r"\b(cmb|combo|solid|blend|tri-?blend)\b", " ", n)
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    n = n.replace("gray", "grey")
    # "Charcoal Heather" and "Heather Charcoal" name the same colour.
    return " ".join(sorted(n.split()))


def _median_hex(hexes):
    import statistics
    chans = [[int(h.lstrip("#")[i:i + 2], 16) for h in hexes] for i in (0, 2, 4)]
    return "#{:02x}{:02x}{:02x}".format(*[int(statistics.median(c)) for c in chans])


def annotate_multi_colour_swatches(catalog):
    """Fill in `hexes` on every multi-part colour whose components can be
    resolved. Re-run over the whole catalog each time, so a colour that was
    unresolvable before becomes resolvable once its component turns up as a
    solid on some later product."""
    lookup = {}
    for prod in catalog.get("products", []):
        for col in prod.get("colors", []):
            if MULTI_NAME_RE.search(col.get("name", "")):
                continue
            key = _norm_colour_name(col.get("name"))
            if key and col.get("hex"):
                lookup.setdefault(key, []).append(col["hex"])
    lookup = {k: _median_hex(v) for k, v in lookup.items()}

    resolved = unresolved = 0
    for prod in catalog.get("products", []):
        for col in prod.get("colors", []):
            name = col.get("name", "")
            if not MULTI_NAME_RE.search(name):
                col.pop("hexes", None)   # in case a name was corrected to a solid
                continue
            parts = [_norm_colour_name(x) for x in MULTI_NAME_RE.split(name)]
            hexes = [lookup.get(x) for x in parts if x]
            if hexes and all(hexes):
                col["hexes"] = hexes[:3]   # three bands is the most a swatch can show legibly
                resolved += 1
            else:
                col.pop("hexes", None)
                unresolved += 1
    return resolved, unresolved



# ---------------------------------------------------------------------------
# Pattern swatches (camo, tie-dye, marle)
# ---------------------------------------------------------------------------
# A camo colourway has no single colour, so the averaged hex is meaningless --
# Forest Camo sampled as #464234, a flat olive-brown that appears nowhere on
# the garment. Splitting into components the way two-tone names do won't help
# either: camo isn't two colours in two regions, it's a pattern.
#
# But we already have a photograph of the fabric. So instead of synthesising a
# pattern, cut a small square OUT of the real garment and use that as the
# swatch. It's exact by construction, for camo and equally for anything else
# patterned, with no pattern-specific code.
#
# Detection is by NAME, not by measuring how varied the photo is. Variance
# looked promising and then flagged 335 colours, most of them wrong: the middle
# of a zip hoodie is a zipper, a ribbed beanie is high-contrast by nature, and
# every one of those needs a human to adjudicate. A name list is smaller, it is
# right, and when it misses something the fix is adding a word.

PATTERN_NAME_RE = re.compile(
    # Generic words first, then the camo BRANDS -- Realtree, Kryptek, Veil,
    # Obskura, Poseidon and Mossy Oak name patterns without ever saying "camo",
    # so a colour like "Realtree Edge/ Brown" or "Kryptek Highlander" was
    # falling through to a flat averaged colour. Worse than merely dull: those
    # sit in a grid beside real two-tone splits, so one camo hat rendering as a
    # single flat brown reads as a rendering fault rather than a colour.
    r"camo|multicam|tie.?dye|tie dye|\bmarl(e|ed)?\b|acid wash|"
    r"mineral wash|splatter|houndstooth|leopard|digital|"
    r"realtree|kryptek|\bveil\b|obskura|poseidon|mossy ?oak|prym|kuiu",
    re.I,
)
SWATCH_TILE_PX = 96


def _fabric_mask(rgb, alpha=None):
    """Where the garment actually is in a product photo.

    Two kinds of source image here. Most are opaque on white, so the background
    is the near-white region CONNECTED TO THE BORDER -- not merely every pale
    pixel, which would classify a white tee as background and find no fabric at
    all. The SanMar PDF path instead yields RGBA cutouts on a TRANSPARENT
    background; converted to RGB that background becomes black, white-detection
    finds nothing, and every crop then straddles the garment edge and scores as
    a wild pattern. Where there's an alpha channel it is the authoritative
    answer, so use it."""
    from scipy import ndimage
    if alpha is not None:
        return ndimage.binary_erosion(alpha > 200, np.ones((9, 9)))
    near_white = np.all(rgb > 236, axis=-1)
    labels, _ = ndimage.label(near_white, np.ones((3, 3)))
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    border.discard(0)
    return ndimage.binary_erosion(~np.isin(labels, list(border)), np.ones((9, 9)))


def extract_pattern_tile(image_path):
    """A square of real fabric, or None if no clean one can be found.

    Candidates are placed across the chest and each is checked against the
    fabric mask -- a tee's bounding box includes the gaps beside the sleeves,
    so a crop positioned by geometry alone can land on background. Of the
    valid ones, the MEDIAN-variance crop is kept: a zip or a placket skews one
    crop, while a real pattern skews all of them, so the median is the one that
    represents the fabric."""
    import statistics
    try:
        img = Image.open(image_path)
        alpha = np.array(img.getchannel("A")) if "A" in img.getbands() else None
        arr = np.array(img.convert("RGB"))
    except Exception:
        return None
    h, w, _ = arr.shape
    mask = _fabric_mask(arr, alpha)
    ys, xs = np.where(mask)
    if len(ys) < 200:
        return None
    gx0, gx1, gy0, gy1 = xs.min(), xs.max(), ys.min(), ys.max()
    side = max(12, int(min(gx1 - gx0, gy1 - gy0) * 0.16))
    found = []
    for fy in (0.42, 0.55, 0.32):
        for fx in (0.28, 0.72, 0.5, 0.20, 0.80):
            cx = int(gx0 + (gx1 - gx0) * fx)
            cy = int(gy0 + (gy1 - gy0) * fy)
            L, T = cx - side // 2, cy - side // 2
            if L < 0 or T < 0 or L + side > w or T + side > h:
                continue
            if not mask[T:T + side, L:L + side].all():
                continue
            found.append(arr[T:T + side, L:L + side])
            if len(found) >= 3:
                break
        if len(found) >= 3:
            break
    if not found:
        return None
    stds = [c.reshape(-1, 3).astype(float).std(axis=0).mean() for c in found]
    med = statistics.median(stds)
    best = found[min(range(len(stds)), key=lambda i: abs(stds[i] - med))]
    tile = Image.fromarray(best).resize((SWATCH_TILE_PX, SWATCH_TILE_PX), Image.LANCZOS)
    return tile


def build_pattern_swatches(catalog, product_id=None):
    """Write a `<colour>_swatch.jpg` tile for every patterned colour that
    doesn't have one, and record it on the colour as `swatch`. Skips work
    already done, so re-running is cheap."""
    made = skipped = failed = 0
    for prod in catalog.get("products", []):
        if product_id and prod.get("id") != product_id:
            continue
        for col in prod.get("colors", []):
            if not PATTERN_NAME_RE.search(col.get("name", "")):
                col.pop("swatch", None)      # a renamed colour stops being patterned
                continue
            rel = f"catalog_images/{prod['id']}/{slugify(col['name'])}_swatch.jpg"
            if Path(rel).exists():
                col["swatch"] = rel
                skipped += 1
                continue
            tile = extract_pattern_tile(col.get("front", ""))
            if tile is None:
                col.pop("swatch", None)
                failed += 1
                continue
            Path(rel).parent.mkdir(parents=True, exist_ok=True)
            tile.save(rel, quality=92)
            col["swatch"] = rel
            made += 1
    return made, skipped, failed


def warn_about_id_collisions(catalog, product_id, brand, style):
    """Catch the two ways a product quietly ends up broken in the catalog.

    Both actually happened. Typing the brand as "BellaCanvas" once and
    "Bella/Canvas" another time produced ids `bellacanvas-3001y` and
    `bella-canvas-3001y` -- two entries for the same shirt, and since the
    photos only ever went into one folder, the other showed 39 broken
    thumbnails on the live catalog page. Separately, passing a <brand> that
    already ended in the style number produced `bella-canvas-6400-cvc-6400-cvc`,
    whose images were written under a different folder than the entry pointed
    at, breaking all 33 of its colours the same way.

    Warn rather than refuse: a genuinely new style whose name resembles an
    existing one is legitimate, and this script isn't in a position to know
    the difference."""
    def norm(t):
        return re.sub(r"[^a-z0-9]", "", (t or "").lower())

    key = norm(f"{brand}{style}")
    for p in catalog.get("products", []):
        if p.get("id") == product_id:
            continue
        if norm(f"{p.get('brand','')}{p.get('style','')}") == key:
            print(f"\n  ! WARNING: '{p['id']}' is already {p.get('brand')} {p.get('style')} --")
            print(f"    the same product as this run's '{product_id}', just slugged differently.")
            print(f"    You'll end up with two entries and one of them will have no photos.")
            print(f"    Re-run using the brand spelled exactly as '{p.get('brand')}' to update it instead.\n")

    if norm(style) and product_id.count(slugify(style)) > 1:
        print(f"\n  ! WARNING: the style '{style}' appears twice in the generated id")
        print(f"    '{product_id}' -- the <brand> argument probably already contains it.")
        print(f"    Pass just the brand name (e.g. \"Bella/Canvas\", not \"Bella/Canvas 6400CVC\").\n")


def run_description_scrape(site, source, brand, style, csv_path, want_fetch=True):
    """--descriptions: hand the same saved page to build_descriptions.py so the
    product's write-up lands in the bulk-import CSV in the same run as its
    photos. Deliberately non-fatal -- the catalog entry and images are already
    written and correct by the time this runs, so a description that can't be
    found is a note to follow up on, never a reason to fail the run."""
    print("\n--- descriptions (--descriptions) ---")
    if site == "sanmar-pdf":
        print("  A Media Library PDF has no description text in it -- skipping.")
        print("  Save the SanMar product PAGE and run:")
        print(f"    python3 build_descriptions.py scrape --site sanmar <page.html> \"{brand}\" {style}")
        return
    try:
        import build_descriptions as bd
    except ImportError:
        print("  build_descriptions.py isn't next to this script -- skipping.")
        return

    csv_path = csv_path or bd.DEFAULT_CSV
    try:
        found = bd.scrape_page(source, site)
    except Exception as e:
        print(f"  ! couldn't read a write-up off that page: {e}")
        return

    product = f"{brand} {style}".strip()
    if not found["description"] and not found["features"]:
        print(f"  Nothing usable found for '{product}'. To see what the page did offer:")
        print(f"    python3 build_descriptions.py scrape --site {site} {source} \"{brand}\" {style} --dump")
        return

    print(f"  Description : {found['description_source'] or 'not found'}")
    print(f"  Features    : {found['features_source'] or 'not found'} ({len(found['features'])} bullet(s))")
    print(f"  Supplier    : {found['supplier_note'] or '(none found)'}")

    rows = bd.read_csv(csv_path)
    what, _ = bd.merge_row(rows, product, found["description"],
                           found["features"], found["supplier_note"])
    bd.write_csv(csv_path, rows)
    print(f"  {what.capitalize()} '{product}' in {Path(csv_path).resolve()}")

    # The page had specs but nothing describing the garment -- the normal case
    # on S&S. Go get one from the manufacturer rather than leaving a blank cell
    # and a follow-up step to forget.
    row = next((r for r in rows if r.get("Product") == product), None)
    needs_description = row is not None and not (row.get("Description") or "").strip()
    if needs_description and want_fetch:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("\n  No description on that page (normal for S&S -- its spec list IS its copy).")
            print("  Looking one up on the manufacturer's site needs an API key. Set one with:")
            print("    python3 build_descriptions.py setkey")
            print(f"  then: python3 build_descriptions.py fetch --only \"{product}\"")
            return
        print("\n  No description on that page (normal for S&S -- its spec list IS its copy).")
        print("  Looking one up on the manufacturer's own site. This does a live web")
        print("  search and costs a few cents; pass --no-fetch to skip it.\n")
        try:
            args = argparse.Namespace(
                csv=csv_path, only=product, from_catalog=False,
                catalog="catalog.json", limit=None, domains=None,
                model="claude-opus-5",
            )
            bd.cmd_fetch(args)
        except SystemExit:
            pass
        except Exception as e:
            print(f"  ! the lookup failed ({e}). The photos and catalog entry are fine;")
            print(f"    retry with: python3 build_descriptions.py fetch --only \"{product}\"")
        return
    if needs_description:
        print(f"  No description found. To look one up on the manufacturer's site:")
        print(f"    python3 build_descriptions.py fetch --only \"{product}\"")
        return
    print("  Import it from Product Admin -> Bulk tools, or reword it first:")
    print(f"    python3 build_descriptions.py polish --only \"{product}\"")


def main():
    args = sys.argv[1:]
    if len(args) < 2 or args[0] != "--site":
        print(f"Usage: python3 {sys.argv[0]} --site <site> <html_file> <brand> <style> <product_name> <kind> [catalog.json]")
        print(f"  site: {' | '.join(EXTRACTORS)}")
        print("  kind: tee | hoodie | cap | tote")
        sys.exit(1)

    site = args[1]
    rest = args[2:]
    if site not in EXTRACTORS:
        print(f"Unknown site '{site}'. Choose one of: {', '.join(EXTRACTORS)}")
        sys.exit(1)

    # Optional crop flags -- can appear anywhere after the positional args.
    # Trims a fraction off each edge before saving, e.g. to cut heads/legs
    # out of on-model photos (Royal Apparel has no flat product shots).
    # Not tied to any one site -- harmless (0.0) unless you pass them.
    crop = {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0}
    CROP_FLAGS = {
        "--crop-top": "top", "--crop-bottom": "bottom",
        "--crop-left": "left", "--crop-right": "right",
    }
    # --descriptions [csv]: after the images/catalog.json work is done, also
    # run build_descriptions.py's scraper over the SAME saved page and merge
    # this product's write-up into the CSV the Product Admin bulk importer
    # reads. Optional and off by default -- the page is already in memory, so
    # this costs one extra parse and no extra downloads.
    descriptions_csv = None
    # ON BY DEFAULT. It was opt-in at first, and the result was a product added
    # with its photos and catalog entry but no write-up -- which looks like a
    # silent failure, because nothing says the step was skipped. Adding a
    # product and describing it are the same job in practice, so the default is
    # to do both; --no-descriptions opts out.
    want_descriptions = True
    # Also ON BY DEFAULT, and it matters most where the scrape can't help: an
    # S&S page carries no prose about the garment at all, and S&S is most of
    # this catalog. Without this, "add a product" reliably ends with an empty
    # description and a second command nobody remembers to run. This one costs
    # money (a live web search, a few cents), so --no-fetch turns it off.
    want_fetch = True

    cleaned = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--no-descriptions":
            want_descriptions = False
            i += 1
            continue
        if arg == "--no-fetch":
            want_fetch = False
            i += 1
            continue
        if arg == "--descriptions":
            want_descriptions = True
            nxt = rest[i + 1] if i + 1 < len(rest) else None
            if nxt and not nxt.startswith("--") and nxt.lower().endswith(".csv"):
                descriptions_csv = nxt
                i += 2
            else:
                i += 1
            continue
        if arg in CROP_FLAGS:
            if i + 1 >= len(rest):
                print(f"{arg} needs a value (fraction between 0 and 0.49, e.g. {arg} 0.18)")
                sys.exit(1)
            try:
                val = float(rest[i + 1])
            except ValueError:
                print(f"{arg} needs a number (fraction between 0 and 0.49, e.g. {arg} 0.18)")
                sys.exit(1)
            if not (0 <= val < 0.5):
                print(f"{arg} {val} is out of range -- use a fraction between 0 and 0.49.")
                sys.exit(1)
            crop[CROP_FLAGS[arg]] = val
            i += 2
        else:
            cleaned.append(arg)
            i += 1
    rest = cleaned
    cropping = any(v > 0 for v in crop.values())

    if len(rest) < 5:
        print(f"Usage: python3 {sys.argv[0]} --site <site> <html_file> <brand> <style> <product_name> <kind> [catalog.json] [--crop-top F] [--crop-bottom F] [--crop-left F] [--crop-right F] [--descriptions [file.csv] | --no-descriptions] [--no-fetch]")
        sys.exit(1)

    source, brand, style, product_name, kind = rest[:5]
    catalog_path = Path(rest[5]) if len(rest) > 5 else Path("catalog.json")

    KNOWN_KINDS = ("tee", "hoodie", "cap", "hat", "tote", "beanie", "sweatshirt", "tank")
    if kind not in KNOWN_KINDS:
        print(f"Warning: kind '{kind}' isn't one of the mockup tool's known categories ({'/'.join(KNOWN_KINDS)}).")
        print("The catalog entry will still be written and work fine -- this only means it'll get its own")
        print("dropdown group in the tool instead of joining an existing one, which is harmless either way.")

    if site == "sanmar":
        print("Note: SanMar pages are per-color. This run will add/refresh ONE")
        print("color; run again with a different saved page for each additional color.")
    if site == "sanmar-pdf":
        print("Note: reading a SanMar Media Library PDF export -- this covers")
        print("every color found in the PDF in one run (no per-color HTML needed).")
    if cropping:
        print(f"Note: cropping each photo by top={crop['top']} bottom={crop['bottom']} "
              f"left={crop['left']} right={crop['right']} before saving.")

    product_id = slugify(f"{brand}-{style}")
    image_dir = Path("catalog_images") / product_id
    image_dir.mkdir(parents=True, exist_ok=True)

    preextracted = site in PREEXTRACTED_IMAGE_SITES
    print(f"Reading {source} (site: {site}) ...")
    if preextracted:
        colors_raw = EXTRACTORS[site](source)
    else:
        html = read_html(source)
        colors_raw = EXTRACTORS[site](html)
    print(f"Found {len(colors_raw)} color option(s).")

    new_colors = []
    skipped = []

    for entry in colors_raw:
        name = entry["name"]

        if preextracted:
            front_img, back_img = entry.get("front_img"), entry.get("back_img")
            if front_img is None or back_img is None:
                skipped.append((name, "missing front or back image"))
                continue
            out_ext = "png"  # preserve alpha transparency from the PDF cutouts
        else:
            front_url, back_url = entry.get("front"), entry.get("back")
            if not front_url or not back_url:
                skipped.append((name, "missing front or back image URL on this page"))
                continue
            print(f"  {name}: downloading front/back...")
            if site == "ssactivewear":
                front_img = bct.download_image(entry["_ss_relpath_front"], DOWNLOAD_CACHE_DIR)
                back_img = bct.download_image(entry["_ss_relpath_back"], DOWNLOAD_CACHE_DIR)
            else:
                front_img = download_image_url(front_url, DOWNLOAD_CACHE_DIR)
                back_img = download_image_url(back_url, DOWNLOAD_CACHE_DIR)
            if front_img is None or back_img is None:
                skipped.append((name, "one or both images failed to download"))
                continue
            out_ext = "jpg"

        if cropping:
            front_img = crop_fraction(front_img, **crop)
            back_img = crop_fraction(back_img, **crop)

        color_slug = slugify(name)
        front_out = image_dir / f"{color_slug}_front.{out_ext}"
        back_out = image_dir / f"{color_slug}_back.{out_ext}"
        if out_ext == "png":
            front_img.save(front_out)
            back_img.save(back_out)
        else:
            front_img.convert("RGB").save(front_out, quality=90)
            back_img.convert("RGB").save(back_out, quality=90)

        hex_color = sample_swatch_hex(front_img)

        new_colors.append({
            "name": name,
            "hex": hex_color,
            "front": f"catalog_images/{product_id}/{front_out.name}",
            "back": f"catalog_images/{product_id}/{back_out.name}",
        })

    if not new_colors:
        print("No colors were processed successfully -- nothing to add to the catalog.")
        sys.exit(1)

    catalog = load_catalog(catalog_path)
    warn_about_id_collisions(catalog, product_id, brand, style)
    existing = next((p for p in catalog["products"] if p.get("id") == product_id), None)
    popular_value = existing.get("popular", False) if existing else False

    if existing:
        # Merge into whatever this product already has -- this is what
        # makes SanMar's one-color-per-run workflow build up correctly,
        # and also means re-running any site to pick up ONE newly-added
        # color doesn't require re-downloading colors that didn't change.
        merged = {c["name"]: c for c in existing.get("colors", [])}
        for c in new_colors:
            merged[c["name"]] = c
        final_colors = list(merged.values())
    else:
        final_colors = new_colors

    catalog["products"] = [p for p in catalog["products"] if p.get("id") != product_id]
    catalog["products"].append({
        "id": product_id,
        "name": product_name,
        "brand": brand,
        "style": style,
        "kind": kind,
        "popular": popular_value,
        "colors": final_colors,
    })
    # Do this before saving, and over the WHOLE catalog rather than just this
    # product -- the colour a new two-tone name needs may live on a product
    # added months ago, and vice versa.
    # Named tiles_* deliberately. These were unpacked as `made, skipped, failed`
    # once, which silently rebound `skipped` -- the list of colours that failed
    # to download, built further up and printed further down -- to an int. The
    # run then crashed on len(skipped) AFTER writing catalog.json but BEFORE
    # reading the product's description, so the product appeared complete while
    # its write-up was silently never fetched.
    tiles_made, tiles_existing, tiles_failed = build_pattern_swatches(catalog)
    if tiles_made or tiles_failed:
        print(f"\nPattern swatches: {tiles_made} new tile(s) cut from the product photos"
              + (f", {tiles_failed} colour(s) had no clean patch of fabric to cut from" if tiles_failed else ""))

    resolved, unresolved = annotate_multi_colour_swatches(catalog)
    if resolved or unresolved:
        print(f"\nTwo-tone swatches: {resolved} colour(s) resolved into components, "
              f"{unresolved} left as a single averaged swatch.")

    save_catalog(catalog_path, catalog)

    # Merging keeps colors that were added by earlier runs, which is what makes
    # the one-color-per-run SanMar workflow work -- but it also silently keeps a
    # color the vendor has since RENAMED or discontinued. Its swatch stays on
    # the catalog and product pages pointing at an image that was never saved,
    # so it renders as an empty square. ("Athletic Heather" on Bella/Canvas 6400
    # was exactly this: S&S now lists it as "Solid Athletic Grey".)
    stale = [c for c in final_colors
             if not Path(c["front"]).exists() or not Path(c["back"]).exists()]
    if stale:
        print(f"\n  ! {len(stale)} color(s) on this product have no image file on disk:")
        for c in stale:
            print(f"      - {c['name']}")
        print("    They aren't on the page you just saved, so they were left untouched rather")
        print("    than deleted. If the vendor renamed or discontinued them, remove them from")
        print(f"    {catalog_path} -- otherwise they show as blank swatches on the live site.")

    print(f"\nDone.")
    print(f"Images saved under: {image_dir.resolve()}")
    print(f"Catalog updated: {catalog_path.resolve()}")
    print(f"Colors added/updated this run: {len(new_colors)}")
    print(f"Total colors now on this product: {len(final_colors)}")
    if skipped:
        print(f"\nSkipped {len(skipped)} color(s):")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")

    if want_descriptions:
        run_description_scrape(site, source, brand, style, descriptions_csv, want_fetch)

    if site == "sanmar":
        style_num, all_slugs = sanmar_list_other_colors(html)
        if all_slugs:
            have = {slugify(c["name"]) for c in final_colors}
            remaining = [s for s in all_slugs if slugify(s) not in have]
            if remaining:
                print(f"\nOther colors found on this page you haven't saved/added yet ({len(remaining)}):")
                for s in remaining:
                    print(f"  https://www.sanmar.com/p/{style_num}_{s}")
            else:
                print("\nAll colors listed on this page have been added -- nothing left for this style.")


if __name__ == "__main__":
    main()
