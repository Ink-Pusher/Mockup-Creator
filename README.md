# Mockup-Creator -- what's what

The repo root stays small on purpose. Quick map:

## Files you touch when adding a product

| What | Where |
|---|---|
| Saved vendor pages (`Brand_Style.html`) | drop them in **`saved_pages/`** (the main folder also still works) |
| `catalog.json`, `product_descriptions.csv`, `catalog_images/` | updated **automatically** by the script -- never edit by hand unless you know why |

Delete old saved pages whenever you like -- they're disposable (though keeping
them lets a missing photo be re-pulled without re-saving the page).

## System files -- do not delete or move (protected)

- `build_catalog.py`, `build_descriptions.py`, `build_color_template.py`, `fetch_prices.py` -- the scripts
- `setup.ps1`, `setup.sh`, `SETUP.md` -- the new-machine installer; its one-line
  commands download these from this repo **at these exact paths, forever**
- `supabase_landing_setup.sql` -- one-time database setup, kept for repair/re-runs
- `squarespace/` -- the live site's pages (source of truth; paste into Squarespace)
- `.githooks/` -- blocks accidental committed deletion of all of the above

A commit that deletes any protected file gets stopped with a warning.
`doctor` (in build_descriptions.py) checks a machine's whole setup -- start there.

## Prices (Product Admin and the price estimator)

Adding a product with `build_catalog.py` now also looks up its wholesale blank price and saves it to
Product Admin, where each card shows **Vendor $**, **Override $** and the **garment price** the price
estimator uses (vendor price rounded up to $0.05, + $1, or + $2 for hoodies and sweatshirts).
Only print admins can see or change prices; staff sign-ins don't see them.

- One-time setup per computer: `python3 fetch_prices.py setup` (S&S account number + API key, where the
  SanMar SDL download and the AS Colour price list are, and your Product Admin sign-in). Stored in
  `~/.inkpusher/`, never in this repo. The password is never saved.
- Refresh every price: `python3 fetch_prices.py --all` (add `--dry-run` to look first).
  New SanMar or AS Colour price files: download them to Downloads (or point `setup` at them) and re-run.
- Sources: S&S API original piece price, SanMar SDL case price, AS Colour Gold price list. A style both
  S&S and SanMar sell gets the higher price. Royal Apparel: type it on the card.
- A price typed on a card is kept by later refreshes (unless `--force`); overrides are never touched.
- Skip it for one add: `--no-prices`.
