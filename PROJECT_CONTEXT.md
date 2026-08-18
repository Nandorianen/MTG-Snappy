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

## Data & API architecture (planned, not yet built)

Design for the real data layer that `mock_data.py` currently stands in for
(see that module's own docstring for the "swap the engine, keep the
interface" contract this has to honor). Nothing below is built yet — see
the Data layer Roadmap section for status — this is the agreed shape so
later work has one spec to build against instead of re-deciding it
per-feature.

**Three kinds of data, one rule: the app ships with none of them.** Bulk
Scryfall card/oracle JSON, Scryfall card images, and the user's own local
data (collection, decks, tags) are all acquired after first launch, never
bundled — first run is a genuinely empty app (already true of the mock
data's *shape*, e.g. `get_all_cards()`'s empty-collection case; this
extends the same expectation to "no metadata at all yet" too).

**Storage engine: SQLite, confirmed — not NoSQL.** Revisited after
poking at a real bulk export (~140k rows today, ~90 columns raw,
~2.5GB on disk, both numbers only growing) — neither number changes the
original call. A few hundred thousand rows with real indexes is small
for SQLite; the width and file size are a SCHEMA/IMPORT question, not a
reason to reconsider the engine (see the two subsections immediately
below). SQL's relational joins are also the natural fit for how this
data actually gets used: card metadata joined against the user's own
collection/deck/tag tables by id, plus genuinely bounded categorical
filters (Type, Rarity, Edition — already special-cased in
`card_table.py` as checklist columns) and multi-value set-membership
exclusion (colors, type words) — all squarely relational-query shaped,
not document-store shaped.

**Why the raw column count is a normalization question, not a sizing
one.** A raw Scryfall card object is wide because several fields are
really "one row per (card, something-else)" flattened into columns, not
because a card has ~90 independent scalar attributes:
- `legalities` (~20 formats) becomes its own child table
  (`card_id, format, status`) — this is already the SHAPE
  `mock_data.py`'s `CARD_LEGALITIES`/`get_card_legalities()` models as a
  lookup, not flat columns; the real schema should match what the app
  already assumes.
- Per-source prices become their own child table
  (`card_id, source, price, updated_at`) — same reasoning, matching
  `PRICE_SOURCES`'s existing per-source shape.
- Rarely-touched nested blobs (`card_faces`, `image_uris`,
  `purchase_uris`, `related_uris`) aren't worth flattening into more
  columns at all — store the raw sub-object as a JSON text column
  (SQLite's `json1` extension supports querying into it later if that
  ever becomes necessary) rather than exploding it into dozens of
  single-use columns.

Once legalities/prices/nested-blobs are pulled out, the genuinely
filterable/sortable surface (name, type_line, colors, rarity, set, cmc,
power, toughness, keywords, ...) is a normal, narrow, well-typed table —
this is the schema the import pipeline should actually build, not a
1:1 flatten of Scryfall's raw JSON shape.

**Working set vs. cold storage — what actually needs to be in memory.**
SQLite stays PURE STORAGE, not something queried live on every filter/
sort/group change: one "give me everything" read at startup returns the
same list-of-dicts shape `get_all_cards()` already returns today, and
`CardTableModel`'s existing (already-built, already-tested) Python-side
filtering/sorting/grouping is untouched — this keeps `mock_data.py`'s
own "swap the engine, keep the interface" contract intact. Only push
filtering into SQL `WHERE`/`ORDER BY` later if profiling actually shows
the in-memory approach costing something real — not a default posture.

The in-memory working set itself should be the LEAN table only: name,
mana_cost, cmc, type_line, colors, set, rarity, power, toughness,
keywords, one default price — the ~15 fields the table view actually
touches for every row. Everything else (full legalities, rulings,
flavor text, all price sources, purchase/related URIs, alternate card
faces) stays in SQLite as a lazy PER-CARD lookup, fetched only when a
specific card's detail popup opens — exactly the pattern
`card_detail_popup.py` already uses today (`get_card_prints`/
`get_card_legalities`/`get_card_rulings`, called once per double-click,
not preloaded for the whole table). At ~200k cards, a working set this
lean lands in the neighborhood of a few hundred MB in memory (Python's
per-object overhead — dict headers, string/list objects for colors and
keywords — costs more than the raw field bytes suggest, but nowhere
near a scale that argues against "load it all into a list at startup").

**Import has to stream, not load-the-whole-file.** The 2.5GB (and
growing) bulk file is where that size number actually matters: parsing
it whole into memory (`json.load()`, or a naive `pandas.json_normalize`
over the full structure) can spike RAM to several times the file size
mid-import, and that spike only gets worse as Scryfall's export grows.
The import pipeline needs a STREAMING parser (e.g. `ijson`, or manual
line-by-line IF the file turns out to genuinely be JSONL rather than
one large JSON array — worth confirming which at implementation time,
since Scryfall's bulk exports have historically been a single JSON
array, not JSONL, despite the `.jsonl`-sounding informal name some of
this project's own notes/filenames use) that reads and inserts into
SQLite in BATCHES, so peak import memory stays roughly constant
regardless of how large the bulk file grows, rather than scaling with
it.

**Bootstrapping the card database.** The user either points the app at
bulk JSON file(s) they downloaded manually, or uses Data Management's
"Download bulk data" to fetch one directly (both paths land in the same
place — see `data_management_dialog.py`'s Metadata tab, currently a UI
shell over this). The chosen file is parsed and flattened into a local
SQLite database (planned: `json_normalize` + `to_sql`, per this doc's own
Architecture Decisions above). **Default Cards** (every printing, one
language) is the intended *primary* import — it's the file that actually
covers what `CARD_PRINTS`/`get_card_prints()` model today. Oracle Cards /
Unique Artwork / All Cards / Rulings are supplementary and independently
opt-in; Art Tags / Oracle Tags are a separate Scryfall Tagger-project
export, not part of core bulk data at all (this distinction is already
called out in `METADATA_SECTIONS`'s per-file descriptions). This import
can be re-run from a fresh bulk snapshot at any time to rebuild the DB
from scratch — the correct recovery path whenever the DB is suspected
stale or corrupted, not just the first-run path.

**Routine freshness is incremental, not a repeated full bulk download.**
Once a DB exists, the intended update path is targeted API calls —
e.g. querying Scryfall's search endpoint by set code when a new edition
releases — merged into the existing SQLite DB **by Scryfall's own card
ID**, not a wholesale table replace. A full bulk re-import (above) stays
available as the deliberate "start over" path when something needs a
clean slate; day-to-day updates shouldn't need it.

**Metadata tables and user-data tables are strictly separate** — already
the design `mock_data.py`'s own docstring describes (a "prints" table
vs. a "collection" table), restated here because it's what makes bulk
rebuild *safe*: rebuilding only ever drops/repopulates Scryfall-sourced
tables, and should never need to touch a collection/deck/tag table at
all. If a future change makes that boundary blurry, that's a design bug
to fix before shipping it, not something to special-case around.

**Migrations, for both retroactive corrections and schema changes.** A
`schema_version` table plus small, ordered migration scripts, checked
and applied automatically on startup whenever the DB's version is behind
the app's — covers both a genuine table-shape change (a new column) and
a data correction that needs to apply going forward (Scryfall errata, a
card's oracle text changing). Both the full bulk-rebuild path and the
incremental-fetch path can trigger a migration if the data they bring in
implies one; neither path is exempt.

**Image storage:** fetched via Scryfall's API (on demand, or a bulk
pre-fetch job), saved under a structured local path mirroring a print's
own identity — `{images_root}/{language}/{set_code}/{collector_number}/
{size_or_crop}.jpg` (exact separators/extension TBD at implementation
time, but the four-level shape — language, set, collector number, size —
is the agreed structure, matching `IMAGE_FORMATS`' existing size/crop
vocabulary in `data_management_dialog.py`). Before any fetch, the app
checks whether a correctly-placed local file already exists and is
valid, and uses it directly — a network fetch only happens for something
genuinely missing, or an explicit user re-fetch/delete-and-refetch. The
folder structure itself IS the existence index (directly checkable, no
separate manifest DB to keep in sync) — which is also why the layout has
to be exact and consistent, not "however a given version happened to
save it."

**Missing-data resilience, everywhere.** Local records (a deck's card
list, a collection entry) reference cards independent of whether the SQL
DB actually has that card populated — every view is expected to degrade
gracefully rather than error or silently drop a row: a deck listing a
card missing from the DB shows it by the NAME the deck/collection entry
itself stored, with blank/dash stats, not an exception or an omitted
row; a print with no locally-cached image (not yet fetched, fetching
disabled in Options, or a failed request) falls back to the existing
`swatch_for_card()` color-fill placeholder — the same fallback regardless
of *why* the image is missing.

**API etiquette — applies to every network call, bulk or per-card,
metadata or image:**
- **Off by default, opt-in per feature, not one global switch.** Bulk
  download, incremental card fetch, and image fetch are each their own
  opt-in (Options > Online is the intended home — see
  `options_dialog.py`'s existing "Enable online mode" page, which this
  refines from one checkbox into per-feature toggles), each shown a
  warning about Scryfall's fair-use/traffic expectations before first
  enabling.
- **Throttled by a real, non-zero floor** — Scryfall's own published API
  etiquette asks for roughly 50–100ms between requests; the app's
  request queue should serialize calls with at least that gap rather
  than firing concurrently, matching the "don't strain Scryfall"
  requirement with an actual number instead of just intent.
- **Every request identifies itself** — a descriptive `User-Agent` plus
  `Accept: application/json`, per Scryfall's API guidelines, not a bare
  default HTTP client string.
- **Runs off the Qt GUI thread** — the same `QThreadPool` background-
  worker pattern `data_management_dialog.py` already established for
  local `os.stat()`/folder-size reads (`_StatWorker`/`_FolderSizeWorker`)
  extends to network calls too, so a slow or rate-limited request can
  never freeze the window.
- **Per-request error handling, batch-level restartability.** A single
  failure (network error, a genuinely-removed card returning 404, a 429)
  doesn't abort a whole batch job — a bulk fetch/download job tracks its
  own remaining work list, and RELAUNCHING it (after a crash, a closed
  app, or an explicit retry) resumes by re-checking what's still
  missing, not by redoing what already succeeded. A 429 specifically
  respects the response's `Retry-After` header rather than just falling
  back to the fixed default delay.

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
See "Data & API architecture" above for the full design (bulk-import
pipeline, incremental fetch, migrations, image storage layout, API
etiquette) — bullets below are status only.
- Mock in-memory data (`mock_data.py`) — **Done** (stand-in)
- Data Management dialog UI (Metadata/Images/Decks&Tags tabs, real Browse
  + async stat/folder-size) — **Partial** (no download/parse/persist
  pipeline)
- Real Scryfall bulk-JSON → SQLite import (+ rebuild-from-fresh-snapshot
  path) — **TODO**
- Incremental per-set/per-card API fetch, merged by Scryfall ID — **TODO**
- Schema versioning + migration scripts — **TODO**
- Structured local card-image storage (fetch-if-missing, reuse otherwise)
  + optional live-API fetch mode — **TODO**
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
  display-scale setting as a starting default) — **N/A, resolved by
  investigation rather than by building it**: Qt6 (PySide6) performs
  mandatory automatic high-DPI scaling that already matches the OS's own
  display-scale setting before this app's code ever runs, so there is no
  separate OS-scale reading for `ui_scale`/`text_scale` to seed from
  without risking double-scaling on top of what Qt already applied. A
  real attempt (reading `QScreen.logicalDotsPerInch()`) was built,
  verified against a real Windows 10 + 125%-scale machine, found to read
  back the normalized baseline instead of the real OS setting, and
  retracted — see `scaling.py`'s module docstring and NOTES.md's
  "Scaling infrastructure" entry for the full reasoning. `ui_scale`/
  `text_scale` correctly start at a flat 1.0/1.0 (no additional zoom) —
  they're a user-controlled zoom layered on top of Qt's own OS-scale
  handling, not a mechanism for replicating it.

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
