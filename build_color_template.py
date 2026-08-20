"""
build_color_template.py

Scrapes a S&S Activewear product page for every color option's front/back
product images, then builds a single 9.5" x 5.5" @ 150 DPI .psd file with
one named, editable layer per color. Only the first color is left visible;
the rest are hidden layers you can toggle in Photoshop's Layers panel.

Two layout modes:
  split  (default) -- front and back shown at equal size, side by side.
                       Good for shirts and other garments.
  hat            -- front shown large (~3/4 width) as a "hero" shot, with
                       a smaller back image tucked next to it. The back
                       image has its white background automatically
                       removed so it can sit close to the front without
                       a visible white box around it.

WHY THIS RUNS LOCALLY, NOT IN A CHAT SANDBOX:
This script needs open internet access to ssactivewear.com and its image
CDN. Run it on your own machine.

SETUP (one time):
    pip install requests pillow numpy scipy pytoshop psd-tools six cloudscraper

USAGE:
    python3 build_color_template.py "https://www.ssactivewear.com/p/bella/3001?color=white-solid" bella_3001_colors.psd
    python3 build_color_template.py page_3001.html bella_3001_colors.psd
    python3 build_color_template.py page_richardson256.html richardson_256.psd hat

NOTES / THINGS TO SANITY-CHECK ON YOUR FIRST RUN:
- The image URL pattern below (CDN_IMAGE_URL_TEMPLATE) was reverse-engineered
  from one live page and looks consistent, but S&S can change their CDN
  paths without notice. If images come back missing/broken, open one
  downloaded file to check it's a real photo and not an error page, and
  adjust CDN_IMAGE_URL_TEMPLATE / the size suffix (_fl = large, _fm = medium,
  _fs = small) if needed.
- Discontinued colors, or colors where a photo is genuinely missing, will
  be skipped automatically and reported at the end.
- pytoshop has a bug in its RLE compressor in some versions, so this script
  uses raw (uncompressed) channel data -- the PSD will be larger on disk
  but opens identically in Photoshop.
- Background removal (hat layout) works by removing near-white pixels that
  are connected to the image's outer edge, so it correctly leaves alone any
  white logos/text/embroidery fully enclosed within the product itself. It's
  tuned for clean studio product photos on a plain white background -- if a
  particular photo has a slightly off-white or textured background, the cutout
  may need a manual touch-up in Photoshop afterward.
"""

import io
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageFilter
from scipy import ndimage

import pytoshop
from pytoshop import image_resources as ir
from pytoshop import layers as pl
from pytoshop.enums import ColorMode, Compression

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

CDN_IMAGE_URL_TEMPLATE = "https://cdn.ssactivewear.com/Images/{path}_fl.jpg"
CANVAS_WIDTH_IN = 9.5
CANVAS_HEIGHT_IN = 5.5
DPI = 150
IMAGE_AREA_FRACTION_OF_HEIGHT = 0.85  # how tall each garment shot can be
MARGIN_PX = 20   # margin around each image within its own half of the canvas

# --- "hat" layout settings ---
HAT_FRONT_WIDTH_FRACTION = 0.72   # how much of the canvas width the front image occupies
HAT_BACK_HEIGHT_FRACTION = 0.62   # back image's height, relative to the front image's height
HAT_GAP_PX = 10                   # gap between the front image and the cutout back image
BG_REMOVE_WHITE_THRESHOLD = 235   # pixels with all RGB channels >= this are treated as "white"
BG_REMOVE_FEATHER_RADIUS = 1.2    # softens the cutout edge so it isn't jagged

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.ssactivewear.com/",
}
DOWNLOAD_CACHE_DIR = Path("downloaded_images")

try:
    import cloudscraper  # type: ignore
    SESSION = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "mobile": False}
    )
    print("(using cloudscraper for requests)")
except ImportError:
    SESSION = requests.Session()
    print(
        "(cloudscraper not installed -- if you keep getting 403 errors, run:\n"
        "   pip install cloudscraper\n"
        "and try again)"
    )

SESSION.headers.update(REQUEST_HEADERS)


# ---------------------------------------------------------------------------
# STEP 1: scrape the product page for the color/image JSON blob
# ---------------------------------------------------------------------------

def fetch_color_data(product_url_or_file: str):
    # If it looks like a local file (not a URL), read it directly instead of
    # making an HTTP request. This is the recommended path if the live site
    # is blocking scripted requests (403 errors) -- save the product page
    # from your browser (File > Save Page As > "Webpage, HTML Only") and
    # pass that file's path instead of the URL.
    looks_like_url = product_url_or_file.lower().startswith(("http://", "https://"))

    if looks_like_url:
        resp = SESSION.get(product_url_or_file, timeout=30)
        resp.raise_for_status()
        html = resp.text
    else:
        file_path = Path(product_url_or_file)
        if not file_path.exists():
            raise RuntimeError(
                f"'{product_url_or_file}' is not a URL and no such file exists. "
                "Pass either a live https:// URL or the path to a saved .html file."
            )
        html = file_path.read_text(encoding="utf-8", errors="ignore")

    # The page embeds a raw JSON array of color objects, each with a
    # colorStyleID, a display "name", and an "Images" list of relative
    # CDN paths. We locate it by finding the first '[{"styleID":' occurrence
    # and matching balanced brackets from there.
    marker = '[{"styleID":'
    start = html.find(marker)
    if start == -1:
        raise RuntimeError(
            "Could not find the color/image JSON block on this page. "
            "S&S may have changed their page structure -- open the page "
            "source and search for 'styleID' to locate the new format."
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

    colors = json.loads(html[start:end])
    return colors


def pick_front_back_paths(color_entry):
    """Given one color's dict, return (front_path, back_path) or (None, None)."""
    images = color_entry.get("Images", [])
    front = next((p for p in images if p.endswith("_f")), None)
    back = next((p for p in images if p.endswith("_b")), None)
    return front, back


# ---------------------------------------------------------------------------
# STEP 2: download images
# ---------------------------------------------------------------------------

def download_image(path: str, cache_dir: Path) -> Image.Image | None:
    url = CDN_IMAGE_URL_TEMPLATE.format(path=path)
    safe_name = path.replace("/", "_") + ".jpg"
    cache_file = cache_dir / safe_name

    if cache_file.exists():
        try:
            return Image.open(cache_file).convert("RGBA")
        except Exception:
            pass  # fall through and re-download

    try:
        resp = SESSION.get(url, timeout=30)
        if resp.status_code != 200 or len(resp.content) < 500:
            return None
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        cache_dir.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(cache_file, quality=95)
        return img
    except Exception as e:
        print(f"  ! download failed for {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# STEP 3: build the PSD
# ---------------------------------------------------------------------------

def fit(im: Image.Image, box_w: int, box_h: int) -> Image.Image:
    ratio = min(box_w / im.width, box_h / im.height)
    new_w = max(1, int(im.width * ratio))
    new_h = max(1, int(im.height * ratio))
    return im.resize((new_w, new_h), Image.LANCZOS)


def remove_white_background(im: Image.Image) -> Image.Image:
    """Make the background transparent, leaving interior white areas (logos,
    embroidery, text) intact. Only near-white pixels connected to the image's
    outer edge are removed, so a white design in the middle of the product
    is never touched."""
    im = im.convert("RGBA")
    arr = np.array(im)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3].copy()

    near_white = np.all(rgb >= BG_REMOVE_WHITE_THRESHOLD, axis=-1)

    structure = np.ones((3, 3), dtype=int)  # 8-connectivity
    labels, _ = ndimage.label(near_white, structure=structure)

    border_labels = (
        set(labels[0, :].tolist()) | set(labels[-1, :].tolist())
        | set(labels[:, 0].tolist()) | set(labels[:, -1].tolist())
    )
    border_labels.discard(0)

    background_mask = np.isin(labels, list(border_labels))
    alpha[background_mask] = 0

    alpha_img = Image.fromarray(alpha, mode="L").filter(
        ImageFilter.GaussianBlur(radius=BG_REMOVE_FEATHER_RADIUS)
    )
    arr[:, :, 3] = np.array(alpha_img)
    return Image.fromarray(arr, mode="RGBA")


def autocrop_transparent(im: Image.Image, padding: int = 4) -> Image.Image:
    """Crop a transparent-background image down to its visible content."""
    alpha = im.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return im
    left, top, right, bottom = bbox
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(im.width, right + padding)
    bottom = min(im.height, bottom + padding)
    return im.crop((left, top, right, bottom))


def find_content_bottom(im: Image.Image) -> int:
    """Measure where an image's actual subject ends vertically, ignoring
    surrounding white padding -- without altering the image itself. Used so
    'bottom align' means the real garment edges line up, not the edges of
    each photo's frame (which often have differing amounts of white space
    below the subject)."""
    probe = remove_white_background(im)
    bbox = probe.getchannel("A").getbbox()
    if bbox is None:
        return im.height - 1
    return bbox[3]  # bottom y of the content, in this image's own coordinates


def compose_hat_canvas(front_im, back_im, canvas_w, canvas_h):
    """Large front 'hero' shot with a smaller, background-removed back shot
    tucked in next to it -- for hats and similar products where the back
    view is more of a supporting detail than an equal partner to the front."""
    base = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    front_target_h = int(canvas_h * IMAGE_AREA_FRACTION_OF_HEIGHT)
    back_target_h = int(front_target_h * HAT_BACK_HEIGHT_FRACTION)

    front_box_w = int(canvas_w * HAT_FRONT_WIDTH_FRACTION)
    back_box_w = canvas_w - front_box_w

    # Front keeps its normal white-background look -- we only use background
    # detection to *measure* where its real content ends, not to alter it.
    f = fit(front_im.convert("RGBA"), front_box_w - MARGIN_PX * 2, front_target_h)
    front_content_bottom = find_content_bottom(f)

    back_cut = autocrop_transparent(remove_white_background(back_im))
    b = fit(back_cut, back_box_w - MARGIN_PX, back_target_h)

    pair_width = f.width + HAT_GAP_PX + b.width
    start_x = (canvas_w - pair_width) // 2

    fx = start_x
    fy = (canvas_h - f.height) // 2
    bx = fx + f.width + HAT_GAP_PX
    # Align the back cutout's bottom edge with the front's *actual visible
    # content* bottom edge, not the bottom of its (often padded) photo frame.
    by = fy + front_content_bottom - b.height

    base.alpha_composite(f, (fx, fy))
    base.alpha_composite(b, (bx, by))
    return base


def compose_color_canvas(front_im, back_im, canvas_w, canvas_h):
    base = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    target_h = int(canvas_h * IMAGE_AREA_FRACTION_OF_HEIGHT)

    # Split the canvas into two equal halves; each image is fit to and
    # centered within its own half. This gives even margins around each
    # image, plus a natural gap where the two halves meet in the middle.
    half_w = canvas_w // 2
    f = fit(front_im, half_w - MARGIN_PX * 2, target_h)
    b = fit(back_im, half_w - MARGIN_PX * 2, target_h)

    fx = (half_w - f.width) // 2
    fy = (canvas_h - f.height) // 2
    bx = half_w + (half_w - b.width) // 2
    by = (canvas_h - b.height) // 2

    base.alpha_composite(f, (fx, fy))
    base.alpha_composite(b, (bx, by))
    return base


def channels_from_rgba(pil_rgba_image):
    arr = np.array(pil_rgba_image)
    return {
        0: pl.ChannelImageData(image=arr[:, :, 0], compression=Compression.raw),
        1: pl.ChannelImageData(image=arr[:, :, 1], compression=Compression.raw),
        2: pl.ChannelImageData(image=arr[:, :, 2], compression=Compression.raw),
        -1: pl.ChannelImageData(image=arr[:, :, 3], compression=Compression.raw),
    }


def resolution_info_block(dpi: int) -> ir.GenericImageResourceBlock:
    fixed = int(dpi * 65536)
    data = struct.pack(">ihhihh", fixed, 1, 1, fixed, 1, 1)
    return ir.GenericImageResourceBlock(resource_id=1005, name="", data=data)


def build_psd(color_layers: list[tuple[str, Image.Image]], out_path: Path):
    """color_layers: list of (color_name, composited_rgba_canvas), in the
    order you want them from BOTTOM to TOP in the final Photoshop stack."""
    canvas_w = int(CANVAS_WIDTH_IN * DPI)
    canvas_h = int(CANVAS_HEIGHT_IN * DPI)

    layer_records = []
    for i, (name, canvas) in enumerate(color_layers):
        is_last = i == len(color_layers) - 1  # last in list = top of stack = visible
        lr = pl.LayerRecord(
            channels=channels_from_rgba(canvas),
            top=0, bottom=canvas_h, left=0, right=canvas_w,
            blend_mode=b"norm",
            name=name,
            opacity=255,
            visible=is_last,
        )
        layer_records.append(lr)

    layers = pl.LayerAndMaskInfo(layer_info=pl.LayerInfo(layer_records=layer_records))
    image_resources = ir.ImageResources(blocks=[resolution_info_block(DPI)])

    pf = pytoshop.core.PsdFile(
        num_channels=4,
        height=canvas_h,
        width=canvas_w,
        color_mode=ColorMode.rgb,
        depth=8,
        layer_and_mask_info=layers,
        image_resources=image_resources,
    )
    with open(out_path, "wb") as f:
        pf.write(f)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print(f"Usage: python3 {sys.argv[0]} <product_url_or_saved_html_file> <output.psd> [layout]")
        print("  layout: 'split' (default, equal-size side by side) or 'hat' (large front + small cutout back)")
        sys.exit(1)

    product_url = sys.argv[1]
    out_path = Path(sys.argv[2])
    layout = sys.argv[3] if len(sys.argv) > 3 else "split"
    if layout not in ("split", "hat"):
        print(f"Unknown layout '{layout}' -- use 'split' or 'hat'.")
        sys.exit(1)
    compose_fn = compose_hat_canvas if layout == "hat" else compose_color_canvas

    print(f"Fetching color data from {product_url} ...")
    colors = fetch_color_data(product_url)
    print(f"Found {len(colors)} color options. Using '{layout}' layout.")

    color_layers = []
    skipped = []

    for entry in colors:
        name = entry["name"]
        front_path, back_path = pick_front_back_paths(entry)
        if not front_path or not back_path:
            skipped.append((name, "missing front or back path in page data"))
            continue

        print(f"  {name}: downloading front/back...")
        front_img = download_image(front_path, DOWNLOAD_CACHE_DIR)
        back_img = download_image(back_path, DOWNLOAD_CACHE_DIR)

        if front_img is None or back_img is None:
            skipped.append((name, "one or both images failed to download"))
            continue

        canvas_w = int(CANVAS_WIDTH_IN * DPI)
        canvas_h = int(CANVAS_HEIGHT_IN * DPI)
        composed = compose_fn(front_img, back_img, canvas_w, canvas_h)
        color_layers.append((name, composed))

    if not color_layers:
        print("No color layers were built successfully -- nothing to save.")
        sys.exit(1)

    # Reverse so the FIRST color in the site's list ends up visible/on top.
    color_layers.reverse()

    print(f"Building PSD with {len(color_layers)} color layers -> {out_path}")
    build_psd(color_layers, out_path)

    print("\nDone.")
    print(f"Saved: {out_path.resolve()}")
    if skipped:
        print(f"\nSkipped {len(skipped)} color(s):")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")


if __name__ == "__main__":
    main()
