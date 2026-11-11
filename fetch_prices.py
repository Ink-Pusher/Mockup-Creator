#!/usr/bin/env python3
"""
fetch_prices.py -- look up each catalog product's WHOLESALE blank price and save it to Product Admin.

build_catalog.py runs this automatically after adding a product (pass --no-prices to skip), and it
can be run on its own to refresh prices:

    python3 fetch_prices.py setup                    # one time per computer (see below)
    python3 fetch_prices.py bella-canvas-3001cvc     # one or more catalog product ids
    python3 fetch_prices.py --all                    # every product in catalog.json
    python3 fetch_prices.py --all --dry-run          # show what it would save, save nothing

WHERE PRICES COME FROM (Timm's rules, 2026-11-10):
  * the ORIGINAL wholesale price, never special-program or sale pricing, and the COLOR price (not white):
      - S&S Activewear: the API's piecePrice (piece = dozen = case at S&S; customerPrice is the special
        program price and is never used)
      - SanMar: the SDL data download's CASE_PRICE (that's the price SanMar's site shows; PIECE_PRICE is
        SanMar's own +$1 broken-case price)
      - AS Colour: the Gold price list PDF (one price for every color)
      - Royal Apparel: the regular price on royalapparel.net's product page (low end of the range = S-XL)
      - anything else: enter by hand in Product Admin
  * most common price among non-white colors in sizes S-XL (all sizes for totes, bags, kids)
  * a style both S&S and SanMar sell gets the HIGHER of the two (either vendor may be the one in stock)
Product Admin then shows the garment price: vendor price rounded UP to $0.05, + $1 (+ $2 for fleece).
A price someone typed in Product Admin (source "manual") is never overwritten unless you pass --force,
and Product Admin's override price is never touched.

SETUP (one time, per computer) -- `python3 fetch_prices.py setup` asks for:
  * S&S account number + API key (hidden as you type)   -> skip if you don't have them
  * where the SanMar SDL download and the AS Colour price list PDF are (defaults: ~/Downloads)
  * your Product Admin sign-in (must be a print admin), so it can save prices. The password is used once
    and never stored; only a sign-in token is kept.
  Everything is saved in ~/.inkpusher/ (readable only by you), never in this repo.
"""
import argparse, base64, collections, csv, getpass, glob, io, json, math, os, re, stat, sys, time, zipfile
import urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF_DIR = Path.home() / ".inkpusher"
CONF = CONF_DIR / "prices.json"

# ---- shop config ---------------------------------------------------------------------------
SUPABASE_URL = "https://wkmwqqtwijimkqfijjrc.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_1ik4UyMIim4n-3FbWCzRRA_kHCy0N5G"
SS_API = "https://api.ssactivewear.com/v2"
SS_DELAY = 1.1                                  # S&S allows about 60 requests a minute
ROUND_STEP, MARKUP, FLEECE_MARKUP = 0.05, 1.00, 2.00
FLEECE_KINDS = {"hoodie", "sweatshirt"}
BASE_SIZES = {"S", "M", "L", "XL", "SM", "MD", "LG", "XS"}
AS_COLOUR = {"ascolour"}
ROYAL = {"royalapparel"}                        # read from royalapparel.net's public product page
HAND_ENTERED = set()                            # brands with no price feed (enter in Product Admin)
# ---------------------------------------------------------------------------------------------

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("+", " ").replace("&", " "))

def blank_cost(vendor_price, kind):
    """Same formula as Product Admin and the price estimator (apparel/pricing.js)."""
    cents = math.ceil(vendor_price * 100 - 1e-6)
    step = round(ROUND_STEP * 100)
    rounded = math.ceil(cents / step) * step / 100
    return round(rounded + (FLEECE_MARKUP if kind in FLEECE_KINDS else MARKUP), 2)

def mode_price(prices):
    return collections.Counter(prices).most_common(1)[0][0] if prices else None

# ---------------------------------------------------------------------------------- config
def load_conf():
    try: return json.loads(CONF.read_text())
    except Exception: return {}

def save_conf(c):
    CONF_DIR.mkdir(mode=0o700, exist_ok=True)
    CONF.write_text(json.dumps(c, indent=1))
    os.chmod(CONF, stat.S_IRUSR | stat.S_IWUSR)

def find_file(conf_key, patterns):
    c = load_conf()
    if c.get(conf_key) and Path(c[conf_key]).expanduser().exists(): return Path(c[conf_key]).expanduser()
    for pat in patterns:
        hits = sorted(glob.glob(os.path.expanduser(pat)), key=os.path.getmtime, reverse=True)
        if hits: return Path(hits[0])
    return None

# ---------------------------------------------------------------------------------- S&S
class SS:
    def __init__(self, account, key):
        self.auth = base64.b64encode(f"{account}:{key}".encode()).decode()
    def get(self, path, tries=3):
        req = urllib.request.Request(SS_API + path, headers={"Authorization": f"Basic {self.auth}", "Accept": "application/json",
                                                             "User-Agent": "InkPusherPriceSync/1.0"})
        for n in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=45) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError:
                raise
            except (urllib.error.URLError, TimeoutError, OSError):
                if n == tries - 1: raise
                time.sleep(5 * (n + 1))   # S&S is sometimes slow: wait, then ask again
    def price(self, p):
        """(price, note) or (None, reason). Never raises for a slow or unreachable S&S."""
        try:
            return self._price(p)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            return None, "S&S didn't answer (try again later)"
    def _price(self, p):
        try:
            hits = self.get(f"/styles/?search={urllib.parse.quote(p['style'])}"); time.sleep(SS_DELAY)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403): raise SystemExit("S&S refused the account number / API key. Run: python3 fetch_prices.py setup")
            return None, "not found at S&S" if e.code == 404 else f"S&S error {e.code}"
        b = norm(p["brand"])
        same = [h for h in hits if norm(h.get("styleName")) == norm(p["style"])]
        st = next((h for h in same if norm(h.get("brandName"))[:6] and (norm(h.get("brandName")).startswith(b[:6]) or b.startswith(norm(h.get("brandName"))[:6]))), None)
        st = st or (same[0] if len(same) == 1 else None)
        if not st: return None, "not found at S&S"
        skus = self.get(f"/products/?styleid={st['styleID']}"); time.sleep(SS_DELAY)
        sized = any((s.get("sizeName") or "").upper() in BASE_SIZES for s in skus)
        colored, white = [], []
        for s in skus:
            if sized and (s.get("sizeName") or "").upper() not in BASE_SIZES: continue
            v = s.get("piecePrice")
            if not isinstance(v, (int, float)) or v <= 0: continue
            (white if re.search(r"\bwhite\b", s.get("colorName") or "", re.I) else colored).append(round(float(v), 2))
        v = mode_price(colored)
        return (v, f"S&S ${v:.2f}") if v else (None, "no colored prices at S&S")

# ---------------------------------------------------------------------------------- SanMar SDL
class SanMar:
    """SanMar's SDL data download (SanMar_SDL_N.zip or .csv). Read once per run, only the styles asked for."""
    def __init__(self, path):
        self.path = path; self.rows = None
    def _load(self, wanted_styles):
        self.rows = collections.defaultdict(list)
        if str(self.path).endswith(".zip"):
            z = zipfile.ZipFile(self.path); f = z.open(next(n for n in z.namelist() if n.lower().endswith(".csv")))
        else:
            f = open(self.path, "rb")
        with io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace") as t:
            for r in csv.DictReader(t):
                st = (r.get("STYLE#") or "").strip().upper()
                if any(st == w or (st.endswith(w) and len(st) - len(w) <= 3) for w in wanted_styles):
                    self.rows[st].append(r)
    def price(self, p, wanted_styles):
        if self.rows is None: self._load(wanted_styles)
        s, b = norm(p["style"]).upper(), norm(p["brand"])[:4]
        cands = [k for k, rs in self.rows.items() if (k == s or (k.endswith(s) and len(k) - len(s) <= 3)) and norm(rs[0]["MILL"])[:4] == b]
        if not cands: return None, "not in the SanMar file"
        rs = self.rows[min(cands, key=len)]
        core = [r for r in rs if r["SIZE"].strip().upper() in BASE_SIZES | {"OSFA"}] or rs
        col = [r for r in core if not re.search(r"white", r["COLOR_NAME"], re.I)] or core
        v = mode_price([round(float(r["CASE_PRICE"]), 2) for r in col if r.get("CASE_PRICE")])
        disc = " (SanMar: discontinued)" if rs[0].get("PRODUCT_STATUS") == "Discontinued" else ""
        return (v, f"SanMar ${v:.2f}{disc}") if v else (None, "no SanMar price")

# ---------------------------------------------------------------------------------- AS Colour PDF
class ASColour:
    def __init__(self, path):
        self.prices = {}
        import fitz   # pymupdf (already a build_catalog.py dependency)
        for page in fitz.open(path):
            lines = collections.defaultdict(list)
            for w in page.get_text("words"):
                lines[round(w[1] / 3)].append((w[0], w[4]))
            for _, ws in sorted(lines.items()):
                text = "  ".join(t for _, t in sorted(ws))
                m = re.match(r"\s*(\d{4}[A-Z]?)\s+(.+?)\s+.*\$(\d+\.\d\d)\s*$", text)
                if m and not re.search(r"\((\dXL|XS)\)", m.group(2)) and m.group(1) not in self.prices:
                    self.prices[m.group(1)] = float(m.group(3))
        self.name = Path(path).stem
    def price(self, p):
        v = self.prices.get(p["style"].upper())
        return (v, f"AS Colour price list ({self.name}) ${v:.2f}") if v else (None, "not on the AS Colour price list")

# ---------------------------------------------------------------------------------- Royal Apparel
class Royal:
    """royalapparel.net product pages carry the style's regular price range publicly ("regLowPrice" /
    "regHighPrice"): the low end is the base price (S-XL), the high end the biggest sizes. Sale prices
    are a separate field and never used. One page at a time, with a pause."""
    def price(self, p):
        url = f"https://www.royalapparel.net/product/{urllib.parse.quote(p['style'])}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "InkPusherPriceSync/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r: html = r.read().decode("utf-8", "replace")
        except Exception as e:
            return None, f"Royal Apparel page didn't load ({e})"
        finally:
            time.sleep(SS_DELAY)
        lo = re.search(r'"regLowPrice"\s*:\s*([\d.]+)', html) or re.search(r'"regPrice"\s*:\s*([\d.]+)', html)
        hi = re.search(r'"regHighPrice"\s*:\s*([\d.]+)', html)
        if not lo or float(lo.group(1)) <= 0: return None, "no price on the Royal Apparel page"
        v = round(float(lo.group(1)), 2)
        return v, f"Royal Apparel ${v:.2f}" + (f" (range up to ${float(hi.group(1)):.2f} for big sizes)" if hi and float(hi.group(1)) > v else "")

# ---------------------------------------------------------------------------------- Supabase
def _post(path, body, token=None, prefer=None):
    h = {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json", "Authorization": f"Bearer {token or SUPABASE_ANON_KEY}"}
    if prefer: h["Prefer"] = prefer
    req = urllib.request.Request(SUPABASE_URL + path, data=json.dumps(body).encode(), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        t = r.read().decode() or "null"
        return json.loads(t)

def _get(path, token):
    req = urllib.request.Request(SUPABASE_URL + path, headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def sign_in():
    """A fresh access token from the saved sign-in (refresh tokens rotate, so the new one is saved)."""
    c = load_conf()
    if not c.get("refresh_token"): return None, None
    try:
        s = _post("/auth/v1/token?grant_type=refresh_token", {"refresh_token": c["refresh_token"]})
    except urllib.error.HTTPError:
        return None, None
    c["refresh_token"] = s["refresh_token"]; save_conf(c)
    return s["access_token"], (s.get("user") or {}).get("email")

# ---------------------------------------------------------------------------------- the work
def load_catalog():
    return json.loads((HERE / "catalog.json").read_text())["products"]

def lookup(products, quiet=False):
    """Returns {product_id: (vendor_price, note)} for every product it could price, plus a list of misses."""
    c = load_conf()
    ss = SS(c["ss_account"], c["ss_key"]) if c.get("ss_account") and c.get("ss_key") else None
    sm_path = find_file("sanmar_sdl", ["~/Downloads/SanMar_SDL_N*.zip", "~/Downloads/SanMar_SDL_N*.csv", "~/Downloads/SanMar_SDL*.zip"])
    asc_path = find_file("ascolour_pdf", ["~/Downloads/gold*.pdf", "~/Downloads/*AS*Colour*rice*.pdf"])
    sm = SanMar(sm_path) if sm_path else None
    try: asc = ASColour(asc_path) if asc_path else None
    except Exception as e: asc = None; print(f"  ! couldn't read the AS Colour price list ({e})")
    if not quiet:
        print(f"Sources: S&S API {'on' if ss else 'OFF (run setup)'} | SanMar file {sm_path.name if sm_path else 'not found'} | AS Colour list {asc_path.name if asc_path else 'not found'}")
    wanted = {norm(p["style"]).upper() for p in products}
    found, misses = {}, []
    for p in products:
        b = norm(p["brand"])
        if b in HAND_ENTERED: misses.append((p, "enter by hand in Product Admin (no price feed)")); continue
        if b in ROYAL:
            v, note = Royal().price(p)
        elif b in AS_COLOUR:
            v, note = asc.price(p) if asc else (None, "AS Colour price list not found")
        else:
            got = []
            reasons = []
            for src, fn in (("S&S", (lambda: ss.price(p)) if ss else None), ("SanMar", (lambda: sm.price(p, wanted)) if sm else None)):
                if not fn: continue
                pv, pn = fn()
                (got if pv else reasons).append((pv, pn) if pv else pn)
            if got:
                v = max(x[0] for x in got)
                note = " / ".join(x[1] for x in got) + (" (higher used)" if len({x[0] for x in got}) > 1 else "")
            else:
                v, note = None, "; ".join(reasons) or "no price sources set up"
        if v: found[p["id"]] = (v, note)
        else: misses.append((p, note))
        if not quiet: print(f"  {p['brand']} {p['style']}: " + (f"${v:.2f} -> garment ${blank_cost(v, p['kind']):.2f}  ({note})" if v else note))
    return found, misses

def save(products, found, force=False):
    token, email = sign_in()
    if not token:
        print("\nNot signed in to Product Admin, so nothing was saved. Run: python3 fetch_prices.py setup"); return False
    by = {p["id"]: p for p in products}
    ids = ",".join(urllib.parse.quote(i) for i in found)
    existing = {r["product_id"]: r for r in _get(f"/rest/v1/apparel_blank_costs?select=product_id,source,vendor_price&product_id=in.({ids})", token)} if found else {}
    now = datetime.now(timezone.utc).isoformat()
    rows, kept = [], []
    for pid, (v, note) in found.items():
        if not force and (existing.get(pid) or {}).get("source") == "manual": kept.append(pid); continue
        rows.append({"product_id": pid, "vendor_price": round(v, 2), "blank_cost": blank_cost(v, by[pid]["kind"]), "price_note": note[:300],
                     "source": "import", "checked_at": now, "updated_at": now, "updated_by": f"{email} (fetch_prices.py)"})
    if rows:
        try:
            _post("/rest/v1/apparel_blank_costs?on_conflict=product_id", rows, token, prefer="resolution=merge-duplicates,return=minimal")
        except urllib.error.HTTPError as e:
            print(f"\n! Couldn't save prices ({e.code}): {e.read().decode()[:300]}")
            print("  Your sign-in must be a print admin. Run: python3 fetch_prices.py setup"); return False
    print(f"\nSaved {len(rows)} price(s) to Product Admin" + (f"; kept {len(kept)} typed in by hand (--force replaces them)" if kept else "") + ".")
    return True

def update_prices(product_ids, force=False):
    """Called by build_catalog.py after it adds a product. Never fatal."""
    try:
        products = [p for p in load_catalog() if p["id"] in set(product_ids)]
        if not products: return
        print("\n--- price (fetch_prices.py) ---")
        found, misses = lookup(products)
        if found: save(products, found, force)
        for p, why in misses: print(f"  No price for {p['brand']} {p['style']}: {why}. Enter it on the product's card in Product Admin.")
    except SystemExit as e:
        print(f"  ! {e}")
    except Exception as e:
        print(f"  ! Price lookup failed ({e}). The photos and catalog entry are fine; retry: python3 fetch_prices.py {' '.join(product_ids)}")

def cmd_setup():
    c = load_conf()
    print("Price setup. Press Return to keep what's already saved.\n")
    a = input(f"S&S account number{' [saved]' if c.get('ss_account') else ''} (Return to skip): ").strip()
    if a:
        c["ss_account"] = a
        c["ss_key"] = getpass.getpass("S&S API key (hidden): ").strip()
    for key, label, default in (("sanmar_sdl", "SanMar SDL download (.zip or .csv)", "~/Downloads/SanMar_SDL_N.zip"),
                                ("ascolour_pdf", "AS Colour price list PDF", "~/Downloads/gold.pdf")):
        v = input(f"{label} [{c.get(key) or default}]: ").strip()
        if v: c[key] = os.path.expanduser(v.strip("'\""))
    save_conf(c)
    email = input("\nProduct Admin sign-in email (Return to skip): ").strip()
    if email:
        pw = getpass.getpass("Password (hidden, not saved): ")
        try:
            s = _post("/auth/v1/token?grant_type=password", {"email": email, "password": pw})
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Sign-in failed ({e.code}). Check the email and password.")
        is_admin = _post("/rest/v1/rpc/is_print_admin", {}, s["access_token"])
        if not is_admin:
            raise SystemExit(f"{email} isn't on the print admin list, so it can't save prices. Ask Timm to add it.")
        c["refresh_token"] = s["refresh_token"]; save_conf(c)
        print(f"Signed in as {email}.")
    print(f"\nSaved to {CONF} (only you can read it).")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="catalog product ids, or 'setup'")
    ap.add_argument("--all", action="store_true", help="every product in catalog.json")
    ap.add_argument("--dry-run", action="store_true", help="look up prices but don't save them")
    ap.add_argument("--force", action="store_true", help="also replace prices typed in by hand in Product Admin")
    a = ap.parse_args()
    if a.ids == ["setup"]: return cmd_setup()
    cat = load_catalog()
    products = cat if a.all else [p for p in cat if p["id"] in set(a.ids)]
    unknown = set(a.ids) - {p["id"] for p in cat}
    if unknown: print("Not in catalog.json:", ", ".join(sorted(unknown)))
    if not products: ap.error("give product ids, or --all")
    found, misses = lookup(products)
    if misses:
        print(f"\n{len(misses)} without a price:")
        for p, why in misses: print(f"  {p['brand']} {p['style']} ({p['id']}): {why}")
    if a.dry_run: print("\n--dry-run: nothing saved."); return
    if found: save(products, found, a.force)

if __name__ == "__main__":
    main()
