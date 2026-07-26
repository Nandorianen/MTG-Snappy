# MTG Local Database — Prototype (spreadsheet UI)

## What this is
A Deckbox-style layout: a narrow tab strip on the left (Tag Database /
Inventory / Wishlist) driving a central spreadsheet. Runs on mock data from
`mock_data.py` — no real database or images yet.

## Run it
```bash
pip install PySide6
python main.py
```

## Try
- **Ctrl+1 / Ctrl+2 / Ctrl+3** — jump between Tag Database / Inventory / Wishlist.
- **Click / Ctrl+click / Shift+click** cells — Excel-like multi-selection.
- **Arrow keys** — navigate cells once one is selected.
- **Ctrl+C** — copies the current selection as tab/newline-separated text
  (paste it into a spreadsheet to see).
- **Checkbox column** — click to toggle per-row selection.
- **"Edition / Rarity" header** — click the left half to sort by set, the
  right half to sort by rarity. Click again to reverse direction.
- **"Price" header** — click the small ▾ on the right edge to pick a price
  source (TCGplayer / Card Kingdom / Cardmarket); click elsewhere in that
  header to sort by price.
- **⋯ button** (rightmost column) — opens a stub actions menu.
- **Hover over a card's Name cell** — a small popover appears after a short
  delay with a placeholder art swatch and the card's text.

## What's deliberately NOT here yet
- Real card images — swatches are colored by mana color identity as a stand-in.
- A real database — `mock_data.get_inventory_cards()` /
  `get_wishlist_cards()` are the two functions that get swapped for real
  SQLite queries later.
- Tag-based filtering (the Tag Database tab shows a tree but it isn't wired
  to anything).
- Drag-to-resize on the two custom header columns (Edition/Rarity, Price) —
  noted as a known limitation in `card_table.py`'s docstring.

