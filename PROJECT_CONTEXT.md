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
   keyboard parity) rather than breadth.
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

## A mid-project architectural pivot worth knowing about

Wishlist was originally its own tab, always filtered to "cards you want."
Partway through, we recognized Wishlist and Inventory are really the same
underlying data shape (a card row with a Have count and a Want count),
just different default lenses on it. **Wishlist as a standalone tab was
removed.** It's now "All Card Database" (the full browsable catalog,
showing Have + Want for every card) plus Inventory (the same shape,
conceptually filtered to Have > 0 — though in the current tiny mock
dataset every card happens to have some Have count, so this distinction
isn't visually obvious yet). Isolating "what I want" is just: right-click
the Want column, uncheck "0". This is why `card_table.py`'s model has
`qty_label`/`cross_qty_label` as per-instance-configurable strings rather
than hardcoded column names.

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
- Full spreadsheet UI (All Card Database, Inventory) — sorting, grouping
  with Deckbox-style sub-headers, per-column filtering with an
  Excel-style search-narrow box, column visibility, cell-range
  selection + Ctrl+C copy, Excel-familiar keyboard shortcuts (F2 edit,
  Shift+Space/Ctrl+Space row/column select, Ctrl+Home/End,
  Ctrl+Shift+Arrow).
- Card detail popup — frameless, edition/language/condition/foil
  selectors with an Apply-to-Inventory button that actually writes back
  into the card's data, legality/rulings panes, a placeholder zoomable
  image window.
- Tag Database tree + tag-apply workflow (right-click → check tags →
  apply to selection, tri-state for mixed selections).
- Deck Viewer tree (folders/decks) — full CRUD, drag-drop, clipboard,
  hotkeys — but **no real per-deck card contents table yet** (its right
  pane is still a placeholder label).
- Collapsible/resizable side panes, shared frameless-dialog base.

**Entirely mock (`mock_data.py`)**: 9 hand-written cards, not real
Scryfall data. No real card images anywhere — everything visual is a
flat color swatch derived from color identity. No real SQLite — every
"database" in this app is an in-memory Python structure (`mock_data.py`'s
module-level lists/dicts, `tag_assignments.py`'s in-memory dict).

**Not built at all**: real Scryfall/SQLite data layer, real images
(local storage or API-fetch-with-caching), the keyword filter database
(goal #4), export/import (goal #7), a proper search engine/pane, an
options/settings window, theming (light mode / system accent colors),
undo/redo, internationalization.

## File map

- `main.py` — entry point, `MainWindow`, tab wiring (`SideNav` + a
  `QStackedWidget`), the app-wide QSS stylesheet.
- `mock_data.py` — **the seam**. Every function here is what gets
  reimplemented against real SQLite later; calling code elsewhere
  shouldn't need to change when that happens.
- `card_table.py` — the spreadsheet: `CardTableModel` (data + sort/group/
  filter logic), `SplitDropdownHeader` (custom header painting/menus),
  `CardTableView` (selection, copy, hotkeys, right-click tag menu).
  Biggest, most iterated-on file — read its module docstring.
- `card_detail_popup.py` — `CardDetailDialog`, `StatField` (the
  fixed-width/wrapping/centering label+dropdown widget used throughout),
  `ImageZoomWidget`.
- `card_popover.py` — the lightweight hover-preview popup (distinct from
  the full detail dialog).
- `frameless_dialog.py` — shared base (`FramelessDialog`) for popups that
  shouldn't show an OS title bar; used by both the card detail popup and
  the tag-apply dialog.
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
  out** (theming approach, search engine scope, options/i18n plan,
  undo/redo open questions, tag hotkey-sequence idea, Excel-parity gaps,
  etc.) — check here before re-deriving a design that's already been
  thought through.

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
   this and the smaller per-column search boxes already built).
4. Everything else in NOTES.md, roughly in the order it's listed there.

## Known testing gaps (verified via headless offscreen Qt — some things can't be)

`QT_QPA_PLATFORM=offscreen` doesn't support real OS keyboard
focus-grabbing or real mouse drag simulation. These have been tested as
thoroughly as the harness allows (direct method calls, mocked event
dispatch) but **not** via genuine windowed interaction:
- Filter-menu search box Up/Down navigation in a real window.
- F2 edit-commit/cancel flow (Enter/Escape) on the Qty column.
- Real mouse drag-and-drop reordering in the tag/deck trees (the
  underlying reparenting logic is unit-tested; the actual drag gesture
  isn't).

If something in one of these areas looks subtly wrong when actually run,
start there — it's the area least covered by automated testing so far.
