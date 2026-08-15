# Project Context — read this first in a new conversation

Read this for the *why* and the roadmap, then `README.md` for the premise/
usage/changelog, then `NOTES.md` for parked-feature design specifics and
reusable debugging lessons, then the code itself (every file has a
docstring explaining its role and trickier decisions).

## What this is

A local-first, offline-by-default Magic: the Gathering card database and
collection manager, prototyped in Python/PySide6. Built iteratively, one
feature at a time, with detailed UI/UX review after almost every round.
Nothing here is production code — it's a UI/UX prototype meant to get the
interaction design right before the real data layer exists.

## Design goals

These are the app's standing priorities, not a one-time checklist — every
decision below is judged against them.

1. **Offline-first.** Local JSON + SQLite, images downloaded manually
   (configurable scope), updated manually. Optional live-API mode (short
   cache only) as a user toggle, not a fork of the architecture.
2. **Snappy / lightweight.** Custom-painted table cells instead of one
   QWidget per cell; lazy view/dialog construction + staggered background
   preload instead of building everything at launch.
3. **UX first-class, not just polish.** Full keyboard control, hotkeys,
   hover previews, mouse-wheel print switching — implies working across
   variable text scaling/DPI too, not just one reference window size.
   Runtime UI/text scaling infrastructure now exists (`scaling.py`) —
   see the Roadmap and NOTES.md's "Scaling infrastructure" entry for
   what's converted vs. still TODO per file.
4. **Maximum customizability** (look/feel/usability) — theming, UI scale,
   keybinding, config-file moddability. UI scale and text scale are now
   real, independent, live-adjustable runtime settings (see `scaling.py`
   and Options' Interface page); not yet PERSISTED between sessions, and
   theming/keybinding/config-file moddability remain unbuilt — see
   Roadmap.
5. **Complete keyboard support** for anything the mouse can do.
6. **Readable, understandable, solid code** — few crutches, comments and
   docs kept current as design decisions change.
7. **Light on dependencies** (PySide6 + stdlib only so far).
8. **Data model**: a unified master card DB (id/name/prints/images/oracle
   text/rulings/mana cost/types/keywords), a derived structured
   keyword/filter DB, a tag DB (independent parent/child tags, folders
   AND leaves taggable), arbitrary collections (owned/wishlist per-print,
   decks), export/import compatible with other tools (e.g. deckbox.org).

## Architecture decisions

- **Data source: Scryfall**, not Gatherer (no public API). Real pipeline
  (planned, not built): Scryfall bulk JSON → pandas (`json_normalize` +
  `to_sql`, one-time flatten) → SQLite (persistent, queried live) → JSON
  again only for export/import. SQLite over a client-server DB because
  this is single-user local desktop software — no need for that overhead.
- **UI: PySide6 (Qt)**, over a web-wrapper, specifically for goal #3's
  deep keyboard/hover/wheel interactions, which are much more natural via
  native Qt events than a browser/JS bridge. Held up well; not revisited.

## Recurring patterns worth knowing before touching related code

- **"Is this really a new tab/dataset, or just a filter lens on data that
  already exists?"** — Wishlist, then Inventory, each started as their own
  tab/fetch-function and got collapsed into "Card Database" once it was
  clear they were the same rows under a different name. Check this before
  adding a new tab or a new `get_*_cards()`-shaped function.
- **Alignment across independently-laid-out UI needs ONE shared authority**
  (a real shared layout, a shared measured value), not two formulas that
  are each individually "correct" — see NOTES.md's debugging-lessons
  section for the two sagas (filter-menu keyboard nav, card-popup Type
  column) this came from, including why headless Qt testing didn't catch
  either bug the same way twice.
- **A multi-value field (a multicolor card's colors, a type line's several
  words) needs set-membership exclusion, not single-value exact-match** —
  established for Mana Cost's color filter, reused verbatim for Type's.

## File map

- `main.py` — entry point, `MainWindow`, tab wiring (SideNav + stacked
  views), app-wide QSS (built live via `build_stylesheet()`, not a
  static string — see `scaling.py`). Lazy view construction + staggered
  background preload; digit shortcuts (1/2/3, no Ctrl) and the global
  Ctrl+Wheel scale zoom both via the same app-level event filter, so
  neither steals input from a focused text field.
- `scaling.py` — **the other seam**: `scale_manager`, the single runtime
  source of truth for `ui_scale`/`text_scale`, plus the `sp()` helper
  every fixed-pixel constant elsewhere in the app should route through.
  One `scale_changed` signal every scale-aware widget listens to. See
  NOTES.md's "Scaling infrastructure" entry for the design and current
  per-file conversion status.
- `mock_data.py` — **the seam**: every function here is what gets
  reimplemented against real SQLite later, with the same signature/return
  shape, so calling code elsewhere never needs to change.
- `card_database_view.py` — wraps `CardTableView` with the Inventory/
  Wishlist/Columns/Clear-Filters button row (two-way synced with the
  table's own filter state) and its own keyboard nav/hotkeys.
- `card_table.py` — the spreadsheet: model (data/sort/group/filter),
  header (paint/menus/keyboard focus), view (selection/hotkeys/tag menu),
  `_MenuSearchBox` (shared keyboard machinery for every filter-menu text
  box). Biggest, most-iterated file — read its module docstring first.
- `card_detail_popup.py` — the double-click detail dialog: one
  `QGridLayout` stat area (guarantees column alignment across rows),
  edition/language/condition/foil selectors + Apply, Legality/Rulings
  panes, a standalone pan/zoom image viewer.
- `card_popover.py` — lightweight hover-preview popup (distinct from the
  full detail dialog).
- `frameless_dialog.py` — shared base (`FramelessDialog`) for no-title-bar
  popups (card detail, tag-apply, and — via `dialog_common.py` — Options/
  Data Management).
- `dialog_common.py` — `VerticalTabDialog`: shared vertical-tab-list +
  stacked-page + Ctrl+Tab chrome for Options and Data Management (siblings
  sharing a base, not one inheriting the other). Lazy per-tab page
  construction.
- `options_dialog.py` / `data_management_dialog.py` — settings/data-import
  windows; UI shells only so far (see Roadmap).
- `tag_apply_dialog.py` / `tag_assignments.py` — tag-apply workflow (tri-
  state checkbox tree) and its card-name → tag-id store.
- `tree_pane.py` — the **generic** reusable folder/item tree (CRUD,
  rename, drag-drop, clipboard, icons, hotkeys); used by both
  `tag_tree.py` and `deck_viewer.py`.
- `collapsible_pane.py` — `CollapsibleSplitter`, resizable/collapsible
  pane wrapper.
- `side_nav.py` — left tab strip; `TABS` is the single source of truth
  for order/labels/shortcuts.
- `README.md` — premise, usage, changelog (newest first).
- `NOTES.md` — parked-feature design notes + reusable debugging lessons.

## Roadmap

Status: **Done** / **Partial** (shell or simplified version exists) /
**TODO** (not started). Grouped by component; see NOTES.md for design
specifics on any TODO or Partial item.

### Card Database table
- Spreadsheet display, sort, Deckbox-style grouping (Type/Color) — **Done**
- Filtering: bounded checklist (Type/Mana/Edition/Rarity) w/ search-narrow
  box — **Done**
- Filtering: typed expression (Have/Want/Power/Toughness/Price/Name) —
  **Done**
- Column visibility, Inventory/Wishlist toggle presets, Clear Filters —
  **Done**
- Full keyboard support: cells, headers, filter menus, meta-button row —
  **Done**
- Row selection menu: Apply Tags / Add to Inventory / Add to Wishlist —
  **Done**; Add to Deck — **Partial** (honest stub, no deck contents yet)
- "Filter by [this card's X]" menu items — **TODO** (needs search engine)
- Edition mini-widget (folder-grouped, name/code/year picker for large
  edition lists) — **TODO**, shared by table filter + image-download picker

### Card detail popup
- Stat grid, edition/language/condition/foil selectors + Apply — **Done**
- Legality / Rulings panes — **Done**
- Pan/zoom/reticle-select image viewer — **Done** (placeholder art)
- Resizable window / DPI-aware layout — **TODO** (fixed-size for now)

### Tag system
- Tag Database tree, tri-state tag-apply dialog — **Done**
- Search/filter box inside the tag-apply tree — **TODO**
- User-assignable per-branch hotkey letter sequences — **TODO**

### Deck Viewer
- Folder/deck tree CRUD — **Done**
- Real per-deck card contents (table) — **TODO**

### Data layer
- Mock in-memory data (`mock_data.py`) — **Done** (stand-in)
- Data Management dialog UI (Metadata/Images/Decks&Tags tabs, real Browse
  + async stat/folder-size) — **Partial** (no download/parse/persist
  pipeline)
- Real Scryfall bulk-JSON → SQLite import — **TODO**
- Local card-image storage + optional live-API fetch mode — **TODO**
- Structured keyword/filter database (goal #4) — **TODO**

### Options / Settings
- Window shell (6 tabs, Apply feedback) — **Partial** (nothing persists)
- Real settings store — **TODO**
- Theming (QPalette-driven accent/light-dark, replacing hardcoded QSS) —
  **TODO**
- String externalization / i18n — **TODO**
- UI scale / text scale, live-adjustable (Interface page sliders +
  global Ctrl+Wheel) — **Partial** (real and live at runtime; not
  persisted; several files' inline QSS and a few lazily-built settings-
  page widgets don't yet live-rescale an already-open window — see
  NOTES.md's "Scaling infrastructure" entry for the exact list)
- DPI-awareness beyond ui_scale/text_scale (querying the OS's own
  display-scale setting as a starting default) — **TODO**

### App-wide
- Lazy tab/dialog construction + background preload — **Done**
- Runtime UI/text scaling (`scaling.py`, Ctrl+Wheel, Options sliders) —
  **Partial** — see Options/Settings section above and NOTES.md
- Flexible cross-field search engine + Ctrl+F popup — **TODO** (landing
  spot reserved in `card_database_view.py`'s button row)
- Undo/redo + explicit-save-vs-autosave model — **TODO**
- Export/Import (e.g. deckbox.org) — **TODO**
- Default-add behavior (language/printing/condition defaults) + collapsing
  owned variants into one summary row — **TODO**
