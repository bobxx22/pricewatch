# Dashboard design rules

The dashboard borrows from a shop shelf: prices are the loudest thing on the page, and yellow
means one thing, a discount, the way promo price tags do in Ukrainian supermarkets.
Tokens live at the top of `apps/dashboard/static/dashboard/app.css`.

## Color

- **Promo yellow `--promo` (#FFD21F) marks discounts only**: the shelf tags, the "−20%" chips, the
  promo price label. Never use it for decoration, focus, links or charts.
  Why: it is the one loud color; spent elsewhere, a discount stops standing out.
- Ink is navy `--ink` (#17233A), not near-black. Text sits on `--surface`, or on `--paper` only
  when it is `--ink` or `--ink-2` (`--muted` is too light on paper).
- Price changes: `--good-text` for cheaper, `--bad-text` for dearer, always with ▼ or ▲ and the
  number, so the meaning never depends on color.
- Dark theme is its own token set under `prefers-color-scheme: dark`, not an inversion. Chart and
  status colors were checked for contrast and colour-blind separation in both themes.

## Typography

- Onest for everything; Unbounded only for big price figures (shelf tags, the product price) and
  the wordmark.
- Tables and axes use tabular figures. Prices are formatted by `apps.catalog.formatting.money`
  ("36 999 ₴", "719,20 ₴", "$295.99"): never format money in a template by hand.
- Sentence case everywhere; no all-caps labels, no labels above headings.

## Layout

- Content is left-aligned in a 1180px column with 24px gutters (16px on phones).
- The weekly-drops strip is one shelf: a single row of up to five tags that scrolls sideways.
- Below 1000px the product page stacks the price label above the chart; below 760px tables become
  two-line entries and the compact chart replaces the wide one. The page never scrolls sideways.

## Charts

- Prices are step lines (2px, `--series`), extended to now; out-of-stock periods are a `--band`
  fill with a legend line. Label only the current, lowest and highest price.
- Charts are SVG built in `apps/dashboard/charts.py`, styled by CSS classes, with a crosshair and
  tooltip that also work from the keyboard. Size the viewBox close to the rendered width so 12px
  text stays near 12px.

## Copy

- Ukrainian, plain and specific: "Подешевшало за тиждень", "Показати", "Скинути фільтри".
- Empty states say what to do next.
