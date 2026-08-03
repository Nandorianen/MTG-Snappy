# Parked design questions

Things we've deliberately deferred, with enough context to pick back up later.

## Revisit: fixed-pixel UI assumptions vs. variable text scaling & DPI (raised explicitly this round, NOT addressed)
Flagged by the user as an important future direction after the card detail
popup's Type-column alignment work — explicitly NOT something to solve
right now, but important enough to not lose track of. The concern, in the
user's own words: fixed window sizes and pixel-precise layout assumptions
aren't viable across all systems and configurations (different default
DPI, OS-level accessibility text-scaling settings, different default
fonts/font substitution across platforms).

**Where this is currently baked in, concretely:**
- `card_detail_popup.py`'s `CardDetailDialog` is a genuinely fixed-size
  window (`resize(900, 560)` called once in `__init__`, never resized
  by the user — frameless windows lose native edge-drag resize, a
  documented limitation in `frameless_dialog.py` that was deliberately
  not solved). Everything about its current stat-grid layout assumes this.
- The just-shipped column-width-locking fix
  (`CardDetailDialog._lock_column_widths()`) is EXPLICITLY justified by
  "this dialog never resizes" — it measures the real column width ONCE,
  after the first layout pass, and freezes it there permanently via
  matching `setColumnMinimumWidth()`/`setMaximumWidth()` calls. If the
  window ever became resizable, or if the OS/user's font-scaling setting
  changed AFTER that lock ran, the columns would stay frozen at whatever
  was correct for the very first render and never adapt — this is a
  real, deliberate trade-off made to fix an immediate bug, not an
  oversight, but it's exactly the kind of fixed-pixel assumption that
  needs revisiting before real scaling support exists.
- More broadly, several other places assume roughly-consistent text
  metrics across fonts/platforms/DPI without an adaptation mechanism:
  `StatField`'s eliding/wrapping width targets, the Legality pane's
  `_legality_column_width()` (sized to the widest string THIS font
  produces, which changes under a different font/scale), and likely
  `card_table.py`'s column widths too (not audited this round).
- Related to the ALREADY-parked "Theming: system accent colors +
  light/dark presets" entry below — that entry critiques the app's
  hardcoded QSS hex colors as "the OPPOSITE of how Qt normally adapts to
  the OS" (QSS color rules override `QPalette`, which would otherwise
  reflect OS theme automatically). The exact same critique applies here,
  just for SIZE instead of color: hardcoded pixel dimensions are the
  opposite of letting Qt's own font-metric-derived sizing adapt
  automatically. Worth treating as ONE audit pass covering both axes
  when this gets picked up, since they're the same underlying pattern
  (assuming a specific rendering environment instead of querying it) —
  not two unrelated pieces of work.

**Open questions for when this gets designed for real:**
- Does `CardDetailDialog` become a genuinely resizable window first
  (reversing the "fixed size for now" decision in `frameless_dialog.py`),
  or does it stay fixed-size but re-measure/re-lock its column widths
  reactively (e.g. a `resizeEvent` handler re-running
  `_lock_column_widths()`, or re-running it if a Qt
  `QGuiApplication.fontChanged`-style signal ever fires)? The two are
  different amounts of work and probably should be decided together,
  not layered on independently.
- Should `StatField`'s hardcoded pixel constants (`CAPTION_VALUE_SPACING`,
  `STAT_ROW_SPACING`, `ROW_COLUMN_SPACING`, `FIELD_INNER_MARGIN`) become
  DPI-aware (e.g. derived from `QFontMetrics` or a scale factor) rather
  than literal pixel counts? This is the same category of question
  `card_table.py`'s and `tree_pane.py`'s various fixed pixel dimensions
  would eventually need answered too — worth answering it once, as a
  reusable pattern, rather than per-widget.
- Does this intersect with the parked Options/Settings window
  (see below) — e.g. a user-facing "text size" preference independent of
  the OS's own scaling — or is OS-level DPI/accessibility scaling the
  only axis that actually matters for a desktop app like this?

## Debugging lesson: alignment across independent layouts needs a shared authority, not a better formula (from the card detail popup Type-column saga)
Not a parked TODO — a worked example worth keeping, same spirit as the
existing "the logic runs but nothing visibly happens" lesson below, but a
distinct failure class. Full blow-by-blow (three failed attempts before
the real fix) lives in README.md's changelog entry for this round; this
entry is the distilled, generalizable version for whenever a similar bug
shows up somewhere else in the app.

**Symptom shape**: two structurally different layouts (in this case, two
independent `QHBoxLayout`s with different column counts/stretch ratios)
each needed to agree on where "column 1" is, so a widget in one could
visually align with a widget in the other. Every attempt to compute that
agreement via a formula — first a naive one, then a careful analytical
derivation that checked out exactly on paper — LOOKED correct and still
wasn't, because each formula depended on an assumption (Qt's actual
default spacing value, or which coordinate space a margin was measured
relative to) that was never actually verified against a real render.

**What actually worked**: two changes together, not one. (1) Stop trying
to make two independent layouts agree via calculation — restructure so
there's only ONE shared layout (a `QGridLayout`) whose column widths are a
single authoritative number by construction, not something reconstructed
per-row. (2) Actually instantiate the dialog headlessly
(`QT_QPA_PLATFORM=offscreen`) and measure REAL rendered pixel positions
(`QFontMetrics.boundingRect()` for text-aware centers, `.mapTo()` for
cross-widget coordinate comparison) rather than trusting a derivation,
however carefully re-checked. That measurement step caught a genuinely
separate bug — a margin being applied relative to the wrong coordinate
origin — that no amount of re-deriving the same algebra would have found,
since the algebra itself was internally consistent; the actual error was
in an unexamined assumption the algebra never touched.

**General takeaway**: when a bug is specifically about two things needing
to align, and a formula-based fix doesn't visibly work even though it
checks out on paper, stop refining the formula and ask whether the two
things have any single shared source of truth they could both read from
instead (a shared parent layout, a shared measured widget, a shared
constant) — and verify any fix candidate against real rendered geometry,
not just re-checked math, before concluding it worked.

**Narrower, reusable gotcha from the same saga**: `setMaximumWidth()` on a
widget does not reliably stop `QGridLayout` from growing that widget's
COLUMN based on the widget's own uncapped `minimumSizeHint()` — a
difference from `QHBoxLayout`, where each row solves its own width
independently and has nothing to reconcile against another row's content.
If a grid column mysteriously grows elsewhere in this app later despite an
apparent per-widget max-width cap, this is the mechanism to suspect;
locking BOTH `setColumnMinimumWidth()` and `setMaximumWidth()` to the
identical value (rather than capping only the widget) is what actually
fixed it.

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

**UPDATE (this round)**: a related but distinct lesson showed up in the
card detail popup's alignment work — see the new entry above. That
saga's headless tests DID render real pixels (unlike this one, which was
purely about state vs. visibility) and still needed actual geometry
measurement to catch the bug, because the failure was in a coordinate-
space assumption, not a rendering/visibility gap. Different failure
class, same underlying moral: don't trust a test that didn't actually
check the specific thing the bug turned out to be about.

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
**See the new "variable text scaling & DPI" entry above** -- the same
critique applies to hardcoded pixel dimensions, not just colors; worth
treating as one combined audit pass rather than two separate efforts.
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
**UPDATE: the window shell now exists (`options_dialog.py`, `OptionsDialog`)
-- reachable via File > Options... or Ctrl+, -- but it's UI ONLY.** No
control reads from or writes to a real settings store; every value shown is
just a sensible-looking default. Still fully TODO below:
- **No persistence layer at all.** Apply currently just flashes "Applied ✓"
  (matching CardDetailDialog's Apply-button feedback pattern) without
  actually applying anything anywhere. Needs a real settings store --
  probably a single JSON/INI file rather than SQLite, since app-wide
  preferences aren't really "collection data" -- plus a decision on where it
  lives (same folder as the future local data folder the Advanced tab
  already has a placeholder field for?).
- **Nothing on the page is wired to app behavior yet**: the UI-scale slider
  doesn't scale anything (this is the literal "user-facing text size
  preference independent of OS scaling" NOTES.md's DPI entry already asked
  about -- the control exists now, the effect doesn't), the accent-color
  swatches don't repaint `main.py`'s STYLE_SHEET, the language combo
  doesn't retranslate anything, the Input tab's keybinding table is
  read-only display only (no rebinding), etc.
- The tab strip is a `QListWidget` (Up/Down/Home/End/type-ahead navigation
  free from Qt) rather than `SideNav`-style buttons, and tab-switching also
  works via Ctrl+Tab/Ctrl+Shift+Tab from anywhere in the dialog -- see
  `options_dialog.py`'s module docstring for the reasoning, which follows
  the same "use the native widget for what Qt already does correctly"
  principle `tree_pane.py` established for QTreeWidget.
- The remaining shape below is unchanged -- still needed regardless of the
  new shell:
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

## Data Management window (new this round) -- the real first step toward goals #1/#3/#4/#7
**New `data_management_dialog.py`, `DataManagementDialog`** -- reachable via
File > Data Management... or Ctrl+M. Same UI-shell status as Options: looks
and behaves correctly, but no download/parse/persistence pipeline exists
yet. Three tabs: Metadata (Scryfall's bulk-data JSON exports -- Oracle
Cards, Unique Artwork, Default Cards, All Cards, Rulings, plus the separate
Tagger-project Art Tags/Oracle Tags exports), Card Images (a target folder,
per-size/crop checkboxes, print language, edition picker, Download button),
Decks & Tags (this app's own local save data -- same row layout as
Metadata, structurally, but nothing here comes from Scryfall).
- **Browse buttons are genuinely real**, not mocked: they open actual
  `QFileDialog`s, and picking a real file/folder reads its REAL size and
  modified time straight off disk (`os.stat`/`os.walk`). Nothing risky
  about that -- it's a local filesystem read, no network, no writes --
  so there was no reason to fake it just because the rest of the dialog
  is a showcase.
- **Update/Locate/Download buttons are NOT real** -- there's no download
  pipeline or settings store to act on yet. They give the same transient
  "working" feedback CardDetailDialog's Apply button and OptionsDialog's
  Apply button already use, rather than doing nothing visible at all.
- **Extracted `dialog_common.py`** out of `options_dialog.py` once this
  became the SECOND dialog wanting the identical "vertical tab list +
  stacked pages + Ctrl+Tab-from-anywhere" chrome -- `VerticalTabDialog` is
  now the shared base both `OptionsDialog` and `DataManagementDialog`
  subclass (siblings, not a hierarchy -- see that module's docstring for
  why one doesn't just inherit the other). Any future dialog wanting this
  same shape should subclass it too rather than re-copying the wiring a
  third time.
- **The edition-picker menu (Card Images tab) needed NONE of
  `card_table.py`'s `_MenuSearchBox` keyboard machinery** -- worth noting
  explicitly since it'd be easy to assume every checklist-style QMenu in
  this app needs that treatment. It doesn't: that machinery exists only
  because a search box embedded in the menu competes with QMenu's own
  arrow-key handling for focus. A plain checklist menu with no embedded
  widget (like this one) already gets correct Up/Down/Space/Enter
  navigation from Qt with zero extra code.
- **First use of `QScrollArea` in this app** (all three tabs use one, given
  how many sections/controls each page holds). Pre-empted the "unstyled
  native widget looks wrong once any custom QSS exists" bug class this
  project already hit once with `QMenu` (see the "logic runs but nothing
  visibly happens" debugging-lesson entry above) by adding explicit
  `QScrollBar` styling to `main.py`'s global stylesheet up front, rather
  than waiting to rediscover the same lesson a second time.
- Dummy edition list (`EDITION_OPTIONS` in `data_management_dialog.py`)
  deliberately reuses the same set codes already scattered through
  `mock_data.py` (LEA, FUT, DGM, ZEN, AVR, ISD, NPH, 2XM, DMR) rather than
  inventing a new arbitrary list, so the placeholder data across the app
  stays internally consistent until real Scryfall set data replaces it.

## Performance fix: settings-dialog open delay (raised as "Options/Data Management feel slow to open")
Two real, measured fixes, both now in `dialog_common.py`/`main.py` --
worth knowing about since they change how any FUTURE `VerticalTabDialog`
subclass should be written:
- **Pages are now built LAZILY.** `VerticalTabDialog` used to build every
  tab's full widget tree immediately in `__init__`, before the window
  could even appear -- for Options' 6 tabs, that's 5 pages' worth of
  work paid for on every single open regardless of whether they're ever
  looked at. Subclasses now implement `page_factories()` (a list of
  *callables*, not built widgets) instead of `build_pages()`; each tab
  starts as an empty placeholder and only gets built the first time it's
  actually selected. Headless timing: OptionsDialog's steady-state
  construction dropped from ~30ms to ~7ms once only 1 of 6 pages had to
  be built up front (measured via `time.perf_counter()` around
  construction, not wall-clock guessing).
- **`main.py` now caches and reuses both dialog instances** (`
  self._options_dialog` / `self._data_management_dialog`, lazily created
  once, reused via `.exec()` on every subsequent open) instead of
  constructing a brand-new dialog object from scratch on every single
  menu click. Neither dialog holds state that needs a fresh start on
  reopen, so there's no correctness reason to rebuild.
- **Still unresolved / worth re-testing for**: headless (offscreen)
  construction timing never showed anything close to the reported
  0.5-1s delay even BEFORE these fixes (worst case ~250ms on the very
  first-ever dialog construction, ~30-70ms steady state) -- meaning
  pure widget/layout construction was probably never the dominant cost.
  If a real, on-screen delay persists after these two fixes (especially
  if it's roughly the SAME on every open, not just the first), the next
  place to look is something platform/window-manager-specific to
  `Qt.FramelessWindowHint` top-level windows (compositor negotiation,
  show-animation cost) rather than anything in this app's own widget
  code -- worth testing by temporarily removing the frameless hint from
  `FramelessDialog` and seeing whether a normal-decorated QDialog opens
  instantly by comparison.

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
