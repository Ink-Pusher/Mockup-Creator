# Squarespace page sources

These are the real, current contents of the Code Blocks on the live Squarespace
site. They are here so a bad paste has something to roll back to, and so two
people aren't each editing a private copy in their own Downloads folder.

**The repo is now the source of truth. Edit here, then paste into Squarespace.**
Any copy still sitting in `~/Downloads` is stale — delete it rather than editing it.

| File | Where it's pasted |
|---|---|
| `admin.html` | Product Admin page (the private, `noindex` one) |
| `apparel_catalog.html` | Apparel Catalog listing page |
| `product_detail.html` | Product detail page (`/product-detail?id=…`) |
| `mockup_generator_v2_3.html` | Mockup Studio page |
| `ink-pusher-nav.html` | Nav Code Block at the top of the landing page |

## Editing these

Nothing here is built or bundled — each file is pasted whole into its Code Block,
so what's in the file is exactly what runs.

Two things about the Squarespace environment have caused real bugs, and both are
easy to reintroduce:

1. **The site nav (`#ip-wrap`) is `position:relative; z-index:9999`.** Anything
   meant to sit above the page (a modal, a dropdown) has to be re-homed onto
   `<body>` when it opens, or it stays trapped in whatever stacking context
   Squarespace wraps the Code Block in and paints underneath the nav.
2. **Squarespace overrides `display` on `<label>`.** A `display:flex` row built
   from a `<label>` will not be a flex container, so keep its children
   inline-level rather than relying on flex to hold them on one line.

## Shared design tokens

`admin.html`, `apparel_catalog.html`, `product_detail.html` and
`mockup_generator_v2_3.html` deliberately share one palette and the same
"sticker" card treatment (2px outline, hard offset shadow). If the palette
changes, change it in all four — they are meant to read as one product.
