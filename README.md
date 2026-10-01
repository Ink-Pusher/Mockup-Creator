# Mockup-Creator — what's what

The repo root stays small on purpose. Quick map:

## Files you touch when adding a product

| What | Where |
|---|---|
| Saved vendor pages (`Brand_Style.html`) | drop them in **`saved_pages/`** (the main folder also still works) |
| `catalog.json`, `product_descriptions.csv`, `catalog_images/` | updated **automatically** by the script — never edit by hand unless you know why |

Delete old saved pages whenever you like — they're disposable (though keeping
them lets a missing photo be re-pulled without re-saving the page).

## System files — do not delete or move (protected)

- `build_catalog.py`, `build_descriptions.py`, `build_color_template.py` — the scripts
- `setup.ps1`, `setup.sh`, `SETUP.md` — the new-machine installer; its one-line
  commands download these from this repo **at these exact paths, forever**
- `supabase_landing_setup.sql` — one-time database setup, kept for repair/re-runs
- `squarespace/` — the live site's pages (source of truth; paste into Squarespace)
- `.githooks/` — blocks accidental committed deletion of all of the above

A commit that deletes any protected file gets stopped with a warning.
`doctor` (in build_descriptions.py) checks a machine's whole setup — start there.
