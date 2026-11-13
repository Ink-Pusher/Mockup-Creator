#!/usr/bin/env python3
"""
model_photos.py -- the photo library Product Admin picks hero and band photos from.

For every catalog product S&S carries, lists S&S's on-model photos (front, side, back, per color)
and, for hats and totes, the three-quarter "direct side" product shots. Writes model_photos.json
(links only, no image files), which Product Admin reads from GitHub. When a photo is picked in
Product Admin it is copied into our own storage, so the live page never depends on S&S's links.

USAGE:
    python3 model_photos.py                 # rebuild the whole library (about 10 minutes)
    python3 model_photos.py <product-id>... # refresh just these products

Needs the S&S account set up for fetch_prices.py (python3 fetch_prices.py setup).
Commit model_photos.json and push to update what Product Admin offers.
"""
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import fetch_prices as fp

HERE = Path(__file__).resolve().parent
OUT = HERE / "model_photos.json"
CDN = "https://cdn.ssactivewear.com/"
VIEWS = {"colorOnModelFrontImage": "model_front", "colorOnModelSideImage": "model_side",
         "colorOnModelBackImage": "model_back", "colorDirectSideImage": "side"}


def big(path):
    return CDN + re.sub(r"_fm\.jpg$", "_fl.jpg", path)


def photos_for(ss, p):
    hits = ss.get(f"/styles/?search={urllib.parse.quote(p['style'])}") or []
    time.sleep(fp.SS_DELAY)
    st = fp.pick_style(hits, p["brand"], p["style"])
    if not st:
        return None
    skus = ss.get(f"/products/?styleid={st['styleID']}") or []
    time.sleep(fp.SS_DELAY)
    out = {}
    for s in skus:
        color = s.get("colorName")
        if not color:
            continue
        for field, view in VIEWS.items():
            if view == "side" and p["kind"] not in ("hat", "cap", "beanie", "tote"):
                continue   # garments: the model shots are what's wanted
            if s.get(field):
                out.setdefault(view, {}).setdefault(color, big(s[field]))
    return out or None


def main():
    conf = fp.load_conf()
    if not (conf.get("ss_account") and conf.get("ss_key")):
        sys.exit("No S&S API account on this computer. Run: python3 fetch_prices.py setup")
    ss = fp.SS(conf["ss_account"], conf["ss_key"])
    products = json.loads((HERE / "catalog.json").read_text())["products"]
    only = set(sys.argv[1:])
    lib = json.loads(OUT.read_text()) if OUT.exists() and only else {}
    todo = [p for p in products if not only or p["id"] in only]
    for i, p in enumerate(todo, 1):
        try:
            got = photos_for(ss, p)
        except Exception as e:   # one bad lookup shouldn't stop the run
            print(f"  [{i}/{len(todo)}] {p['id']}: skipped ({e})")
            continue
        if got:
            lib[p["id"]] = got
            print(f"  [{i}/{len(todo)}] {p['id']}: " + ", ".join(f"{len(v)} {k}" for k, v in got.items()))
        else:
            lib.pop(p["id"], None)
    OUT.write_text(json.dumps(lib, indent=1, sort_keys=True))
    print(f"\n{len(lib)} products with photos. Wrote {OUT.name}; commit and push it.")


if __name__ == "__main__":
    main()
