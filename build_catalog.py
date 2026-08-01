"""
build_catalog.py

Companion to build_color_template.py. Instead of building a PSD, this
downloads clean, human-readable front/back images per color -- named after
YOUR product info (brand/style/color), not S&S's internal numeric IDs -- and
writes a catalog.json entry in the exact shape the Ink Pusher Mockup Studio
tool expects.

WHY THIS EXISTS:
S&S's page data only ever gives you a numeric internal colorStyleID (e.g.
"3227"). It has no brand, style, or product name -- so any filenames built
straight from that data are opaque, whether you scrape a live URL or a saved
HTML page. This script asks for that info up front (you already know it)
and bakes it into every filename and into the catalog entry itself.

SETUP (one time, same as build_color_template.py):
    pip install requests pillow numpy scipy pytoshop psd-tools six cloudscraper

USAGE:
    python build_catalog.py <html_or_url> <brand> <style> <product_name> <kind> [catalog.json]

    kind must be one of: tee, hoodie, cap, tote  (matches the mockup tool's
    procedural fallback shapes -- doesn't need to be exact, just consistent)

EXAMPLE:
    python build_catalog.py bella_3001.html "Bella/Canvas" 3001 "Unisex Heavyweight Tee" tee catalog.json

OUTPUT:
    catalog_images/<brand-style-slug>/<color-slug>_front.jpg
    catalog_images/<brand-style-slug>/<color-slug>_back.jpg
    catalog.json  (created if missing, otherwise the new product is appended
                    -- re-running with the same brand+style replaces that
                    product's entry rather than duplicating it)

WHAT STILL NEEDS A HUMAN EYE:
Each color's "hex" swatch is auto-sampled from the actual downloaded photo
(averaging pixels from the garment's center) so you don't have to hand-enter
one for every color -- but it's an approximation. Skim the output and nudge
any that look off before publishing.
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import build_color_template as bct


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


def main():
    if len(sys.argv) < 6:
        print(f"Usage: python {sys.argv[0]} <html_or_url> <brand> <style> <product_name> <kind> [catalog.json]")
        print("  kind: tee | hoodie | cap | tote")
        sys.exit(1)

    source = sys.argv[1]
    brand = sys.argv[2]
    style = sys.argv[3]
    product_name = sys.argv[4]
    kind = sys.argv[5]
    catalog_path = Path(sys.argv[6]) if len(sys.argv) > 6 else Path("catalog.json")

    if kind not in ("tee", "hoodie", "cap", "tote"):
        print(f"Warning: kind '{kind}' isn't one of the mockup tool's known shapes (tee/hoodie/cap/tote).")
        print("The catalog entry will still be written, but the tool won't have a fallback drawing for it.")

    product_id = slugify(f"{brand}-{style}")
    image_dir = Path("catalog_images") / product_id
    image_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching color data from {source} ...")
    colors_raw = bct.fetch_color_data(source)
    print(f"Found {len(colors_raw)} color options.")

    catalog_colors = []
    skipped = []

    for entry in colors_raw:
        name = entry["name"]
        front_path, back_path = bct.pick_front_back_paths(entry)
        if not front_path or not back_path:
            skipped.append((name, "missing front or back path in page data"))
            continue

        print(f"  {name}: downloading front/back...")
        front_img = bct.download_image(front_path, bct.DOWNLOAD_CACHE_DIR)
        back_img = bct.download_image(back_path, bct.DOWNLOAD_CACHE_DIR)

        if front_img is None or back_img is None:
            skipped.append((name, "one or both images failed to download"))
            continue

        color_slug = slugify(name)
        front_out = image_dir / f"{color_slug}_front.jpg"
        back_out = image_dir / f"{color_slug}_back.jpg"
        front_img.convert("RGB").save(front_out, quality=90)
        back_img.convert("RGB").save(back_out, quality=90)

        hex_color = sample_swatch_hex(front_img)

        catalog_colors.append({
            "name": name,
            "hex": hex_color,
            "front": f"catalog_images/{product_id}/{front_out.name}",
            "back": f"catalog_images/{product_id}/{back_out.name}",
        })

    if not catalog_colors:
        print("No colors were processed successfully -- nothing to add to the catalog.")
        sys.exit(1)

    catalog = load_catalog(catalog_path)
    catalog["products"] = [p for p in catalog["products"] if p.get("id") != product_id]
    catalog["products"].append({
        "id": product_id,
        "name": product_name,
        "brand": brand,
        "style": style,
        "kind": kind,
        "popular": True,
        "colors": catalog_colors,
    })
    save_catalog(catalog_path, catalog)

    print(f"\nDone.")
    print(f"Images saved under: {image_dir.resolve()}")
    print(f"Catalog updated: {catalog_path.resolve()}")
    print(f"Colors added: {len(catalog_colors)}")
    if skipped:
        print(f"\nSkipped {len(skipped)} color(s):")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")


if __name__ == "__main__":
    main()
