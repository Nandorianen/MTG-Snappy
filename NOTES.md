# Parked design questions

Things we've deliberately deferred, with enough context to pick back up later.

## Debugging lesson: "the logic runs but nothing visibly happens" (from the filter-menu keyboard-nav fix)
Not a parked TODO -- a worked example worth keeping, because it took three
real attempts to actually fix and the first two were each individually
reasonable-looking dead ends.

**Symptom**: `_MenuSearchBox` (the search box embedded via `QWidgetAction`
in every filterable column's right-click menu, `card_table.py`) had
Up/Down arrow-key navigation that visibly did nothing at all in a real
window -- no highlight moved, Space didn't toggle anything, focus never
left the box.

**Attempt 1**: hypothesized `QMenu`'s own internal arrow-key handling was
intercepting the keys before `_MenuSearchBox.keyPressEvent()` ever ran --
a real, documented category of Qt bug (`collapsible_pane.py`'s Tab-
interception fix is exactly this same shape). Moved the handling into an
app-level `eventFilter`. Verified via a headless test that called
`app.sendEvent(box, ev)` directly and confirmed `activeAction()` moved
correctly. **Still didn't work in the real window.** The test was flawed:
forcing the event's receiver via `sendEvent(box, ...)` never actually
exercised the real ambiguity of Qt's popup keyboard-grab routing -- it
proved the LOGIC was correct, not that it would ever actually GET CALLED
for real popup-routed events.

**Attempt 2**: hypothesized Qt's real popup routing doesn't necessarily
report the search box itself as the event filter's `watched` parameter
(unlike the artificial `sendEvent(box, ...)` test). Dropped the
`watched is self` condition entirely, reacting to the key code alone
instead. Verified this time with a test that deliberately passed an
UNRELATED decoy object as `watched`, proving the broadened filter no
longer depended on receiver identity. **Still didn't work.**

**The actual fix**: reframed the symptom instead of the mechanism. "Arrow
keys visibly do nothing" does NOT mean "the events aren't arriving" --
it's equally consistent with "the events arrive, the internal state
updates correctly, and there's simply no VISIBLE difference to see."
`main.py`'s global stylesheet had never included a single `QMenu` rule.
Once ANY custom QSS is applied to a Qt application, the style engine
stops relying on the native platform style's automatic hover/selected
rendering for widgets not explicitly covered -- so `QMenu.setActiveAction()`
may have been working correctly all along, just invisibly. Adding explicit
`QMenu` / `QMenu::item:selected` styling (reusing the app's existing
`#3d6a8f` selection color) was the actual fix. Separately, "Space doesn't
toggle" turned out to be a real, distinct gap rather than a routing bug:
real `QMenu` only handles Space when the MENU ITSELF holds actual keyboard
focus, which this design deliberately never grants (focus stays on the
search box the whole time, so typing keeps narrowing the list) -- so
Space needed its own explicit handler, scoped to only fire once an action
is already highlighted (so a space typed as part of "Lightly Played"
still works before any arrow-navigation has happened).

**The general lesson**: headless/offscreen Qt testing (`QT_QPA_PLATFORM=
offscreen`, used throughout this project's testing) can verify that STATE
changed correctly. It cannot verify whether a human would actually SEE
that state change, because it never renders real pixels. When a fix looks
provably correct in a headless test but a person reports "still doesn't
work" in the real app, seriously consider whether the bug is actually in
RENDERING/VISIBILITY rather than in the LOGIC/ROUTING the test was capable
of checking -- especially anywhere a custom global stylesheet is in play
(this app's `main.py` applies one to the whole `QApplication`), since that
specifically disables automatic native-style state rendering for anything
not explicitly re-declared in QSS.

## Full Excel keyboard parity (raised alongside the F2/Shift+Space/etc additions)
This round added F2 (edit Qty), Shift+Space (select row), Ctrl+Space
(select column), Ctrl+Home/End (jump to first/last cell), and Ctrl+Shift+
Arrow (extend selection to an edge). Still missing, for whenever more
Excel-familiarity is wanted: Ctrl+Arrow (jump, WITHOUT extending, to the
edge of a contiguous block of non-empty cells -- what's implemented now
always jumps to the table's actual edge, not the nearest "gap" in the
data, which needs scanning logic this doesn't have yet); Tab/Enter moving
the current cell after committing an edit; a formula-bar-style edit
experience; and Ctrl+Z/Y (tracked separately under the undo/redo note
below, since cell edits should probably feed the same history as
everything else eventually).

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
  bits (SplitDropdownHeader's HEADER_BG, CardPopover, ImageZoomWidget, and
  now also the QMenu / QMenu::item:selected rules added this round to fix
  filter-menu keyboard-nav visibility -- easy to forget since it's plain
  QSS rather than a custom paintEvent, but it's exactly as hardcoded as
  everything else on this list) needing to read from whichever
  preset/palette is active rather than a single hardcoded constant, which
  is the main reason this is a real refactor and not a one-line change.

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
UPDATE: this now has a concrete home. `card_database_view.py`'s
`CardDatabaseView` puts a button row (Inventory/Wishlist/Columns) above
the Card Database table, with a deliberate `addStretch()` after those
three buttons reserving the rest of that row -- that's where the Ctrl+F
popup trigger belongs when this gets built, rather than an open "does
this live inside or outside the table" question.

## Excel keyboard parity: what's still missing (raised alongside this round's shortcuts)
Added this round: F2 edit mode (Qty column, now genuinely editable),
Shift+Space (select row), Ctrl+Space (select column), Ctrl+Home/End (jump
to first/last cell), Ctrl+Shift+Arrow (extend selection to an edge).
Known gaps for a future pass, in rough priority order:
- Ctrl+Shift+Arrow currently jumps to the table's actual edge, not Excel's
  real behavior (jump to the edge of the current contiguous non-empty
  block, stopping at the first gap) -- needs data-scanning logic.
- Tab/Shift+Tab to move the edit cursor between cells while editing (F2
  mode currently only supports Enter/Escape to end editing).
- Ctrl+Arrow (without Shift) to jump without extending selection.
- Delete key to clear editable cell contents (currently only Qty is
  editable at all, so this is a small scope once more columns are).
- Fill-handle / Ctrl+D "fill down" style operations -- much bigger scope,
  probably its own feature rather than a keyboard-shortcut afterthought.

## Tag-apply widget: search/filter (raised as an explicit TODO)
The tag tree in TagApplyDialog can get long once a real tag hierarchy
exists. Needs the same kind of search box the column filter menus now have
(narrows what's visible as you type) -- probably simpler than the header
version since there's no "excluded values" concept here, just show/hide
tree items (and their ancestor folders, so a matching deeply-nested tag
doesn't end up hidden because its parent got hidden).

## Tag-apply widget: user-assignable hotkey sequences (raised as an explicit TODO)
Idea, described in detail: let the user assign a single letter to any tag,
unique only among its SIBLINGS at the same tree depth (not globally unique)
-- then typing a sequence of those letters navigates straight to a tag
without touching the mouse. Given example: a→Artifacts, c→Creature,
d→Destroy under one branch, so "a c c" reaches "Removal for Artifact" and
"a c d" reaches "Removal (Enchantment)" (per the user's own worked example),
while "c c c" reaches an entirely different tag "Fetch Any Card" down a
different branch, since letters only need to be unique among siblings at
each level, not across the whole tree. Open questions for when we design
this: where do the assignments live (per-tag field alongside icon_color?),
what happens on a collision when the user tries to assign an already-used
sibling letter, and how does the UI show "type a letter to jump" (small
letter badges next to each item, probably, activated by some modifier or
a distinct navigation mode toggle).

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
