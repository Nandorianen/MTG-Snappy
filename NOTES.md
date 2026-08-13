# Design notes: parked features + debugging lessons

Organized by topic, newest understanding first within each entry. See
PROJECT_CONTEXT.md's Roadmap for a status-tagged index of everything here.

## Card Database filtering

**Two filter shapes, by design, not inconsistency.** Type, Mana Cost's
color, Edition, and Rarity are genuinely small bounded sets → checklist
with an Excel-style search-narrow box. Have/Want (unbounded int), Price
(continuous), Name (thousands of cards), Power/Toughness (literal-number
checklist was never useful, plus "*" for variable P/T) → a single typed
EXPRESSION box instead (`CardTableModel._matches_expression`):
- Leading `>`, `>=`, `<`, `<=`, `!=` = comparison; anything else = a bare
  substring search.
- Numeric vs. text is auto-detected **per comparison** (does the operand
  parse as a number?), not chosen by the user or declared per-column. A
  card that isn't numeric for that column (Power's `*`) simply never
  matches a numeric comparison — never coerces to 0.
- `!=` in text mode means "does not contain," not "isn't exactly equal."
- Blank box = no filter.

**Type filtering is WORD-based** (`_type_words`, `type_excluded_words`),
not routed through `_type_category()` (which is for GROUPING and
deliberately collapses a type line to one bucket, stripping supertypes).
Filtering needs a card to match on ANY of its type words independently —
same set-membership-exclusion shape Mana Cost's color filter already uses
for multicolor cards. Type's search box ALSO applies a typed EXPRESSION
against the card's full raw type line on Enter (reusing
`_matches_expression`), layered on top of the word checklist — this is
what lets `type~bird` find a subtype past the em dash that the checklist
can never offer as a checkbox.

**Edition mini-widget (TODO, not built)**: today's Edition filter/picker
is a flat checklist — fine for 9 mock sets, not for a real Scryfall list of
thousands. Wanted: a widget where editions are grouped into collapsed
folders (block/era) with each edition listed by name/code/year, an
edition OR a whole folder selectable. Two call sites, one shared widget:
the table's Edition column filter, and `data_management_dialog.py`'s Card
Images edition picker (currently `EDITION_OPTIONS`, a flat placeholder
list reusing mock_data.py's set codes for consistency). Open questions:
where the block/era grouping data comes from (Scryfall's `set_type`,
once real data exists), whether folder selection means "everything
inside" or an additional filter tier, and whether this becomes its own
reusable file given two call sites from day one.

**Rarity belongs to a PRINTING, not the card in the abstract** — the same
card name can be common in one edition, rare in a reprint. Code that
reads/writes rarity should always do so alongside a specific edition/
print. `card_detail_popup.py`'s edition switcher already gets this right
(`CARD_PRINTS`/`get_card_prints` — picking a print updates edition and
rarity together, from the same print record) — the pattern to preserve.

## Card Database keyboard navigation

Headers are keyboard-focusable independently of Qt's real focus
(`CardTableHeader._focused_column`) — reachable via Alt+Shift+Up/Down from
a cell, or Ctrl+Tab from the meta-button row. Once focused: Left/Right
wraps between columns, Down opens the filter menu, Enter/Space sorts,
Tab/Ctrl+Tab/Shift+Tab hand off to the table (group-aware landing, shared
with the meta-button row's own Tab handling).

**Meta-button row: Up/Down ≠ Left/Right, and a menu-owning button's popup
needs its own toggle/no-wrap handling.** An earlier version aliased
Up/Down to the exact same cycling Left/Right does across
Inventory/Wishlist/Columns/Clear Filters — wrong, since Down/Up on a
menu-owning button (only Columns today) should EXPAND/COLLAPSE that menu
instead, not move focus along the row. Fixed in
`CardDatabaseView.eventFilter`: Left/Right still cycle
(`_focus_adjacent_metabutton`); Down opens the focused button's menu via
`self._metabutton_menu_openers` (a no-op for buttons with no menu); Up is
reserved for collapsing but, by construction, can never actually reach a
focused button while a menu is open (see next paragraph), so it's just
consumed there. Two more real gaps this same pass fixed, both specific to
Columns' `_StayOpenMenu`: (1) Qt's native QMenu arrow-key handling CYCLES
(Up from the first item wraps to the last) — wrong for a menu standing in
for a button's expanded/collapsed state, so `_StayOpenMenu.keyPressEvent`
(card_table.py) now clamps Down at the last item and closes the menu on
Up-past-the-top instead of wrapping — the same Up-collapses convention
`_MenuSearchBox`'s own filter menus already have, just without that
class's two-step "land on nothing highlighted first" version, since there's
no search box here to double as that intermediate stop. (2) a live QMenu
grabs the keyboard for the whole app while showing, so the Alt+3 QShortcut
that opened it can't fire a SECOND time to close it — worked around by
checking for "the same Alt+N pressed again while this button's menu is
open" directly in `CardDatabaseView`'s own application-level eventFilter
(installed for other reasons already — see next paragraph), which still
receives keypresses during that grab the same way `_MenuSearchBox`'s own
app-level filter does. `_show_columns_menu` now tracks open/closed state
(`self._open_menu`) so both a repeat click and a repeat Alt+3 toggle-close
rather than reopen.

**Plain Tab had to be caught via an app-level `eventFilter`, not
`keyPressEvent`**, for both `CardTableHeader` and `CardDatabaseView`'s
meta-button row: `QWidget::event()` runs its own internal
`focusNextPrevChild()` for a plain, unmodified Tab/Shift+Tab *before*
`keyPressEvent()` ever runs, but explicitly skips that internal handling
for Ctrl/Alt-modified keys — which is exactly why Ctrl+Tab always worked
while plain Tab silently left stale focus state behind. Same fix shape as
`collapsible_pane.py`'s Tab interception: an application-level filter
installed ahead of Qt's own routing. Recurs three times in this codebase
(`collapsible_pane.py`, `card_database_view.py`, `card_table.py`'s
`CardTableHeader`) — if a Tab/Shift+Tab bug shows up somewhere new, this
is the first thing to check.

**"Price Source" submenu keyboard access** (three attempts before it
worked): a real `QMenu.addMenu()` submenu's own trigger action isn't
`isCheckable()`, so `_MenuSearchBox`'s navigable-actions scan skipped it
by default (fixed via explicit `add_navigable_action` registration). The
harder problem: `QMenu.setActiveAction()` on an action with a submenu
**opens that submenu immediately** as an undocumented Qt side effect, so
by the time keyboard nav "arrives" at it, Qt has already shown it — a
second `.exec()`/`.popup()` call on top of that repositions and
destabilizes it (confirmed: visible jitter, Left/Enter/Space unreliable
after first use). Fix: stop trusting native nested-popup routing
entirely — `_MenuSearchBox._handle_submenu_key` drives the submenu's own
Up/Down/Left/Enter/Space itself, *adopting* whatever Qt auto-opened
rather than re-showing it.

**Group-header rows and selection rectangles don't mix.** A flat
`QItemSelection(anchor, target)` that merely *passes through* a spanned
group-header row (`setSpan()`) renders as the whole row selected, every
column — even though the header's own cells aren't individually
selectable. Fix: build the selection as one `QItemSelection` per
contiguous run of real rows, skipping header rows, rather than one flat
rectangle (`CardTableView._extend_selection_to`).

**Anchor tracking**: `self.currentIndex()` can't simultaneously be "the
fixed corner a Shift-chain extends from" and "the thing every extend
moves" — `CardTableView._selection_anchor` is tracked explicitly,
updated only on non-shift navigation, left untouched by anything that
extends. `Ctrl+Home/End` go through the selection model directly with an
explicit `ClearAndSelect` rather than the unreliable `setCurrentIndex()`
convenience, which doesn't reliably clear a prior selection.

## StatField clickable-variant centering (card detail popup)

**Current design, two parts, both visible in `StatField.__init__`**: (1)
the QToolButton is given `QSizePolicy.Maximum` (sizes to its own
`sizeHint()`, nothing more) and centered within its field via ordinary
`addStretch()` on both sides — centering happens at the layout level, not
via CSS `text-align`. (2) the native dropdown-arrow subcontrol is removed
entirely (`menu-indicator { image: none; width: 0px; }`) rather than
padded around, since the value text itself is already the click target.

**What this replaced**: stretching the button to fill the whole field and
relying on `text-align: center` plus hand-estimated left/right padding to
account for the arrow. Two independent systems were fighting over the
same pixels — Qt's style engine positions the arrow subcontrol by its own
rules, while the CSS padding was a separate guess at how much room it
needed. When they disagreed (consistently), text sat off-center by a
fixed, structural amount. Removing the arrow rather than estimating its
width removes the second system entirely instead of trying to make the
two guesses agree.

## Card detail popup: Type-column alignment

**Current design**: all three stat rows (Type/Mana, Edition/Rarity/Price,
Language/Condition/Foil) live in ONE `QGridLayout` — a hard Qt invariant
guarantees every cell in a column shares the same width, instead of a
formula having to correctly guess how a *different*, independently-laid-
out row divides its own width. Type's cell spans columns 0+1 (room to
grow rightward); `StatField.set_grid_anchor()` still centers *short*
Type values on column 0 alone by querying a real single-column sibling
cell (`QGridLayout.cellRect()`) directly.

**Column widths are explicitly LOCKED** post-first-layout
(`CardDetailDialog._lock_column_widths`) — `setMaximumWidth()` on an
individual cell doesn't reliably stop `QGridLayout` from sizing a COLUMN
off an uncapped `minimumSizeHint()`; both `setColumnMinimumWidth()` and
`setMaximumWidth()` have to be set to the identical number on every cell
in the column to remove Qt's remaining degree of freedom. Safe only
because this dialog is fixed-size (900×560, frameless windows lose
native edge-drag resize) — revisit before the dialog becomes resizable or
before real DPI/text-scaling support exists (see "DPI/scaling" below).

**Three attempts before this worked** (all failed for different reasons,
worth knowing before re-deriving from scratch):
1. Anchor from Type's own width alone (`width/4`) — wrong because
   Type+Mana's row and a real 3-column row divide width up differently;
   "1/4 of Type's own width" answers a structurally different question
   than "half of a real column's width," even though the numbers looked
   close.
2. Read a live sibling widget's `.width()` at compute time — timing-
   fragile; depended on that widget having already settled into final
   geometry, with nothing guaranteeing that ordering relative to a
   deferred `QTimer.singleShot(0, ...)` refresh.
3. An analytical correction formula, checked out exactly on paper — still
   wrong, because it depended on an unverified assumption (Qt's actual
   default inter-column spacing) never checked against a real render.

The fix needed **both** a shared authority (the grid) **and** actually
instantiating the dialog headlessly and measuring real rendered pixel
positions (`QFontMetrics.boundingRect()`, `.mapTo()`) — which caught a
second, previously invisible bug: anchor math applied via
`setContentsMargins()` on a label whose own coordinate origin was already
shifted by `StatField`'s own inner margin (`FIELD_INNER_MARGIN`).

## Reticle-zoom image viewer

**Current design**: `ImageZoomWidget` tracks exactly two things —
`_zoom` (scalar, 1.0 = fit-to-screen) and `_pan_center` (normalized point
in the full image). Window size is *derived* (`_geometry_for_zoom`): the
image at current zoom is `fit_size * zoom` in both dimensions (uniform —
aspect ratio never distorts), clamped independently per axis to the
screen — this is what makes the window correctly grow into whatever
shape the screen allows as zoom increases, instead of staying
letterboxed. `MAX_ZOOM = 4.0` is an explicit ceiling (was previously
unbounded and could run away past what one wheel-tick could unwind).

**Two earlier designs, each fixed one bug and revealed the next**:
1. Reticle zoom just resized the window directly — no persistent state,
   so nothing composed across repeated zooms.
2. Two separate variables: `_zoom` (wheel-adjusted window scale) and
   `_view_rect` (reticle-adjusted crop). Repeated zooms could compose,
   but wheel only touched `_zoom` — zooming out after several reticle
   zooms shrank the window while the crop (and its multiplier) stayed
   frozen, so the on-screen number could report huge magnification even
   with a small window.
3. Deleted `_zoom`, let one crop rectangle drive everything, wheel
   scaling both dimensions by the same factor. Fixed the drift, but a
   uniformly-scaled crop can never change SHAPE — wheel-zooming from the
   default (card-shaped) crop just produced a smaller, still card-shaped
   crop, so the window never actually grew past its letterboxed starting
   size under wheel alone, even as the reported number climbed.

**General lesson**: when one piece of state is being asked "how much is
shown" and "what shape is it" simultaneously, check whether those are
really two independent facts conflated into one representation — not
just a formula needing more tuning.

## Filter-menu search box: state-vs-visibility debugging

Three attempts to fix Up/Down/Space doing nothing in a real window, each
individually reasonable and each a real dead end:
1. Moved handling to an app-level `eventFilter` (QMenu's own internal
   arrow-key handling was hypothesized to intercept keys first). Verified
   via `app.sendEvent(box, ev)` — but that call *forces* the receiver to
   be the box, which never exercises the real popup-routing ambiguity. No
   effect in a real window.
2. Dropped the `watched is self` condition entirely. Verified with a
   decoy `watched` object this time — proving receiver-identity
   independence. Still no effect.
3. **The actual fix**: reframed the symptom. "Nothing happens" doesn't
   mean the events aren't arriving — `main.py`'s global stylesheet had
   never styled `QMenu` at all, and once *any* custom QSS applies to a
   `QApplication`, Qt's style engine stops relying on the native
   platform's automatic hover/selected rendering for anything not
   explicitly re-declared. `setActiveAction()` may have been working the
   whole time, just invisibly. Added explicit `QMenu`/`QMenu::item:selected`
   QSS. Space-to-toggle was a genuinely separate, real gap (never
   implemented) — real `QMenu` only handles Space when the menu itself
   holds keyboard focus, which this design deliberately never grants.

**General lesson — two distinct failure classes, don't conflate them**:
"the logic runs but nothing is visibly different" (headless tests that
manually construct/send events can confirm state changed but can't
confirm a human would ever SEE it change — check for missing QSS state
styling before assuming event routing is broken) vs. "the logic looks
correct on paper and still isn't, because a coordinate-space/spacing
assumption was never verified against a real render" (the Type-column
saga above — headless Qt CAN render and measure real geometry; use that
before re-deriving algebra a third time).

## Data Management / Options dialogs

**Shell only, no pipeline yet** for both. Browse buttons are real
(`QFileDialog` + async `os.stat()`/folder-size via `QThreadPool` —
`_StatWorker`/`_FolderSizeWorker`, since a slow/spun-down disk should
never freeze the window); Update/Locate/Download/Apply give the same
transient "working"/"Applied ✓" feedback pattern throughout the app but
don't persist or fetch anything real. `dialog_common.py`'s
`VerticalTabDialog` is the shared chrome (siblings, not inheritance — see
that module's docstring) with lazy per-tab page construction (Options
went from ~30ms to ~7ms steady-state construction once only the visible
tab builds up front).

**Edition picker here needs none of card_table.py's `_MenuSearchBox`
machinery** — that machinery exists purely because an embedded search box
competes with QMenu's own arrow-key handling for focus. A plain checklist
QMenu with no embedded widget (like this picker) already gets correct
Up/Down/Space/Enter from Qt for free. Worth remembering so this isn't
"fixed" later by copying machinery it doesn't need.

## Startup / preload performance

**Cold PySide6 native-library load is the dominant launch cost and isn't
fixable from Python** (measured 4.4–5.6s for `import PySide6.QtWidgets`
alone, wildly inconsistent — consistent with the general reality of any
compiled Qt binding's first read off disk in a process). What WAS fixable
and is fixed: lazy top-level view construction (only the visited tab
builds), lazy dialog imports (deferred into their own `_open_*` methods),
and a real `QSplashScreen` shown before `MainWindow` construction begins
— doesn't reduce underlying cost, just stops hiding that something is
happening (a perceived-responsiveness fix, not a real one).

**Lazy construction alone just relocates the one-time cost** to whichever
tab/dialog is clicked first — still a felt hitch, just later.
`main.py`'s staggered background-preload timer chain
(`_run_next_preload_step`, `PRELOAD_STEP_DELAY_MS` between steps) closes
that gap. Not a real thread — Qt widgets can only be built/touched on the
GUI thread, unlike `data_management_dialog.py`'s safely-backgrounded
`os.stat()` — the staggering (letting the event loop service pending
input between steps) is what stands in for "async" here. Every preload
task reuses the exact guarded builder path a direct user action would
hit, so whichever happens first is a no-op for the other.

## Parked features (not yet designed in detail)

- **Flexible search engine**: its own pane (not just column filters),
  multi-field queries, a lighter Ctrl+F popup that collapses non-matching
  rows in whichever pane has focus. Landing spot already reserved:
  `card_database_view.py`'s button row has a deliberate `addStretch()`
  after Inventory/Wishlist/Columns for this.
- **Undo/redo + save model**: scope (tree edits only, or table edits
  too?), single global stack vs. per-view, explicit-save-vs-autosave
  (implies an in-memory "dirty" copy layered over disk/SQLite — decide
  BEFORE the real data layer is built, not after).
- **Theming**: replace `main.py`'s hardcoded QSS hex colors with
  `QPalette`-role-driven values (`palette(highlight)` etc.) so the OS's
  accent color/light-dark setting can actually apply, plus a 2-3-preset +
  "follow system" switcher in Options. Custom-painted bits (header
  background, popover, image zoom overlay, the QMenu selection rule) all
  need to read from whichever preset is active.
- **Variable text scaling / DPI**: fixed-pixel assumptions throughout
  (`CardDetailDialog`'s locked column widths, `StatField`'s spacing
  constants, `_legality_column_width()`) — same underlying "hardcoded
  instead of Qt/OS-derived" pattern as theming; worth one combined audit
  pass covering both axes. Do this before much more pixel-precise layout
  work accumulates.
- **Options/i18n**: string externalization (per-language files, each
  falling back to English for missing keys) — do this before too many
  more inline UI strings accumulate, since retrofitting later is a bigger
  job.
- **Tag-apply search box**: same narrow-as-you-type box the column filter
  menus already have, simpler (no "excluded values" concept — just show/
  hide tree items and their ancestor folders).
- **Tag hotkey-letter sequences**: assign a single letter to a tag,
  unique only among its siblings at that tree depth — typing a sequence
  navigates straight to it (e.g. `a c c` vs `a c d` under the same parent,
  vs `c c c` down an unrelated branch). Open questions: where the
  assignment lives, collision handling, how the UI signals "type a letter
  to jump."
- **Group-boundary option for arrow-key movement**: when grouped, an
  opt-in setting (leaning off by default) for Up/Down to stop at a
  group's edge instead of falling through to the next group.
- **Default-add behavior + collapsing owned variants into one row**: new
  cards default to configured language/latest printing/non-foil/NM; a
  card with several owned printings/conditions shows as one row with an
  expand affordance. Real data-model question, worth designing alongside
  the eventual SQLite collection schema.
- **Full Excel keyboard parity gaps**: contiguous-block-aware Ctrl+Arrow
  (stop at data gaps, not just the table edge), Tab/Shift+Tab during F2
  edit, plain Ctrl+Arrow without Shift (done), Delete-to-clear, fill-
  handle/Ctrl+D.

## General debugging principles (cross-referenced above, worth restating)

1. **State changing correctly ≠ a human seeing it change.** Headless
   tests that manually construct/dispatch events can confirm the former,
   never the latter. Once any custom QSS exists, check for missing
   `:selected`/`:hover`/`:focus` styling before assuming event routing is
   broken.
2. **Math that checks out on paper can still be wrong** if it depends on
   an unverified assumption about a real render (default spacing, a
   margin's coordinate origin). Headless Qt *can* render and measure real
   geometry (`.geometry()`, `.mapTo()`, `QFontMetrics.boundingRect()`) —
   use that to check a pixel-level claim rather than re-deriving algebra
   a third time.
3. **Two independently-laid-out things that need to visually agree**
   resist being reconciled by formula. Prefer giving them one shared
   authority (a real shared layout, a shared measured value) over two
   separately-computed-but-matching answers.
4. **Qt's internal Tab/Backtab handling runs before a focused widget's
   own `keyPressEvent()`**, but skips Ctrl/Alt-modified keys — this is
   why Ctrl+Tab "just works" in places plain Tab silently doesn't, and
   why plain-Tab interception has to happen in an app-level `eventFilter`
   installed ahead of Qt's own routing, not in `keyPressEvent`. A related
   but distinct cause of the same symptom: keyboard focus normally sits
   on a CHILD widget (a tree, a table), not on the container that
   logically "owns" the shortcut (a splitter, a header) — Qt delivers key
   events straight to whichever widget has focus, and that widget's own
   internal Tab handling can consume the key before it ever bubbles up to
   a parent's own `event()`/`keyPressEvent()` override. Either way, the
   fix is the same: an application-level filter checking whether the
   event's target is the container or one of its descendants.
5. **`QMenu.setActiveAction()` on an action with a submenu opens it
   immediately** as an undocumented side effect — don't call
   `.exec()`/`.popup()` on top of an already-auto-opened submenu; adopt
   it as-is.
6. **A single piece of state answering two conceptually different
   questions** ("how much" and "what shape") is a sign it should be two
   separate variables, not a formula needing more tuning.
7. **A live QMenu's keyboard grab silences background QShortcuts, not
   just background keyPressEvent handlers.** If a hotkey needs to act a
   SECOND time while the menu it opened is still showing (e.g. toggle it
   closed), don't expect the same QShortcut to fire again — intercept the
   keypress in an application-level eventFilter instead, which still
   receives events during the grab (same mechanism `_MenuSearchBox` and
   `ImageZoomWidget`'s own outside-click filters already rely on).
