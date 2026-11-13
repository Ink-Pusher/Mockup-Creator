"""
hat_tags.py -- the "Hat details" tags (panels, closure, fabric, structured or not) on hats in
catalog.json, read off each hat's name and its write-up's feature bullets. They drive the Headwear
filter chips on the catalog page and the hat resource guide's links (inkpusher.com/hat-resource-guide).

Used by build_catalog.py (one product at a time) and bulk_add.py (lists). Re-tag every hat with:
    python3 bulk_add.py tag-hats
A hat with "hatTagsManual": true in catalog.json is left alone.
"""
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
HAT_KINDS = ("hat", "cap")
HAT_RULES = [
    ("trucker",      r"trucker|mesh back"),
    ("dad",          r"\bdad\b|unstructured.*low[- ]profile|low[- ]profile.*unstructured"),
    ("structured",   r"(?<!un)structured"),
    ("unstructured", r"unstructured"),
    ("5-panel",      r"\b5[- ]panel|five[- ]panel"),
    ("6-panel",      r"\b6[- ]panel|six[- ]panel"),
    ("7-panel",      r"\b7[- ]panel|seven[- ]panel"),
    ("snapback",     r"snap ?back|plastic snap|snap closure"),
    ("hook-loop",    r"hook[- ]and[- ]loop|hook & loop|velcro"),
    ("buckle",       r"buckle|slide closure|tri-glide|brass"),
    ("fitted",       r"\bfitted\b|flexfit|stretch[- ]fit|stretch band"),
    ("bucket",       r"bucket"),
    ("corduroy",     r"corduroy"),
    ("cotton-twill", r"\btwill\b"),
    ("mesh",         r"\bmesh\b"),
    ("wool",         r"\bwool"),
]
CLOSURES = {"snapback", "hook-loop", "buckle"}


def _norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def hat_tags(p, desc):
    text = (p["name"] + " " + desc.get(_norm(f"{p['brand']} {p['style']}"), "")).lower()
    tags = [t for t, rx in HAT_RULES if re.search(rx, text)]
    if "fitted" in tags and CLOSURES & set(tags):
        tags.remove("fitted")   # Flexfit 110 etc.: stretch band, but adjustable at the back
    return tags


def _descs(csv_path):
    out = {}
    if csv_path.exists():
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[_norm(r.get("Product", ""))] = (r.get("Description") or "") + " " + (r.get("Features") or "")
    return out


def tag_hats(catalog_path=None, only_id=None, quiet=False, csv_path=None):
    """(Re)tag hats in catalog.json; only_id limits it to one product. Returns how many changed.
    Never raises: tagging is a nice-to-have and must never break adding a product."""
    try:
        catalog_path = Path(catalog_path or HERE / "catalog.json")
        cat = json.loads(catalog_path.read_text())
        desc, n = _descs(Path(csv_path or HERE / "product_descriptions.csv")), 0
        for p in cat["products"]:
            if p.get("kind") not in HAT_KINDS or p.get("hatTagsManual"):
                continue
            if only_id and p["id"] != only_id:
                continue
            tags = hat_tags(p, desc)
            if p.get("hatTags") != tags:
                p["hatTags"] = tags
                n += 1
            if not quiet:
                print(f"  {p['id']:22s} {', '.join(tags) or '(none)'}")
        if n:
            catalog_path.write_text(json.dumps(cat, indent=2))
        return n
    except Exception as e:
        print(f"  (hat tags skipped: {e})")
        return 0
