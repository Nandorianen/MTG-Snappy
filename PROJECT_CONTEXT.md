# Project Context — read this first in a new conversation

This file exists because the working history of *why* things are built the
way they are lived in chat, not in the code. If you're picking this project
up in a fresh conversation, read this, then `README.md` (what's built, how
to run it, how to try each feature) and `NOTES.md` (specific parked
features with design notes already worked out), then the code itself —
every file has a docstring explaining its role and its trickier decisions.

## What this actually is

A local-first, offline-by-default Magic: the Gathering card database and
collection manager, prototyped in Python/PySide6. Originally scoped from
an 8-point outline (below); built iteratively, one feature at a time, with
the user reviewing and giving detailed UI/UX feedback after almost every
round. Nothing here is production code — it's a UI/UX prototype meant to
get the interaction design right before the real data layer exists.

## The original vision (from the very first ask, paraphrased)

1. **Entirely offline by default.** Local JSON + SQLite database, images
   manually downloaded once (configurable: all sets or specific
   releases), updated manually thereafter. An OPTIONAL mode exists to
   fetch images live via API instead of storing them locally (with only
   short-lived caching) — a user-facing toggle, not an either/or
   architecture decision.
2. **UX is a first-class goal**, not just visual polish: configurability,
   full keyboard control, hotkeys throughout, image enlarge-on-hover,
   mouse-wheel print switching. This is *why* so much of the work so far
   has been interaction-detail passes (alignment, focus behavior,
   keyboard parity) rather than breadth. **Emerging corollary, flagged
   explicitly by the user but not yet acted on**: this UX-first goal
   also implies the UI should work across variable text scaling and DPI
   settings, not just look right at one fixed window size on one
   reference machine — see NOTES.md's "variable text scaling & DPI"
   entry.
3. **A unified master card database**: id, name, print editions, image
   ids/links, oracle text, rulings, mana cost, types, keywords, etc. —
   this is the eventual real Scryfall-backed table `mock_data.py` stands
   in for.
4. **A derived, structured filter/keyword database** — e.g. filtering by
   the literal keyword ability "menace" as parsed data, not a text
   search for the substring "menace". **Not built yet** — keywords exist
   as a field on mock cards but aren't surfaced/filterable in the UI.
   Would need real Scryfall keyword data plus a dedicated filter UI.
5. **A tag database**: user-defined tags in a tree, where a card can
   carry a broad parent tag ("Removal"), a specific child tag
   ("Destroy"), both, or a child without its parent — independently.
   **Built**: `tree_pane.py` (generic tree CRUD) + `tag_tree.py` (the Tag
   Database tab) + `tag_assignments.py` (card→tag-id store) +
   `tag_apply_dialog.py` (right-click a card, check tags, apply to the
   whole selection). Both folders AND leaves are checkable/assignable —
   confirmed against the original wording, this was a real design
   decision, not an assumption.
6. **Arbitrary user collections**: owned/wishlist tracking with per-print
   granularity, and decks built the same way. **Partially built**: see
   "Current status" below — the Wishlist/Inventory split was
   deliberately reworked (see next section); Deck Viewer has the
   tree/folder UI but no real per-deck card contents yet.
7. **Export/import compatible with other tools** (e.g. one-button import
   of a deck exported from deckbox.org). **Not built at all yet.**
8. **Snappy and lightweight**, especially with many card images — this is
   *why* the table uses a custom-painted delegate for interactive cells
   instead of one real QWidget per row per column (see `card_table.py`'s
   module docstring for the reasoning), and why grouping/filtering
   re-derives a display list rather than mutating widgets in place.

## A mid-project architectural pivot worth knowing about — and its sequel

Wishlist was originally its own tab, always filtered to "cards you want."
Partway through, we recognized Wishlist and Inventory are really the same
underlying data shape (a card row with a Have count and a Want count),
just different default lenses on it. **Wishlist as a standalone tab was
removed.** It became "All Card Database" (the full browsable catalog,
showing Have + Want for every card) plus Inventory (the same shape,
conceptually filtered to Have > 0). This is why `card_table.py`'s model
has `qty_label`/`cross_qty_label` as per-instance-configurable strings
rather than hardcoded column names.

**The same realization happened again, one round later, about Inventory
itself**: it turned out to be exactly the same pattern as Wishlist had
been — `mock_data.py`'s `get_inventory_cards()` and `get_all_cards()` were
returning identically-shaped data (same source lists) under two different
function names, purely because the mock dataset is too small for the
"Have > 0" filter to ever actually exclude anything. **All Card Database
and Inventory are now ALSO merged, into one tab called "Card Database."**
`get_inventory_cards()` is gone. Isolating "what I own" / "what I want" is
now: click the **Inventory** / **Wishlist** toggle buttons above the table
(new `card_database_view.py` — `CardDatabaseView` wraps a `CardTableView`
with this button row), which is a faster path to the exact same underlying
filter the header's own right-click checklist already offered — right-click
the Have or Want column and uncheck "0" still does the identical thing, and
the two UIs stay in sync in both directions (see `card_database_view.py`'s
module docstring for why that sync has to be bidirectional, not just
button-to-model).

**Pattern worth remembering for next time**: whenever a new "lens" on the
same data starts feeling like it deserves its own tab or its own fetch
function, check whether it's actually just a filter on data that already
exists elsewhere first. Two collapses in a row on the exact same instinct
suggests this is a recurring shape in this app, not a one-off.

**Second pattern worth remembering, from the card detail popup's alignment
work**: whenever two independently-laid-out UI pieces need to visually
agree on something (a column boundary, in that case), check whether they
can share ONE real authority (a shared layout, a shared measured value)
before reaching for a formula to reconcile two separate calculations.
Formulas that check out on paper still went through two failed rounds
before the actual fix — see NOTES.md's new debugging-lesson entry.

## Data source decision

**Scryfall**, not Wizards' official Gatherer (which has no public API).
Scryfall has a bulk-data endpoint (one JSON file, every card/print) that's
the intended real data source. Planned real pipeline, discussed but not
yet built: Scryfall bulk JSON → pandas (one-time flatten/normalize,
`json_normalize` + `to_sql`) → SQLite (persistent, indexed, queried live
at runtime) → JSON again only for export/import interchange. SQLite over
Postgres/MySQL specifically because this is a single-user local desktop
app with no need for a client-server database — the "client-server"
overhead would fight the "snappy and lightweight" goal directly.

## UI framework decision

**PySide6** (Qt), chosen over a web-wrapper approach specifically because
of goal #2 (deep keyboard control, mouse-wheel interactions, hover
behaviors) — those are much more natural with native Qt event handling
than routing everything through a browser/JS bridge. This decision has
held up well; no reason to revisit it.

## Current status — what's real vs. mock vs. missing

**Real, working, tested (headless via `QT_QPA_PLATFORM=offscreen`):**
- Full spreadsheet UI (one merged "Card Database" tab, replacing the old
  separate All Card Database + Inventory tabs — see the architectural
  pivot section above) — sorting, grouping with Deckbox-style sub-headers,
  Edition and Rarity as independent sortable/filterable columns (no
  longer one custom-painted split column — see NOTES.md's "Edition/Rarity
  column split" entry), two per-column filter shapes depending on the
  column (a bounded checklist with an Excel-style search-narrow box for
  Type/Mana color/Edition/Rarity; a typed comparison-or-substring
  EXPRESSION box — `>10`, `<=3.2`, `!=sliver`, a bare partial name — for
  Have/Want/Power/Toughness/Price/Name, where a value checklist doesn't
  scale — see NOTES.md's "filter overhaul" entry), column visibility via
  a standalone Columns dropdown button, Inventory/Wishlist filter-preset
  toggle buttons (two-way synced with the header's own right-click filter
  state, and layered independently on top of any typed Have/Want
  expression), cell-range selection + Ctrl+C copy, Excel-familiar
  keyboard shortcuts (F2 edit, Shift+Space/Ctrl+Space row/column select,
  Ctrl+Home/End, Ctrl+Shift+Arrow).
- Card detail popup — frameless (no window title text; the card's own
  NAME is styled as the Card pane's header instead), a `QGridLayout`-based
  stat area (Type/Mana Cost, Edition/Rarity/Price, Language/Condition/Foil
  all share ONE grid so column widths are structurally guaranteed to
  match across rows, rather than reconstructed per-row — see NOTES.md's
  debugging-lesson entry for why this replaced an earlier, formula-based
  approach that looked correct but wasn't), edition/language/condition/
  foil selectors with an Apply button (styled like CardDatabaseView's
  Inventory/Wishlist toggles) that actually writes back into the card's
  data, legality/rulings panes, a placeholder zoomable image window.
  **Known limitation carried forward from this round**: the stat grid's
  column widths are explicitly LOCKED to a fixed pixel value shortly
  after first layout, which is only safe because the dialog is a fixed-
  size window (900x560) that's never resized — see NOTES.md's "variable
  text scaling & DPI" entry before touching this area on a differently-
  scaled system or if the dialog ever becomes resizable.
- Tag Database tree + tag-apply workflow (right-click → check tags →
  apply to selection, tri-state for mixed selections).
- Deck Viewer tree (folders/decks) — full CRUD, drag-drop, clipboard,
  hotkeys — but **no real per-deck card contents table yet** (its right
  pane is still a placeholder label).
- Collapsible/resizable side panes, shared frameless-dialog base (now
  with an optional `show_title` flag — see `frameless_dialog.py` — so a
  dialog can keep the draggable title-bar/close-button chrome without
  duplicating a title the content pane already shows).

**Entirely mock (`mock_data.py`)**: 9 hand-written cards, not real
Scryfall data. No real card images anywhere — everything visual is a
flat color swatch derived from color identity. No real SQLite — every
"database" in this app is an in-memory Python structure (`mock_data.py`'s
module-level lists/dicts, `tag_assignments.py`'s in-memory dict).

**Not built at all**: real Scryfall/SQLite data layer, real images
(local storage or API-fetch-with-caching), the keyword filter database
(goal #4), export/import (goal #7), a proper search engine/pane, an
options/settings window, theming (light mode / system accent colors),
**variable text scaling / DPI awareness** (newly flagged, see NOTES.md —
related to but distinct from theming; both stem from the same "hardcoded
instead of Qt/OS-derived" pattern), undo/redo, internationalization.

## File map

- `main.py` — entry point, `MainWindow`, tab wiring (`SideNav` + a
  `QStackedWidget` — now 3 tabs: Tag Database, Card Database, Deck
  Viewer), the app-wide QSS stylesheet (now includes `QMenu` styling —
  see NOTES.md if a "the logic runs but nothing visible happens" bug
  shows up again in some other custom-painted/menu-driven widget).
- `mock_data.py` — **the seam**. Every function here is what gets
  reimplemented against real SQLite later; calling code elsewhere
  shouldn't need to change when that happens. Down to one dataset
  function now (`get_all_cards()`) — Inventory's separate function was
  removed as a redundant duplicate (see the architectural-pivot section
  above).
- `card_database_view.py` — `CardDatabaseView`, the wrapper that composes
  a `CardTableView` with the Inventory/Wishlist/Columns button row above
  it. This is what replaced the separate Inventory tab — main.py now
  builds ONE of these instead of two `CardTableView`s.
- `card_table.py` — the spreadsheet: `CardTableModel` (data + sort/group/
  filter logic — checklist-based exclusion via `is_value_excluded()`/
  `set_value_excluded()`, the shared mechanism the header checklist AND
  `CardDatabaseView`'s Inventory/Wishlist buttons both route through,
  PLUS a separate typed-expression mechanism via `set_column_expression()`/
  `get_column_expression()` for `EXPRESSION_COLUMNS` — see NOTES.md's
  "filter overhaul" entry; both can apply to the same column at once, e.g.
  Have/Want), `CardTableHeader` (custom header painting/menus, plus
  `build_show_columns_menu()` — the column-visibility menu, now built
  here but SHOWN from `CardDatabaseView`'s Columns button rather than
  duplicated per-column; Edition and Rarity are now ordinary columns like
  any other, not a custom-painted split section), `CardTableView`
  (selection, copy, hotkeys, right-click tag menu), `_MenuSearchBox` (the
  checklist-column filter-menu search box — Up/Down/Tab/Shift+Tab/Space/
  Enter keyboard handling; see NOTES.md if this ever regresses, the
  debugging journey there is worth reading before re-diagnosing from
  scratch). Biggest, most iterated-on file — read its module docstring.
- `card_detail_popup.py` — `CardDetailDialog`, `StatField` (the
  labeled-stat widget used throughout; clickable dropdown variants hug
  their own content and center via layout stretches rather than CSS
  text-align — see the class docstring if a field's alignment ever looks
  off again), `ImageZoomWidget`. The stat area (Type/Mana Cost,
  Edition/Rarity/Price, Language/Condition/Foil) is built as ONE
  `QGridLayout` in `CardDetailDialog._build_card_pane()`, with column
  widths explicitly locked post-layout via `_lock_column_widths()` — read
  that method's docstring AND NOTES.md's debugging-lesson entry before
  changing this area; two earlier formula-based approaches to the same
  alignment problem looked correct and weren't, for non-obvious reasons.
- `card_popover.py` — the lightweight hover-preview popup (distinct from
  the full detail dialog).
- `frameless_dialog.py` — shared base (`FramelessDialog`) for popups that
  shouldn't show an OS title bar; used by both the card detail popup and
  the tag-apply dialog. `_TitleBar` now takes an optional `show_title`
  flag (default True) — `CardDetailDialog` passes `False` since the
  card's name is shown once, as the Card pane's own header, instead of
  being duplicated into the title bar too.
- `tag_apply_dialog.py` / `tag_assignments.py` — the tag-apply workflow
  and its backing store.
- `tree_pane.py` — the **generic**, reusable folder/item tree (CRUD,
  rename, drag-drop, clipboard, icons, hotkeys). Used by both
  `tag_tree.py` and `deck_viewer.py` — this reuse was deliberate and is
  why building it generically early paid off repeatedly.
- `collapsible_pane.py` — `CollapsibleSplitter`, the resizable/collapsible
  pane wrapper (Tab to toggle, click-elsewhere-collapses, a draggable
  divider with a tall click-to-toggle arrow zone).
- `side_nav.py` — the left tab strip; `TABS` is the single source of
  truth for tab order/labels/shortcuts (Ctrl+1..N are derived from it
  automatically).
- `README.md` — run instructions plus a **rolling changelog** (newest
  round at the top of each file's relevant section).
- `NOTES.md` — **parked features with design specifics already worked
  out** (theming approach, variable text scaling & DPI, search engine
  scope, options/i18n plan, undo/redo open questions, tag hotkey-sequence
  idea, Excel-parity gaps, etc.) — check here before re-deriving a design
  that's already been thought through.

## Suggested roadmap / where to pick up

The agreed build order was: TreePane → Card detail popup → Header
extensions → Tag-apply widget → Search. All but Search are done (plus
several polish rounds beyond the original scope). Reasonable next
directions, roughly in order of how much they'd unblock:

1. **Real data layer** (Scryfall bulk data → SQLite) — the single
   biggest gap between "polished prototype" and "actual usable app."
   Everything currently mock-backed would swap over via `mock_data.py`'s
   existing function seams.
2. **Deck contents** — Deck Viewer's tree exists but decks don't hold
   real cards yet; needs a per-deck `CardTableView` reusing existing
   infrastructure.
3. **Search pane / Ctrl+F** (see NOTES.md for the scope split between
   this and the smaller per-column search boxes already built) —
   `card_database_view.py`'s button row already reserves layout space for
   this via `addStretch()` after the Inventory/Wishlist/Columns buttons,
   so this has a concrete landing spot now rather than an open "where does
   this even go" question.
4. **Variable text scaling & DPI audit** (newly parked, see NOTES.md) —
   not urgent, but worth doing BEFORE much more pixel-precise layout work
   gets built on top of the current fixed-size-window assumptions,
   since retrofitting scale-awareness onto more accumulated fixed-pixel
   code later is more work than designing for it going forward.
5. Everything else in NOTES.md, roughly in the order it's listed there.

## Known testing gaps (verified via headless offscreen Qt — some things can't be)

`QT_QPA_PLATFORM=offscreen` doesn't support real OS keyboard
focus-grabbing, real mouse drag simulation, or actual pixel rendering.
These have been tested as thoroughly as the harness allows (direct method
calls, mocked event dispatch) but **not** via genuine windowed interaction:
- F2 edit-commit/cancel flow (Enter/Escape) on the Qty column.
- Real mouse drag-and-drop reordering in the tag/deck trees (the
  underlying reparenting logic is unit-tested; the actual drag gesture
  isn't).

**Filter-menu search box Up/Down/Tab/Space navigation** was on this list
for a while and took three rounds to actually fix — confirmed working in a
real window now, but the debugging path is worth knowing before touching
this area again: two of the three attempts fixed real (but not THE) bugs
in event-filter routing, and both looked correct in headless testing
because headless tests that manually construct/send events can't
distinguish "the logic works" from "the logic works AND is visible" — the
actual root cause was that `QMenu` had no explicit `::item:selected`
styling in `main.py`'s stylesheet, so a correctly-updating internal
highlight state was rendering with zero visible difference. Headless mode
can verify state changes; it can't verify anything about whether a human
would actually SEE the state change. Full writeup in NOTES.md and
README.md's changelog for this round if this general class of "my code
runs but nothing visibly happens" bug recurs elsewhere.

**Card detail popup alignment bugs (card_detail_popup.py) were a
DIFFERENT failure class worth distinguishing from the one above**: two
formula-based fixes each looked mathematically correct and STILL didn't
fix the visible problem, because headless offscreen Qt CAN actually
render real widget geometry (unlike the "state vs. visibility" gap above)
— the missing step was querying that real geometry
(`widget.geometry()`, `QFontMetrics.boundingRect()`, `.mapTo()`) to check
a pixel-level claim, rather than trusting a derivation that had never
actually been checked against a render. Once real widget positions were
measured this way, the fix (and a second, previously invisible bug in a
coordinate-space assumption) became obvious quickly. **Takeaway for any
future "these two things don't visually line up" bug**: headless Qt CAN
answer this — instantiate the real dialog, call `.show()` +
`app.processEvents()`, and measure actual widget/text positions — don't
rely on re-checking the math alone, even when the math seems airtight.

If something in one of these areas looks subtly wrong when actually run,
start there — it's the area least covered by automated testing so far.
