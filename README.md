# MTG Local Database — Prototype

## Repurposing pass (this round)
- **Wishlist is gone as a standalone tab.** It's replaced by "All Card
  Database" -- the full browsable catalog, showing both Have and Want
  counts for every card. Inventory is the same shape of data, filtered to
  what you actually own. Isolating "what I want" is now just: right-click
  the Want column on either table, uncheck "0". Tab order changed
  accordingly: Tag Database, All Card Database, Inventory, Deck Viewer
  (Ctrl+1..4) -- All Card Database took Inventory's old slot, Inventory took
  Wishlist's.
- Header background is now a deliberately darker near-black (matching what
  used to show up by accident before it got "fixed" to match the rows) --
  applied uniformly across plain and custom-painted headers alike.
- Card detail popup: Edition/Rarity/Price and Language/Condition rows are
  now center-aligned across the board, instead of left-aligned in a way
  that read as inconsistent next to the Type/Mana row's intentional
  left/center split.

## Polish pass (earlier round)
- Side nav buttons now highlight the instant you press them, not after a
  visible dashed-focus-rect-then-highlight delay (the delay was a native
  focus rectangle Qt draws before our own styling takes over — removed via
  `outline: 0`, plus an explicit `:pressed` style for immediate feedback).
- Table headers are now visually uniform — the custom-painted ones
  (Edition/Rarity split, Type/Mana/Price dropdown arrows) were reading their
  background from the widget's base palette instead of the app's actual
  stylesheet color, which are two different things in Qt; they now share
  one explicit color constant with the plain headers.
- Added a cross-reference count column: Inventory shows "Wished" (how many
  you've wishlisted), Wishlist shows "Have" (how many you own) — sortable,
  toggleable via Show Columns like any other.
- Detail popup: Rulings pane now has a proper visible border (QListWidget
  wasn't in the app's bordered-widget style rule at all — now is) and is
  guaranteed at least as wide as the Legality pane.
- Detail popup: Language/Condition/Foil moved to their own third metadata
  row, separate from Edition/Rarity/Price, so the card pane isn't
  overcrowded.
- Detail popup: Foil now reads "Yes"/"No" instead of "On"/"Off".
- Detail popup: the Type/Mana Cost row is now a true proportional 2:1
  split of the row's actual width (via layout stretch, not fixed pixel
  guesses) — Type left-aligned, Mana Cost centered.

## Frameless detail popup, Power/Toughness split, broader type filter
- Opening the detail popup now cancels any hover popover already showing
  or waiting out its delay timer.
- Tree panes (Tag Database / Deck Viewer): removed the "+ Item"/"+ Folder"
  toolbar buttons (right-click menu and Ctrl+N/Ctrl+Shift+N cover the same
  ground) and made tab-switching set focus deterministically — this is
  what actually fixes Tab not collapsing the pane on the very first press.
- Removed the native dashed "focus rectangle" Qt draws on top of selected
  items (kept the color highlight, which was already the intended look).
- Detail popup: Legality pane now sizes itself to the widest text that can
  actually occur, with word-wrap as a fallback, instead of a cramped
  proportional share of the width.
- Detail popup: removed the OS title bar entirely — frameless window with
  its own thin title bar (name + close button), draggable by that bar,
  closes automatically when you click anywhere in the main app window
  (verified this doesn't misfire when clicking the popup's own dropdown
  menus, which are technically separate top-level windows).
- Detail popup: added Language and Condition dropdowns and a Foil toggle
  alongside Edition/Rarity/Price.
- Table: Power and Toughness are now independent columns (sortable/
  filterable separately) rather than one combined "P/T" column.
- The Type column's right-click filter checklist now offers broad
  categories (Creature, Instant, ...) instead of full literal type lines.
- Parked for later (see NOTES.md): an options/settings window with
  externalized per-language string files, "have"/"want"/"in-deck" count
  columns, and default-add behavior with variant grouping.

## Header filter, column picker, group-by
- **Right-click any header** in Inventory/Wishlist: for most columns, a
  checklist of every distinct value in that column (uncheck a value to hide
  matching rows — check it again to bring them back), plus a **"Show
  Columns"** submenu to toggle any column's visibility live.
- **Type / Mana Cost headers** now have the same ▾ dropdown arrow Price
  has — click it for **"Group by Type"** / **"Group by Color"**. Grouped
  view inserts a full-width sub-header bar between groups (Deckbox-style:
  Creatures, then Instants, etc.; Colorless, then White, Blue, ... then
  multicolor combos like "U/B"). Click again to un-group.
- Group-header rows are inert — not selectable, not checkable, don't open
  the detail popup or hover popover.
- Known simplification: the Edition/Rarity column's filter checklist works
  off the Set only (not Rarity); Price isn't filterable this way since it's
  continuous data — real range filtering is planned as part of the
  upcoming Search feature.

## Card detail popup
- Double-click any row: name, clickable art placeholder (opens a separate
  zoomable/draggable window), fixed-position stats (Type / Mana Cost /
  Edition / Rarity / Price), oracle + flavor text, Legality and Rulings tabs.
- Edition and Price fields are dropdowns — switching editions updates
  rarity/price/flavor text; switching price source updates the price shown.

## Tree tabs (Tag Database / Deck Viewer)
- Full folder/item CRUD: create, rename (F2), delete (with confirmation),
  drag-and-drop, Ctrl+X/C/V (with cycle-detection and same-name dedup),
  right-click menu with icon color picker.
- Collapsible/resizable side pane: drag the divider, click the tall arrow
  on it, press Tab, or click into the right-hand content area.

## What this is
A Deckbox-style layout: a tab strip (Tag Database / All Card Database /
Inventory / Deck Viewer) on the left driving swappable central views. All
Card Database and Inventory are spreadsheets; Tag Database and Deck Viewer
are collapsible folder/item trees. Runs on mock data — no real database or
images yet.

## Run it
```bash
pip install PySide6
python main.py
```

## Try — spreadsheet tabs (All Card Database / Inventory)
- **Ctrl+2 / Ctrl+3** — jump to All Card Database / Inventory.
- **Click / Ctrl+click / Shift+click** cells — Excel-like multi-selection.
- **Ctrl+C** — copy the selection as tab/newline-separated text.
- **"Edition / Rarity" header** — click left half to sort by set, right half
  by rarity.
- **"Price" header** — click the ▾ to pick a price source; click elsewhere
  to sort by price.
- **"Have" / "Want" columns** — right-click, uncheck "0" to isolate cards
  you own / cards you've wishlisted.
- **⋯ button** — stub actions menu. **Hover a card's Name** — popover with
  placeholder art + text.

## Try — tree tabs (Tag Database / Deck Viewer)
- **Ctrl+1 / Ctrl+4** — jump to Tag Database / Deck Viewer.
- **Ctrl+N / Ctrl+Shift+N** — create a new item/folder; it's immediately
  renameable with all text pre-selected, so typing replaces the name right
  away. (Also available via right-click.)
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

