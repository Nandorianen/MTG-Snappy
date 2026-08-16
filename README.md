# MTG Local Database — Prototype

A local-first, offline-by-default Magic: the Gathering card database and
collection manager (Python/PySide6). A Deckbox-style layout: a left tab
strip (Card Database / Tag Database / Deck Viewer) driving swappable
central views. Runs entirely on mock data today — no real Scryfall import,
no real images, no real SQLite yet. See `PROJECT_CONTEXT.md` for the full
design-goals-and-roadmap picture and `NOTES.md` for parked-feature design
notes and reusable debugging lessons.

## Run it

```bash
pip install PySide6
python main.py
```

## Try — Card Database (spreadsheet)

- **1** — jump to Card Database (no Ctrl; digit shortcuts are suppressed
  while a text field has focus).
- **Inventory / Wishlist buttons** — toggle excluding Have == 0 / Want ==
  0; both can be on at once, two-way synced with the header's own
  right-click filter state.
- **Columns button** — toggle column visibility. **Clear Filters** (also
  Ctrl+Alt+F) — resets every filter at once, including remembered search
  text.
- **Click / Ctrl+click / Shift+click** — Excel-like multi-selection.
  **Ctrl+C** — copy selection as tab/newline-separated text.
- **Right-click a header** — Type/Mana color/Edition/Rarity get a
  search-narrowable checklist; Have/Want/Power/Toughness/Price/Name get a
  typed expression box (`>10`, `<=3.2`, `!=sliver`, or a bare partial
  match). Type/Mana/Price also get Group-by/Price-Source controls in the
  same menu. Full keyboard support throughout (Up/Down/Tab/Space/Enter,
  Home/End/PageUp/PageDown, Clear Filter as a navigable stop).
- **Alt+Shift+Up/Down from a cell** (or Ctrl+Tab from the button row) —
  jump to that column's header; Left/Right cycles headers; Down opens its
  menu; Enter/Space sorts.
- **F2** (Qty), **Shift+Space/Ctrl+Space** (select row/column),
  **Ctrl+Home/End**, **Ctrl+Arrow** (move to edge), **Ctrl+Shift+Arrow**
  (extend to edge), **Ctrl+Tab/Shift+Tab** (jump between groups when
  grouped) — Excel-familiar throughout; see NOTES.md for the still-missing
  gaps (contiguous-block-aware jumping, fill-handle).
- **Hover a card's Name** — placeholder-art popover. **Double-click a
  row** — full detail popup. **Right-click a row/selection** — Apply
  Tags, Add to Deck (stub), Add to Inventory/Wishlist (Alt+A/D/E/W).

## Try — Tag Database / Deck Viewer

- **1 / 3** — jump to Tag Database / Deck Viewer.
- **Ctrl+N / Ctrl+Shift+N** — new item/folder, immediately renameable.
  **F2** rename, **Delete** delete (with confirmation).
- **Drag-and-drop** or **Ctrl+X/C/V** — reorder/reparent (cycle-guarded,
  same-name deduped on paste).
- **Right-click** — full menu incl. icon color picker.
- **Tab**, or the divider's **◂/▸** arrow, or clicking the content area —
  collapse/expand the tree pane.

## Try — File menu

- **Ctrl+M** Data Management (Scryfall bulk-data file linking, card-image
  format/folder settings) — real file/folder browsing, no real download
  pipeline yet.
- **Ctrl+,** Options (language/themes/online/interface/input/advanced) —
  UI shell only, nothing persists yet.

## Limitations — what's deliberately not here yet

Real card images and the real Scryfall/SQLite data layer; deck contents
(Deck Viewer's right pane is a placeholder); the flexible cross-field
search engine; an edition mini-widget for large real edition lists;
theming (light mode / system accent colors) and DPI/text-scaling
awareness; settings persistence; string externalization/i18n; undo/redo;
export/import; delete confirmation is plain (no "don't ask again"). Full
list with design notes for each: `PROJECT_CONTEXT.md`'s Roadmap and
`NOTES.md`.

---

## Changelog (newest first)

**Scaling polish: bigger steps, smoother wheel-zoom, screen-safe dialogs,
wrapping labels.** Ctrl+wheel and both Options sliders now move in 10%
increments (previously an inconsistent 5% on the wheel vs. a fiddly
default 1% on the sliders' arrow-keys/click-track). Ctrl+wheel scale
changes are now coalesced (~50ms after scrolling stops) instead of
rebuilding the whole app-wide stylesheet on every individual wheel notch
-- that per-notch full-app QSS rebuild, not a PySide rendering limit, was
what made a fast scroll feel laggy; see NOTES.md's "Scaling infrastructure"
entry. Every frameless dialog (card detail, tag-apply, Options, Data
Management) now clamps its size to the current screen and scrolls (both
directions) instead of growing off-screen at a high scale; Data
Management's own dialog size is now sp()-scaled too (previously a bare,
non-scaling 880x620). The side nav's own tab labels ("Tag Database", etc.)
now wrap instead of clipping at a high text scale; Options'/Data
Management's tab list already gets the same for free via Qt's native
QListWidget word-wrap, now turned on.

**Type filter search box, Price Source keyboard access, Clear Filter
cleanup.** Type's Enter now applies a typed expression against the card's
full raw type line (finds subtypes/substrings the word checklist can't),
layered on the checklist's own word exclusion. Price Source is a real
keyboard-operable submenu again after two failed attempts (see NOTES.md).
Clear Filter / Clear All Filters now also forget remembered search-box
text, not just real filter state.

**Filter-menu keyboard nav + Type filter redesign.** Every filter box
(checklist and expression alike) now shares one keyboard-nav class
(`_MenuSearchBox`) — fixes Down landing back on the textbox, adds a
keyboard-reachable "Clear Filter" on every column, fixes Up-collapses,
remembers checklist search text across reopens. Type's filter became
word-based (`_type_words`) instead of reusing the single-category
grouping function, fixing "Artifact" never matching "Artifact Creature."

**Column split + filter overhaul, menu focus-leak fix.** Edition/Rarity
became two ordinary columns (no more custom-painted split section).
Have/Want/Power/Toughness/Price/Name switched from an unscalable value
checklist to a typed expression box; Type/Mana/Edition/Rarity kept the
checklist (genuinely bounded sets). Fixed a real leak: every filter
menu's search box now gets `deleteLater()`'d on close instead of piling
up forever as hidden children of the header.

**Keyboard access for table headers.** Headers are now keyboard-
focusable independently of Qt's real focus — Alt+Shift+Up/Down from a
cell (or Ctrl+Tab from the button row) reaches a header; Left/Right
cycles, Down opens its menu, Enter/Space sorts, Tab hands back to the
table. Page Up/Down/Home/End also now work inside an open filter menu.

**Row context-menu rework: selection-scoped actions.** Right-click now
opens a real action menu (Apply Tags/Add to Deck/Add to Inventory/Add to
Wishlist, each also Alt+-hotkeyed) plus six disabled "Filter by..."
placeholders reserving the spot for the future search engine. The old
per-row "..." actions column is gone — every action it held was
selection-scoped already.

**Keyboard navigation polish: group-aware edges.** Ctrl+Up/Down at a
group's edge now hops into the adjacent group instead of stopping dead;
fixed a selection-rendering bug where extending across a group-header row
selected that row's full width. Ctrl+Arrow/Shift+Arrow stop at the
current group's edge (not the table's); Page Up/Down jump between
groups; headers/menus hand keyboard focus back to the table on close; an
arrow press with nothing selected plants the top-left cell; a plain arrow
already at the edge collapses a stale multi-cell selection.

**Header cleanup, Ctrl+Arrow/Tab, mono-color-X fix.** Fixed a stray sort
arrow painted on non-sortable columns before anything had ever been
sorted (a `None == None` bug). Type/Mana/Price's separate dropdown-arrow
zone is gone — Group-by/Price-Source moved into the same right-click menu
the value filter already has. "Monocolored only" no longer wrongly
excludes colorless/X-cost cards. Added plain Ctrl+Arrow (move without
extending) and Ctrl+Tab/Shift+Tab (jump between groups, wrapping).

**Startup empty-state, tab reorder, Excel-parity fixes.** App now opens
with no tab selected (an empty placeholder) instead of defaulting to Tag
Database — nothing builds eagerly. Tab order is Card Database/Tag
Database/Deck Viewer, switchable via bare 1/2/3 (an app-level filter, so
a focused text field still gets the literal digit). Added F2 edit,
Shift+Space/Ctrl+Space, Ctrl+Home/End, Ctrl+Shift+Arrow; new keyboard-
selection anchor tracking fixes two real bugs (a Ctrl+Shift+chain losing
its original anchor; Ctrl+End appearing to select two cells at once).
Header now shows a sort-direction arrow and a filter-active dot per
column. New Clear Filters button + Ctrl+Alt+F.

**Loading time / launch performance.** Lazy top-level view construction
(only the visited tab builds) plus a staggered main-thread preload chain
for everything else, so idle time after launch gets used without
reintroducing a blocking build. Lazy dialog imports and a `QSplashScreen`
shown before `MainWindow` construction begins address perceived, not
actual, cold-start cost — most of that cost is native Qt library loading,
outside Python's reach. See NOTES.md for the full profiling story.

**Data Management window + shared dialog base.** New `DataManagementDialog`
(Metadata / Card Images / Decks & Tags tabs) — real file/folder Browse
with async `os.stat()`/folder-size reads (never blocks the UI thread), no
real download pipeline. Extracted `dialog_common.py`'s `VerticalTabDialog`
as the shared tab-list/stack/Ctrl+Tab base once a second dialog needed the
identical chrome.

**Options window (UI shell).** New `OptionsDialog` — six tabs
(Language/Themes/Online/Interface/Input/Advanced), Apply/Cancel/OK,
nothing persists yet. Accent swatches are `QRadioButton`s for free
arrow-key cycling.

**Reticle-select zoom on the card image.** Real pan+zoom image viewer
(`ImageZoomWidget`): mouse wheel zooms, drag pans once zoomed past
fit-to-screen, Ctrl+drag reticle-selects a region to zoom to. Third design
attempt — see NOTES.md for what the first two got wrong.

**Card detail popup: Type-column alignment overhaul.** All three stat
rows now share one `QGridLayout` so column widths are a single
Qt-enforced number instead of independently-reconstructed per row; column
widths are locked post-layout (safe only because the dialog is
fixed-size). Three earlier formula-based fixes didn't work — see
NOTES.md's debugging-lessons section.

**Card Database merge + filter-menu keyboard nav fixed.** All Card
Database and Inventory collapsed into one "Card Database" tab (Inventory
was always just a Have>0 filter lens on the same data). New
`CardDatabaseView` wraps the table with Inventory/Wishlist/Columns
buttons. Filter-menu Up/Down/Space navigation actually fixed this round —
root cause was missing `QMenu` QSS, not broken event routing (see NOTES.md).

**Detail popup, mono-color, and keyboard-parity fixes.** Fixed a
double-subtracted arrow-reservation bug in centered dropdown fields.
Mana Cost filtering redesigned to a per-color exclusion set (a multicolor
card matches on any color it contains). Added a real "Apply to Inventory"
button. Added F2/Shift+Space/Ctrl+Space/Ctrl+Home/End/Ctrl+Shift+Arrow.

**Alignment & interaction fixes.** Type/Condition/Language/Mana Cost now
wrap instead of truncating where needed. `CardDetailDialog`/
`TagApplyDialog` share one `frameless_dialog.py` base. Mana Cost's
checklist narrowed to just the 5 mono colors, with "Monocolored only" as
an independent persistent toggle. Right-click no longer drops a
multi-row selection depending on which column it lands on.

**Detail-popup layout + filter-menu polish.** Type's caption centers
within a notional 1/3 slot even though its value spans 2/3. Centered
dropdown fields actually center now (matching left/right padding). Search
boxes auto-focus on right-click; Mana Cost gained "Monocolored only";
Price became filterable.

**Tag-apply widget.** Right-click any row (or multi-selection) for a
tri-state checkbox tree mirroring the Tag Database — folders AND leaves
independently taggable. Backed by `tag_assignments.py`, keyed by tag ID
so renames never orphan assignments.

**Filter improvements + layout fixes.** Card-pane rows actually split
into even thirds now. Every filter menu gained a search-narrow box. Mana
Cost's filter switched to color categories. Power/Toughness's missing
values show as "(none)" instead of being silently excluded from the
filter.

**Repurposing pass.** Wishlist folded into "All Card Database" (Have/Want
shown together) — the first of two "this is just a filter lens" collapses
(see PROJECT_CONTEXT.md).

**Polish pass.** Immediate side-nav highlight on press. Uniform header
background color across custom-painted and plain headers. Added a
cross-reference Have/Wished count column. Rulings pane got a real border;
Language/Condition/Foil moved to their own row; Foil reads Yes/No.

**Frameless detail popup, Power/Toughness split, broader type filter.**
Frameless card detail dialog (own title bar, click-outside-closes,
verified against its own dropdown menus). Power/Toughness became
independent sortable columns. Type's filter offers broad categories
instead of literal type lines.

**Header filter, column picker, group-by.** Right-click any header for a
value checklist (most columns) plus a Show Columns submenu. Type/Mana
Cost gained a dropdown for Group by Type/Color, inserting Deckbox-style
sub-header rows.

**Card detail popup (initial).** Double-click a row: name, clickable art
placeholder (opens a zoom window), fixed-position stats, oracle/flavor
text, Legality and Rulings tabs. Edition/Price are dropdowns.

**Tree tabs (Tag Database / Deck Viewer).** Full folder/item CRUD,
rename, delete, drag-and-drop, Ctrl+X/C/V, right-click color picker,
collapsible/resizable side pane.
