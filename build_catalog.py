"""
build_catalog.py  (multi-site version)

Companion to build_color_template.py. Downloads clean, human-readable
front/back images per color -- named after YOUR product info (brand/style/
color), not any vendor's internal IDs -- and writes a catalog.json entry in
the exact shape the Ink Pusher Mockup Studio tool expects.

Supports four vendor sites, each with its own small "extractor" function
(everything downstream -- downloading, renaming, writing catalog.json -- is
identical regardless of site):

    ssactivewear   S&S Activewear   (original, unchanged)
    sanmar         SanMar
    royalapparel   Royal Apparel
    ascolour       AS Colour

SETUP (one time):
    pip install requests pillow numpy scipy pytoshop psd-tools six cloudscraper

USAGE:
    python build_catalog.py --site <site> <html_file> <brand> <style> <product_name> <kind> [catalog.json]

    kind must be one of: tee, hoodie, cap, tote

EXAMPLES:
    python build_catalog.py --site ssactivewear bella_3001.html "Bella/Canvas" 3001 "Unisex Heavyweight Tee" tee catalog.json
    python build_catalog.py --site sanmar sanmar_black.html "Port & Co" PC099 "Beach Wash Garment-Dyed Tee" tee catalog.json
    python build_catalog.py --site royalapparel royal_5051.html "Royal Apparel" 5051 "Unisex Short Sleeve Tee" tee catalog.json
    python build_catalog.py --site ascolour ascolour_5026.html "AS Colour" 5026 "Classic Tee" tee catalog.json

IMPORTANT -- SanMar is different from the other three sites:
S&S Activewear, Royal Apparel, and AS Colour all list every color on ONE
product page, so one saved page gives you the whole catalog entry in one
run. SanMar's site is structured with a SEPARATE page per color (the URL
itself contains the color, e.g. .../p/4664_Black vs .../p/4664_White).
That means for SanMar you save and run this script ONCE PER COLOR -- each
run adds or refreshes just that one color in catalog.json, so running it
five times for five saved SanMar color pages builds up a five-color entry
the same way the other sites do it in a single run.

HOW TO SAVE A PAGE (all sites): open the product page in your browser, let
it fully load, then File > Save Page As > "Webpage, HTML Only" (or
"Webpage, Complete" -- either works, this script only reads the .html
file). Pass that saved file's path as <html_file>. Live URLs are NOT
supported for any of these four sites -- all of them either block scripted
requests or load their real product data via JavaScript after the initial
page load, which a saved-after-load page captures but a plain script
fetching the raw URL cannot.

OUTPUT:
    catalog_images/<brand-style-slug>/<color-slug>_front.jpg
    catalog_images/<brand-style-slug>/<color-slug>_back.jpg
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

import io
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
    skipped."""
    m = re.search(r'"product-schema"[^>]*>(\{.*?\})</script>', html, re.S)
    if not m:
        raise RuntimeError(
            "Couldn't find AS Colour's product-schema JSON-LD block on this "
            "page. Make sure you saved a product page, fully loaded."
        )
    data = json.loads(m.group(1))
    images = data.get("image", [])
    GENERIC = {"MAIN", "FRONT", "TURN", "SIDE", "BACK", "LOOSE"}

    front_by_color, back_by_color = {}, {}
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
        low = rest_clean.upper()
        if "TEE_" not in low:
            # Works for "Classic Tee"; other AS Colour products may use a
            # different product-name word than "Tee" -- if extraction comes
            # back empty for a non-tee product, this is the line to adjust.
            continue
        idx = low.index("TEE_") + 4
        cname = rest_clean[idx:]
        if not cname or cname.upper() in GENERIC:
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
    "royalapparel": extract_royalapparel,
    "ascolour": extract_ascolour,
}


# ---------------------------------------------------------------------------
# Main pipeline -- identical regardless of which site the data came from
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    if len(args) < 2 or args[0] != "--site":
        print(f"Usage: python {sys.argv[0]} --site <site> <html_file> <brand> <style> <product_name> <kind> [catalog.json]")
        print(f"  site: {' | '.join(EXTRACTORS)}")
        print("  kind: tee | hoodie | cap | tote")
        sys.exit(1)

    site = args[1]
    rest = args[2:]
    if site not in EXTRACTORS:
        print(f"Unknown site '{site}'. Choose one of: {', '.join(EXTRACTORS)}")
        sys.exit(1)
    if len(rest) < 5:
        print(f"Usage: python {sys.argv[0]} --site <site> <html_file> <brand> <style> <product_name> <kind> [catalog.json]")
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

    product_id = slugify(f"{brand}-{style}")
    image_dir = Path("catalog_images") / product_id
    image_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading {source} (site: {site}) ...")
    html = read_html(source)
    colors_raw = EXTRACTORS[site](html)
    print(f"Found {len(colors_raw)} color option(s).")

    new_colors = []
    skipped = []

    for entry in colors_raw:
        name = entry["name"]
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

        color_slug = slugify(name)
        front_out = image_dir / f"{color_slug}_front.jpg"
        back_out = image_dir / f"{color_slug}_back.jpg"
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
    save_catalog(catalog_path, catalog)

    print(f"\nDone.")
    print(f"Images saved under: {image_dir.resolve()}")
    print(f"Catalog updated: {catalog_path.resolve()}")
    print(f"Colors added/updated this run: {len(new_colors)}")
    print(f"Total colors now on this product: {len(final_colors)}")
    if skipped:
        print(f"\nSkipped {len(skipped)} color(s):")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")

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
