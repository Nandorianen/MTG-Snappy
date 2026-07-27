# MTG Local Database — Prototype

## Recent addition (this pass): card detail popup
- **Double-click any row** in Inventory/Wishlist to open it: name, a
  clickable art placeholder, fixed-position stats (Type / Mana Cost /
  Edition / Rarity / Price), oracle text, flavor text, plus Legality and
  Rulings tabs.
- **Click the art** to open it in a separate frameless window: scroll to
  zoom, drag anywhere by holding and moving, close with right-click or Escape.
- **Edition field** — dropdown of every printing this card has (mock data
  has 2 for Lightning Bolt and Swords to Plowshares to demonstrate it);
  switching updates rarity, price, and flavor text.
- **Price field** — dropdown to pick TCGplayer / Card Kingdom / Cardmarket,
  same as the table's Price header.

## Earlier fixes
- Cut+paste of a folder into its own descendant is now blocked (previously
  hung the app) -- rejected with an OS beep + a brief red flash on the item.
- Pasting an item with a name that collides with an existing sibling now
  auto-renames it "Name (1)", "Name (2)", etc.
- Delete now asks for confirmation first.
- Tab reliably collapses/expands the tree pane regardless of which child
  widget currently has keyboard focus.
- The collapse arrow on the pane divider is taller and vertically centered.

## What this is
A Deckbox-style layout: a tab strip (Tag Database / Inventory / Wishlist /
Deck Viewer) on the left driving swappable central views. Inventory and
Wishlist are spreadsheets; Tag Database and Deck Viewer are collapsible
folder/item trees. Runs on mock data — no real database or images yet.

## Run it
```bash
pip install PySide6
python main.py
```

## Try — spreadsheet tabs (Inventory / Wishlist)
- **Ctrl+2 / Ctrl+3** — jump to Inventory / Wishlist.
- **Click / Ctrl+click / Shift+click** cells — Excel-like multi-selection.
- **Ctrl+C** — copy the selection as tab/newline-separated text.
- **"Edition / Rarity" header** — click left half to sort by set, right half
  by rarity.
- **"Price" header** — click the ▾ to pick a price source; click elsewhere
  to sort by price.
- **⋯ button** — stub actions menu. **Hover a card's Name** — popover with
  placeholder art + text.

## Try — tree tabs (Tag Database / Deck Viewer)
- **Ctrl+1 / Ctrl+4** — jump to Tag Database / Deck Viewer.
- **"+ Deck"/"+ Tag" and "+ Folder" buttons, or Ctrl+N / Ctrl+Shift+N** —
  create a new item; it's immediately renameable with all text pre-selected,
  so typing replaces the name right away.
- **F2** — rename the selected item. **Delete** — delete selected item(s).
- **Drag and drop** — reorder/reparent items (drop onto a folder to move
  inside it). **Ctrl+X / Ctrl+C / Ctrl+V** — cut/copy/paste as an
  alternative to dragging.
- **Right-click** — full context menu, including a color-swatch submenu to
  recolor an item's icon.
- **Click the small ◂/▸ arrow at the top of the divider** between the tree
  and the content area — collapses/expands the tree pane. **Tab** — same
  toggle, from anywhere in that view. **Clicking anywhere in the right-hand
  content area** — also collapses the tree pane, to reclaim space once
  you've picked something.

## What's deliberately NOT here yet
- Real card images.
- Any real database — the tree/table data all comes from hardcoded seed
  data (`mock_data.py`, `deck_viewer.py`, `tag_tree.py`); each has one clearly
  marked function/constant that gets swapped for a real query later.
- Tag-based card filtering, deck contents view, column right-click filtering
  and grouping, card detail popup, and the tag-apply widget — all upcoming.
- Drag-to-resize specifically on the Edition/Rarity and Price header cells
  (documented limitation in `card_table.py`).
- Delete confirmation dialogs (documented limitation in `tree_pane.py`).

