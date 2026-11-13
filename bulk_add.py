#!/usr/bin/env python3
"""
bulk_add.py -- add many products in one run, no saved vendor pages.

Reads a list of products and adds each one exactly like build_catalog.py does
(photos for every color, catalog.json entry, write-up, wholesale price), getting
everything from the vendor's own data instead of a saved page:

    S&S       the S&S API (account number + key from: python3 fetch_prices.py setup)
    SanMar    the SanMar SDL data download (SanMar_SDL_N.zip in Downloads)

Royal Apparel and AS Colour have no data feed, so they still need a saved page
and build_catalog.py, one at a time. Lines for them are listed and skipped.

USAGE:
    python3 bulk_add.py bulk_lists/checklist.csv --dry-run      # look first: what would be added, how big
    python3 bulk_add.py bulk_lists/checklist.csv --priority     # add the bold (priority) ones
    python3 bulk_add.py bulk_lists/checklist.csv --limit 10     # add the next 10 not yet in the catalog
    python3 bulk_add.py feature <product-id> [...]              # (re)pick featured photos
    python3 bulk_add.py feature --report                        # how many featured photos per color family
    python3 bulk_add.py tag-hats                                # (re)tag every hat: panels, closure, fabric ...

  Options: --priority   only rows marked priority
           --brand X    only rows for one brand (repeatable)
           --kind K     only rows of one kind, e.g. beanie or tote (repeatable)
           --skip STYLE leave one style out, e.g. a discontinued one (repeatable)
           --limit N    stop after N products
           --no-fetch   skip the paid manufacturer-site description lookup
           --no-commit  don't make a git commit per product (default: one commit
                        per product, "Add <brand> <style>", same as by hand)

THE LIST (CSV, one product per row):
    site,brand,style,name,kind,priority
    ss-api,Lane Seven,LS15001,Heavyweight Tee,tee,yes
    sanmar-sdl,District,DT6000,Very Important Tee,tee,

  site is ss-api or sanmar-sdl; kind is one of the catalog kinds (tee, longsleeve,
  hoodie, sweatshirt, tank, hat, beanie, tote). Products already in catalog.json are
  skipped, so the same list can be re-run any time to pick up where it left off.
  A product that fails doesn't stop the run; failures are listed at the end and in
  bulk_logs/.

FEATURED PHOTOS: each new product gets a featured photo (the card picture,
featured_front.jpg) picked automatically so the library stays varied: the
color family least used by the catalog's featured photos so far wins, preferring
rich mid-tone colors over white, black and very pale ones. Change any pick in
Product Admin as before; the next pick just counts it.

Photos still live in this repo (GitHub), about 5 MB per product. Add in batches
and push between them; a few hundred more products is fine, the whole S&S and
SanMar range is not (that would need the photos hosted somewhere else).
"""
import colorsys
import csv
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
CATALOG = HERE / "catalog.json"
LOGS = HERE / "bulk_logs"
API_SITES = ("ss-api", "sanmar-sdl")
KINDS = ("tee", "longsleeve", "hoodie", "sweatshirt", "tank", "hat", "cap", "beanie", "tote")
PAUSE = 2.0          # seconds between products: be gentle with the vendors' image servers
MB_PER_COLOR = 0.24  # front + back photo, measured on the current library


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")


def _norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def _brand_key(b):
    b = _norm(b)
    return "yupo" if b.startswith("ypclassic") else b[:4]


def already_have(r, products):
    """Same style from the same brand, even when the brand was spelled differently
    (YP Classics = Yupoong, Atlantis = Atlantis Headwear, Next Level Apparel ...)."""
    st, bk = _norm(r["style"]), _brand_key(r["brand"])
    return next((p for p in products if _norm(p.get("style")) == st and _brand_key(p.get("brand")) == bk), None)


def load_catalog():
    return json.loads(CATALOG.read_text())["products"]


# ------------------------------------------------------------------ featured photos
FAMILIES = ("red", "orange", "gold", "green", "teal", "blue", "navy", "purple", "pink",
            "brown", "grey", "black", "white")
BLAND = {"white", "black", "grey"}   # fine sometimes, but not the first choice


def family(hex_color):
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return "grey"
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    hue *= 360
    if light < 0.13: return "black"
    if light > 0.86 and sat < 0.5: return "white"
    if sat < 0.14: return "grey"
    if 15 <= hue < 50 and light < 0.42: return "brown"
    if 200 <= hue < 260 and light < 0.3: return "navy"
    if hue < 12 or hue >= 345: return "red" if light < 0.7 else "pink"
    if hue < 38: return "orange"
    if hue < 65: return "gold"
    if hue < 160: return "green"
    if hue < 200: return "teal"
    if hue < 260: return "blue"
    if hue < 300: return "purple"
    return "pink"


def appeal(hex_color):
    """Higher = nicer as a card picture: saturated, mid-light."""
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return 0
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    _, light, sat = colorsys.rgb_to_hls(r, g, b)
    return sat - abs(light - 0.5)


def featured_color(p):
    """Which of p's colors its featured_front.jpg is (by file contents), or None."""
    f = HERE / "catalog_images" / p["id"] / "featured_front.jpg"
    if not f.exists():
        return None
    data = f.read_bytes()
    for c in p["colors"]:
        fr = HERE / c.get("front", "")
        if fr.is_file() and fr.stat().st_size == len(data) and fr.read_bytes() == data:
            return c
    return None


def family_counts(products, skip_id=None):
    n = Counter()
    for p in products:
        if p["id"] == skip_id:
            continue
        c = featured_color(p)
        if c:
            n[family(c.get("hex"))] += 1
    return n


def pick_featured(product_id, products=None, quiet=False):
    products = products or load_catalog()
    p = next((x for x in products if x["id"] == product_id), None)
    if not p or not p["colors"]:
        return None
    used = family_counts(products, skip_id=product_id)
    usable = [c for c in p["colors"] if (HERE / c["front"]).is_file()]
    if not usable:
        return None
    # fewest featured photos in that family first; bland families count double; then the nicest color
    best = min(usable, key=lambda c: ((used[family(c.get("hex"))] + 1) * (2 if family(c.get("hex")) in BLAND else 1),
                                      -appeal(c.get("hex"))))
    src, dst = HERE / best["front"], HERE / "catalog_images" / product_id / "featured_front.jpg"
    if src.suffix.lower() == ".jpg":
        shutil.copyfile(src, dst)
    else:
        from PIL import Image
        im = Image.open(src).convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        bg.save(dst, quality=90)
    if not quiet:
        print(f"  featured: {best['name']} ({family(best.get('hex'))})")
    return best


def cmd_feature(args):
    products = load_catalog()
    if args == ["--report"] or not args:
        n = family_counts(products)
        none = sum(1 for p in products if not featured_color(p))
        print("Featured photos by color family:")
        for f in FAMILIES:
            print(f"  {f:7s} {n[f]:3d} {'#' * n[f]}")
        print(f"  (no featured photo, or not one of its colors: {none})")
        return
    for pid in args:
        print(pid)
        if not pick_featured(pid, products):
            print("  ! no such product, or it has no photos")


# ------------------------------------------------------------------ hat tags
from hat_tags import tag_hats   # shared with build_catalog.py


def cmd_tag_hats(args):
    n = tag_hats()
    print(f"{n} hat(s) changed. Commit catalog.json and push to update the site.")


# ------------------------------------------------------------------ the list
def read_list(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [{k.strip().lower(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]
    for r in rows:
        r["kind"] = re.sub(r"[^a-z]", "", r.get("kind", "").lower())
        r["priority"] = r.get("priority", "").lower() in ("yes", "y", "true", "1", "x")
        r["id"] = slugify(f"{r.get('brand', '')}-{r.get('style', '')}")
    return rows


def dry_run_item(r):
    import build_catalog as B
    colors = B.EXTRACTORS[r["site"]](r["brand"], r["style"])
    front_only_ok = r["kind"] in B.FRONT_ONLY_KINDS
    ok = [c for c in colors if c.get("front") and (c.get("back") or front_only_ok)]
    if not ok:
        raise RuntimeError(f"none of its {len(colors)} colors has both a front and a back photo in the vendor data"
                           " (needs a saved page)")
    return len(ok), len(colors) - len(ok)


def add_item(r, log, fetch, commit):
    cmd = [sys.executable, "build_catalog.py", "--site", r["site"], "-", r["brand"], r["style"], r["name"], r["kind"],
           "catalog.json"] + ([] if fetch else ["--no-fetch"])
    env = dict(os.environ, SKIP_FRESH_CHECK="1")   # checked once at the start of the run instead
    log.write(f"\n===== {r['brand']} {r['style']} ({r['site']}) =====\n$ {' '.join(cmd)}\n"); log.flush()
    res = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
    if res.returncode != 0:
        return f"build_catalog.py failed (exit {res.returncode}) -- see the log"
    products = load_catalog()
    p = next((x for x in products if x["id"] == r["id"]), None)
    if not p:
        return "not in catalog.json after the run -- see the log"
    best = pick_featured(r["id"], products, quiet=True)
    if r["kind"] in ("hat", "cap"):
        tag_hats(only_id=r["id"], quiet=True)
    log.write(f"featured: {best['name'] if best else '(none)'}\n")
    if commit:
        # all of catalog_images: a new two-tone or pattern color can add a swatch tile to OTHER products too
        paths = ["catalog.json", "product_descriptions.csv", "catalog_images"]
        subprocess.run(["git", "add", "--"] + paths, stdout=log, stderr=subprocess.STDOUT)
        c = subprocess.run(["git", "commit", "-q", "-m", f"Add {r['brand']} {r['style']}", "--"] + paths,
                           stdout=log, stderr=subprocess.STDOUT)
        if c.returncode != 0:
            return "added, but the git commit failed -- see the log"
    return None, len(p["colors"]), (best or {}).get("name")


def main():
    argv = sys.argv[1:]
    if argv[:1] == ["feature"]:
        return cmd_feature(argv[1:])
    if argv[:1] == ["tag-hats"]:
        return cmd_tag_hats(argv[1:])
    if not argv or argv[0].startswith("-"):
        sys.exit(__doc__)
    path, opts = argv[0], argv[1:]
    dry, pri, fetch, commit = "--dry-run" in opts, "--priority" in opts, "--no-fetch" not in opts, "--no-commit" not in opts
    limit = int(opts[opts.index("--limit") + 1]) if "--limit" in opts else None
    brands = {slugify(opts[i + 1]) for i, o in enumerate(opts) if o == "--brand" and i + 1 < len(opts)}
    skip = {_norm(opts[i + 1]) for i, o in enumerate(opts) if o == "--skip" and i + 1 < len(opts)}
    kinds = {re.sub(r"[^a-z]", "", opts[i + 1].lower()) for i, o in enumerate(opts) if o == "--kind" and i + 1 < len(opts)}

    rows = read_list(path)
    products = load_catalog()
    todo, manual, bad = [], [], []
    for r in rows:
        if pri and not r["priority"]: continue
        if brands and slugify(r["brand"]) not in brands: continue
        if kinds and r["kind"] not in kinds: continue
        if _norm(r["style"]) in skip: continue
        if already_have(r, products): continue
        if r.get("site") not in API_SITES: manual.append(r); continue
        if r["kind"] not in KINDS or not r.get("style") or not r.get("name"):
            bad.append((r, f"needs a style, a name and a kind ({'/'.join(KINDS)})")); continue
        todo.append(r)
    if limit is not None:
        todo = todo[:limit]

    print(f"{len(todo)} product(s) to {'check' if dry else 'add'}"
          + (f"; {len(manual)} need a saved page (Royal Apparel / AS Colour), skipped" if manual else "")
          + (f"; {len(bad)} row(s) with problems" if bad else ""))
    for r, why in bad:
        print(f"  ! {r.get('brand')} {r.get('style')}: {why}")
    if not todo:
        return

    if dry:
        total_mb, found, missing = 0.0, 0, []
        for i, r in enumerate(todo, 1):
            try:
                ok, nophoto = dry_run_item(r)
                mb = ok * MB_PER_COLOR; total_mb += mb; found += 1
                print(f"  [{i}/{len(todo)}] {r['brand']} {r['style']} -- {r['name']} ({r['kind']}): "
                      f"{ok} colors{f', {nophoto} without photos (skipped)' if nophoto else ''}, ~{mb:.0f} MB")
            except Exception as e:
                missing.append((r, str(e)))
                print(f"  [{i}/{len(todo)}] {r['brand']} {r['style']}: ! {e}")
        print(f"\n{found} found, {len(missing)} not found. Photos would add about {total_mb:.0f} MB to the repo.")
        return

    import build_descriptions as bd
    bd.ensure_clone_fresh(HERE)    # stop now if GitHub has commits this copy lacks
    LOGS.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    log_path = LOGS / f"bulk_add_{stamp}.log"
    added, failed = [], []
    with open(log_path, "w", encoding="utf-8") as log:
        for i, r in enumerate(todo, 1):
            print(f"  [{i}/{len(todo)}] {r['brand']} {r['style']} -- {r['name']} ... ", end="", flush=True)
            t = time.time()
            try:
                out = add_item(r, log, fetch, commit)
            except Exception as e:
                out = f"crashed: {e}"
            if isinstance(out, tuple):
                added.append(r)
                print(f"added {out[1]} colors, featured {out[2]} ({time.time() - t:.0f}s)")
            else:
                failed.append((r, out))
                print(f"FAILED: {out}")
            time.sleep(PAUSE)
    print(f"\nAdded {len(added)}, failed {len(failed)}. Full log: {log_path.relative_to(HERE)}")
    if failed:
        fail_csv = LOGS / f"failed_{stamp}.csv"
        with open(fail_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["site", "brand", "style", "name", "kind", "priority", "why"])
            for r, why in failed:
                w.writerow([r["site"], r["brand"], r["style"], r["name"], r["kind"], "yes" if r["priority"] else "", why])
        for r, why in failed:
            print(f"  - {r['brand']} {r['style']}: {why}")
        print(f"  (also in {fail_csv.relative_to(HERE)}; fix and re-run that file)")
    if added and commit:
        print("\nOne commit per product is ready: push with GitHub Desktop. The write-ups are in")
        print("product_descriptions.csv: import them in Product Admin -> Bulk tools as usual.")


if __name__ == "__main__":
    main()
