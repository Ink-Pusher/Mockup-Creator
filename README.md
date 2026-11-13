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

## Adding many products at once (S&S and SanMar)

`python3 bulk_add.py bulk_lists/checklist.csv --dry-run` shows what would be added and how big the
photos are; drop `--dry-run` to add them (`--priority` for the bold ones, `--limit N` for a batch).
No saved pages: photos, write-up and price come from the S&S API and the SanMar SDL file, and each
product gets an automatically picked featured photo that keeps the library's colors varied
(`python3 bulk_add.py feature --report`). One commit per product; push between batches.
Royal Apparel and AS Colour still need a saved page and `build_catalog.py`.
`bulk_lists/checklist.csv` was made from the Apparel Catalog Checklist doc; add rows to grow it.

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

## Featured catalog page (heroes, popular, category bands)

The catalog page opens on a **Featured** view: up to 5 rotating heroes, Recently viewed, Most popular,
a band per category, an instant-quote band and Shop by brand. **All products** (or any category,
filter or brand) switches to the full grid. Everything is edited in Product Admin:

- **Products tab**: the **Popular** checkbox on each card (badge + Most popular row).
- **Featured Page tab**: heroes (photos, text, button, start/end dates, on/off), category band photos,
  and the products shown under each band (the old landing rows).

Photos are chosen from `model_photos.json`, a list of S&S's on-model and side-view photos for products
we carry. Refresh it after adding products: `python3 model_photos.py` (about 10 minutes), then commit
and push `model_photos.json`. A picked photo is copied into our own Supabase storage. The built-in
fallback photos live in `featured_defaults/`.
