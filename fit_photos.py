#!/usr/bin/env python3
"""
fit_photos.py -- on-model ("fit") photos for the product detail page.

The catalog's own photos are flat product shots, which don't show how a garment fits.
Each product gets up to TWO colors' worth of on-model photos (front + back, a side shot
when there is no back), saved small next to its other photos and listed in catalog.json:

    "models": [{"color": "Black", "front": "catalog_images/<id>/model_black_front.jpg",
                "back": "catalog_images/<id>/model_black_back.jpg"}, ...]

The product detail page shows them in an "On a model" row under the main photos.
A product with no "models" looks exactly as before.

Where the photos come from (first one that has any wins):
    SanMar SDL   FRONT_MODEL_IMAGE_URL / BACK_MODEL_IMAGE_URL (the SDL download in Downloads)
    S&S API      colorOnModelFrontImage / BackImage / SideImage (fetch_prices.py setup account)
    AS Colour    the saved product page's generic MAIN / BACK / SIDE shots (one unnamed color)
Royal Apparel's catalog photos are already on a model, so it is skipped. Hats mostly have none.

Used by build_catalog.py (every new product) and `python3 bulk_add.py models` (backfill).
"""
import csv
import io
import json
import re
import time
import urllib.parse
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_W = 800           # model photos are smaller than the flat shots (the image folder is big already)
QUALITY = 80
MAX_COLORS = 2
SKIP_BRANDS = ("royalapparel",)   # catalog photos are already on a model


def _norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")


# ------------------------------------------------------------------ sources
# Each returns {color name: {"front": url, "back": url, "side": url}} (views it has), or {}.

_SDL = None


def _sdl_index():
    """SanMar SDL rows with model photos, read once: (STYLE#, mill[:4]) -> {color: views}."""
    global _SDL
    if _SDL is not None:
        return _SDL
    import fetch_prices as fp
    _SDL = {}
    path = fp.find_file("sanmar_sdl", ["~/Downloads/SanMar_SDL_N*.zip", "~/Downloads/SanMar_SDL_N*.csv",
                                       "~/Downloads/SanMar_SDL*.zip"])
    if not path:
        return _SDL
    if str(path).endswith(".zip"):
        z = zipfile.ZipFile(path)
        f = z.open(next(n for n in z.namelist() if n.lower().endswith(".csv")))
    else:
        f = open(path, "rb")
    with io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace") as t:
        for r in csv.DictReader(t):
            fr = (r.get("FRONT_MODEL_IMAGE_URL") or "").strip()
            if "model" not in fr.lower():   # hats/bags: this column holds a plain product shot instead
                continue
            key = ((r.get("STYLE#") or "").strip().upper(), fp.norm(r.get("MILL"))[:4])
            c = _SDL.setdefault(key, {}).setdefault((r.get("COLOR_NAME") or "").strip(), {})
            c.setdefault("front", fr)
            bk = (r.get("BACK_MODEL_IMAGE_URL") or "").strip()
            if "model" in bk.lower():
                c.setdefault("back", bk)
    return _SDL


def from_sanmar(p):
    import fetch_prices as fp
    idx = _sdl_index()
    want = (p.get("style") or "").strip().upper()
    mill = fp.norm(p.get("brand"))[:4]
    hits = idx.get((want, mill))
    if hits is None:   # brand spelled differently from SanMar's MILL: take the style if only one mill has it
        same = [v for (s, _), v in idx.items() if s == want]
        hits = same[0] if len(same) == 1 and _norm(p.get("brand"))[:4] in ("dist", "port", "spor") else {}
    return {k: v for k, v in hits.items() if k}


_SS = None


def _ss():
    global _SS
    if _SS is None:
        import fetch_prices as fp
        conf = fp.load_conf()
        _SS = fp.SS(conf["ss_account"], conf["ss_key"]) if conf.get("ss_account") and conf.get("ss_key") else False
    return _SS


SS_VIEWS = {"colorOnModelFrontImage": "front", "colorOnModelBackImage": "back", "colorOnModelSideImage": "side"}


def from_ss(p):
    import urllib.error
    import fetch_prices as fp
    ss = _ss()
    if not ss:
        return {}
    try:
        hits = ss.get(f"/styles/?search={urllib.parse.quote(p['style'])}") or []
    except urllib.error.HTTPError:
        return {}
    finally:
        time.sleep(fp.SS_DELAY)
    st = fp.pick_style(hits, p["brand"], p["style"])
    if not st:
        return {}
    skus = ss.get(f"/products/?styleid={st['styleID']}") or []
    time.sleep(fp.SS_DELAY)
    out = {}
    for s in skus:
        name = s.get("colorName")
        for field, view in SS_VIEWS.items():
            if name and s.get(field):
                # _fm is S&S's medium size; _fl is the 1000px one
                out.setdefault(name, {}).setdefault(view, "https://cdn.ssactivewear.com/"
                                                    + re.sub(r"_f[a-z]\.jpg$", "_fl.jpg", s[field]))
    return {k: v for k, v in out.items() if v.get("front")}


def from_ascolour_page(p, html=None):
    """AS Colour pages carry generic on-model shots (STYLE_NAME_MAIN / _BACK / _SIDE), one unnamed color."""
    if html is None:
        for f in (HERE / f"AS_Colour_{p['style']}.html", HERE / "saved_pages" / f"AS_Colour_{p['style']}.html"):
            if f.exists():
                html = f.read_text(encoding="utf-8", errors="ignore")
                break
    if not html:
        return {}
    m = re.search(r'"product-schema"[^>]*>\s*(\{.*?\})\s*</script>', html, re.S)
    if not m:
        return {}
    views = {}
    for url in json.loads(m.group(1)).get("image", []):
        fname = url.rsplit("/", 1)[-1]
        m2 = re.match(r"(\d+)_(.+?)__\d+.*\.jpg", fname, re.I)
        if not m2 or m2.group(1) != str(p["style"]).strip():
            continue
        tail = m2.group(2).upper().rsplit("_", 1)[-1]
        view = {"MAIN": "front", "BACK": "back", "SIDE": "side"}.get(tail)
        # the generic BACK is the one with the product name only (a color back has the color before _BACK)
        if view and view not in views:
            views[view] = url
    return {"": views} if views.get("front") else {}


def find_models(p, html=None):
    """All on-model photos the vendors have for product p: ({color: views}, source name)."""
    if any(_norm(p.get("brand")).startswith(b) for b in SKIP_BRANDS):
        return {}, None
    if _norm(p.get("brand")).startswith("ascolour"):
        got = from_ascolour_page(p, html)
        return (got, "AS Colour page") if got else ({}, None)
    got = from_sanmar(p)
    if got:
        return got, "SanMar"
    got = from_ss(p)
    return (got, "S&S") if got else ({}, None)


# ------------------------------------------------------------------ choosing
NEUTRAL_ORDER = ("black", "white", "heather", "grey", "gray", "marle", "ash", "charcoal", "natural")


def _neutral_rank(name):
    n = (name or "").lower()
    if "/" in n:
        return len(NEUTRAL_ORDER) + 1
    if re.search(r"\bjet black\b|^black$", n):
        return 0
    for i, w in enumerate(NEUTRAL_ORDER):
        if re.search(rf"\b{w}\b", n):
            return i
    return len(NEUTRAL_ORDER)


def choose(models, p):
    """Up to MAX_COLORS colors: the best neutral (black, white, heather) plus one non-neutral
    color the shop carries, both preferring colors that are on our product and have a back shot."""
    ours = {_norm(c["name"]): c for c in p.get("colors", [])}
    if list(models) == [""]:
        return [("", models[""])]

    def base(name, v):
        return (0 if _norm(name) in ours else 1, 0 if v.get("back") else 1)

    items = sorted(models.items(), key=lambda kv: base(*kv) + (_neutral_rank(kv[0]),))
    if not items:
        return []
    first = items[0]
    picks = [first]
    rest = [kv for kv in items[1:] if _neutral_rank(kv[0]) >= len(NEUTRAL_ORDER)]
    if not rest:
        rest = [kv for kv in items[1:] if _neutral_rank(kv[0]) != _neutral_rank(first[0])]
    if rest:
        try:
            from bulk_add import appeal
        except Exception:
            appeal = None

        def nice(kv):
            c = ours.get(_norm(kv[0]))
            return -(appeal(c.get("hex"), c.get("name")) if appeal and c else 0)
        picks.append(min(rest, key=lambda kv: base(*kv) + (nice(kv),)))
    return picks[:MAX_COLORS]


# ------------------------------------------------------------------ saving
def _download(url):
    import build_color_template as bct
    try:
        r = bct.SESSION.get(url, timeout=30)
    except Exception:
        return None
    if r.status_code != 200 or len(r.content) < 2000:
        return None
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(r.content))
        im.load()
    except Exception:
        return None
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        im = bg
    im = im.convert("RGB")
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    return im


def save_models(p, picks):
    """Download + shrink the picked photos into catalog_images/<id>/; returns (models list, bytes written)."""
    out, total = [], 0
    folder = HERE / "catalog_images" / p["id"]
    folder.mkdir(parents=True, exist_ok=True)
    ours = {_norm(c["name"]): c["name"] for c in p.get("colors", [])}
    for name, views in picks:
        color = ours.get(_norm(name), name)
        prefix = f"model_{slugify(color)}_" if slugify(color) else "model_"
        entry = {"color": color} if color else {}
        wanted = ["front", "back"] if views.get("back") else ["front", "side"]
        for view in wanted:
            if not views.get(view):
                continue
            im = _download(views[view])
            if im is None:
                continue
            dst = folder / f"{prefix}{view}.jpg"
            im.save(dst, quality=QUALITY, optimize=True, progressive=True)
            total += dst.stat().st_size
            entry[view] = f"catalog_images/{p['id']}/{dst.name}"
        if entry.get("front"):
            out.append(entry)
    return out, total


def has_models(p):
    return bool(p.get("models")) and all((HERE / m["front"]).exists() for m in p["models"])


def add_models(catalog_path, product_id, html=None, force=False, quiet=False, found=None):
    """Find, save and record model photos for one product. Never raises; returns (n colors, bytes)."""
    catalog_path = Path(catalog_path)
    try:
        catalog = json.loads(catalog_path.read_text())
        p = next((x for x in catalog["products"] if x.get("id") == product_id), None)
        if not p or (has_models(p) and not force):
            return 0, 0
        models, src = found if found is not None else find_models(p, html)
        picks = choose(models, p)
        if not picks:
            if not quiet:
                print("\n  No on-model photos at the vendor for this product (fine: the page shows the flat photos).")
            return 0, 0
        saved, size = save_models(p, picks)
        if not saved:
            return 0, 0
        catalog = json.loads(catalog_path.read_text())   # re-read: nothing else should have changed it, but be safe
        p = next(x for x in catalog["products"] if x.get("id") == product_id)
        p["models"] = saved
        catalog_path.write_text(json.dumps(catalog, indent=2))
        if not quiet:
            print(f"\n  On-model photos ({src}): " + ", ".join(m.get("color") or "model" for m in saved)
                  + f" ({size / 1e6:.1f} MB)")
        return len(saved), size
    except Exception as e:
        if not quiet:
            print(f"\n  ! On-model photos skipped: {e}")
        return 0, 0
