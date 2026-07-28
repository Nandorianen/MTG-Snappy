# Parked design questions

Things we've deliberately deferred, with enough context to pick back up later.

## Theming: system accent colors + light/dark presets (raised while polishing colors)
TODO, explicitly flagged rather than a quick fix. The current dark theme is
a single hardcoded QSS string (`main.py`'s STYLE_SHEET) with literal hex
colors everywhere -- this is the OPPOSITE of how Qt normally adapts to the
OS: QSS color rules completely override `QPalette`, which is what would
otherwise reflect the OS's accent color and light/dark setting automatically.
The Qt-friendly path, when we get here:
- Stop hardcoding colors in QSS; either don't set a palette at all (let the
  OS/style provide one) or set one derived from `QGuiApplication` theme
  hints, and reference palette ROLES from QSS via the `palette(highlight)`
  / `palette(window)` etc. functions instead of literal hex values -- this
  keeps structural styling (padding, radius, borders) in QSS while colors
  stay OS/theme-driven.
- A real light/dark (and possibly "system") preset switcher belongs in the
  Options window (see the options/i18n TODO above) -- likely 2-3 named
  QPalette presets plus a "follow system" option, with the custom-painted
  bits (SplitDropdownHeader's HEADER_BG, CardPopover, ImageZoomWidget, etc.)
  needing to read from whichever preset/palette is active rather than a
  single hardcoded constant, which is the main reason this is a real
  refactor and not a one-line change.

## Flexible search engine (raised as an explicit TODO)
A proper search pane -- its own view, not just column filters -- covering
multi-field queries (name + type + color + keyword combined), with a
lighter/quicker variant accessible via Ctrl+F as a popup that collapses/
hides non-matching rows in whichever pane has focus (this was actually part
of the ORIGINAL project outline, goal #2, not a new idea). The per-column
filter checklists now have an Excel-style search box to narrow long value
lists (see this round's changes to card_table.py) -- that's a smaller,
separate thing from this: a real search engine needs cross-field queries,
saved searches, and probably its own query-language-ish input, not just
"narrow this one column's checklist."

## Options menu + externalized/translatable strings (raised alongside language selector)
TODO, explicitly flagged as a TODO rather than a quick fix. Shape of it:
- An actual Options/Settings window/dialog is needed once there's more than
  a couple of app-wide preferences (default language, default condition,
  price-source default, etc. -- see the "default add" note below).
- **String externalization**: every user-facing label currently lives
  inline in the Python source (`"Type"`, `"Rarity"`, `"Filter by..."`,
  etc). Add real language support means moving these into per-language
  files -- one file per language, each defaulting to/falling back on the
  English file for any key it doesn't override, rather than one giant
  all-languages file. Worth deciding the file format (JSON? Python dict
  modules? .ts/Qt Linguist format, which has real tooling but more
  ceremony?) before this grows -- retrofitting externalization onto strings
  scattered through a dozen files later is a bigger job than building it in
  as we go from here.
- This should probably happen BEFORE too many more UI strings get written
  inline, since every new hardcoded string is something to migrate later.

## "Have" / "Want" / "In Deck" count columns (raised alongside language/condition)
UPDATE: Have/Want now exist as real columns (dynamically labeled per table)
across both All Card Database and Inventory, and are filterable by exact
value (right-click -> uncheck "0" isolates "cards I own" or "cards I
want"). What's still missing: Deck Viewer doesn't have a real per-deck card
table yet (see deck_viewer.py's placeholder), so there's no "copies in this
deck" column to add alongside Have yet -- that's still pending on building
actual deck contents.

## Default-add behavior + collapsing variants into one row (raised together with the above)
Bigger idea, needs its own design pass:
- New cards added to Inventory/Wishlist/a deck should default to: the
  user's configured language (see Options above), the latest major release
  printing, non-foil, Near Mint -- all themselves configurable defaults.
- By default, a card should show as ONE row even if the user owns several
  different printings/languages/conditions/foil-states of it -- with some
  way to expand/check which specific version(s) they actually have. This is
  a real data-model question (a card "row" becomming a summary over
  potentially several underlying collection-entry rows) that intersects
  with the count-columns idea above and with the eventual real SQLite
  collection schema -- worth designing together with that schema rather
  than bolting onto the current flat per-printing mock rows.

## Reticle-select zoom on the card image (raised during detail-popup feedback)
Idea: let the user drag out a rectangle ("reticle") directly on the enlarged
card image and zoom specifically into that region, rather than only the
current whole-image wheel-zoom. Ctrl+click was suggested as the modifier to
distinguish "start a reticle selection" from "drag the window around" (plain
click+drag currently means "move the window"). Not designed yet -- open
questions when we get to it:
- Does the reticle zoom replace the current whole-image zoom, or layer on
  top of it (zoom into a region of an already-zoomed image)?
- Once real card images (not color placeholders) exist, is this pixel-crop
  based (crop + rescale a QPixmap region) or done via a transform on the
  view (translate + scale)? The former is simpler; the latter generalizes
  better if we ever want smooth pan/zoom animation.
- Should the reticle rectangle stay visible as an overlay while dragging it
  out (typical UX), and what cancels it (Escape, releasing outside the image)?

## Undo/redo + save model (raised during TreePane feedback pass)
Not designed yet. Rough shape of the open questions, for when we do:

- **In-memory edit history for Ctrl+Z/Ctrl+Y**, scoped to... what? Just tree
  edits (rename/move/delete/create)? Also table edits (checkbox toggles,
  qty changes) once those exist? A single global undo stack across the
  whole app is simpler for the user to reason about; per-view stacks are
  easier to implement in isolation but "undo" would need to mean "undo in
  whichever view has focus," which may or may not match what a user expects.
- **Explicit save vs. autosave.** You floated "only commit to files when the
  user explicitly saves" -- that implies an in-memory "dirty" working copy
  layered over whatever's on disk (or in SQLite), which has real implications
  for how the data layer gets designed once we build it (goal from the
  original outline: local JSON + SQLite). Worth deciding BEFORE the real
  database layer is built, not after, since retrofitting "everything is
  actually a diff against a committed state" onto an already-built direct-
  write data layer is a lot more painful than designing for it up front.
- **Auto-backup of database files** -- periodic snapshot/copy, probably
  independent of the undo/redo question above (backup protects against
  file corruption/loss; undo/redo protects against user mistakes mid-session).

Revisit once the real data layer (SQLite decks/tags/collection tables) is
underway -- this will shape how that layer is built, not just sit on top of it.
