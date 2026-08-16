# Design notes: parked features + debugging lessons

Organized by topic, newest understanding first within each entry. See
PROJECT_CONTEXT.md's Roadmap for a status-tagged index of everything here.

## Scaling infrastructure

**Design**: `scaling.py`'s `scale_manager` (module singleton) holds two
INDEPENDENT floats, `ui_scale` and `text_scale`, plus one `scale_changed`
Qt signal fired on either change — same "one shared authority" shape as
`SideNav.TABS` or `CardTableModel`'s filter state feeding two different
UIs (see "Recurring patterns" in PROJECT_CONTEXT.md). Every scale-aware
widget connects to that ONE signal rather than inventing its own
notification path.
- `text_scale` drives `QApplication`'s default font POINT SIZE
  (`ScaleManager._apply_font_scale`) — close to a "free" axis, since Qt's
  layout system already reflows anything built with layouts +
  QFontMetrics (most of this app) around a font change with no further
  code. The one thing that had to be actively REMOVED for this to work:
  hardcoded `font-size: Npx` in QSS strings (main.py's global QWidget
  rule, frameless_dialog.py's title, card_popover.py's name label,
  dialog_common.py's `section_label`) — a literal QSS font-size wins over
  the app's own default font, which would have silently pinned that
  widget's text regardless of text_scale. Replaced with either no
  explicit size (inherits the scaled default) or a relative
  `setPointSizeF(font.pointSizeF() * k)` bump in code, so "a bit
  bigger/smaller than body text" stays true at any scale instead of
  freezing at one absolute size.
- `ui_scale` drives everything else (icon sizes, fixed widget widths,
  margins/padding baked into QSS, dialog default sizes, header paint
  metrics) via `sp(px)` — NOT automatic; every call site that used to
  write a bare pixel literal needs `sp(that literal)` instead, evaluated
  AT USE TIME. A module-level `WIDTH = sp(28)` would freeze at whatever
  scale was active on first import — this is why several QSS strings
  that used to be static module-level constants (`dialog_common.py`'s
  `APPLY_BUTTON_STYLE`/`DANGER_BUTTON_STYLE`/tab-list style,
  `card_database_view.py`'s `TOGGLE_STYLE`, `options_dialog.py`'s swatch
  style, `card_detail_popup.py`'s Apply-button style, `main.py`'s whole
  app stylesheet) are now FUNCTIONS, called fresh wherever they're
  applied, instead of strings referenced directly. Any code still
  calling one of these as a bare string (rather than `NAME()`) is a bug.

**Ctrl+Wheel** moves both scales together, one `WHEEL_STEP` (0.05) per
wheel notch — a single combined "zoom," matching the familiar browser/OS
convention, rather than needing a second modifier to reach one axis from
the mouse. Caught in `main.py`'s `MainWindow.eventFilter` (an
app-level filter, extending the one already installed there for the
1/2/3 tab shortcuts) — checked independent of `watched`, since it has to
fire regardless of which widget the cursor happens to be over, the same
reasoning `CardDatabaseView`'s own Alt+N-while-menu-open check already
uses. The Options dialog's Interface page has two separate sliders
(70–200%, live, two-way synced with Ctrl+wheel changes via
`_sync_scale_sliders`) for when a user wants to split the two axes apart
— see `ScaleManager`'s own module docstring for why two independent
numbers, not one, is the point.

**RUNTIME-ONLY**: nothing here persists between sessions yet — Options'
"real settings store" is still TODO (see Roadmap). Every scale change is
live and immediate, and lost on restart. Deliberate scope cut for this
round, not an oversight.

**Per-file conversion status** (own tracking, same Done/Partial/TODO
convention as PROJECT_CONTEXT.md's Roadmap):
- **Done, and live-rescales an already-open window**: `main.py` (global
  stylesheet + Ctrl+Wheel), `side_nav.py`, `frameless_dialog.py` (every
  dialog's title bar), `dialog_common.py` (Options/Data Management's
  shared tab-list chrome), `collapsible_pane.py` (the Deck/Tag tree
  splitter's handle + arrow zone), `options_dialog.py`'s own dialog size
  and Interface-page sliders, `card_database_view.py`'s button row
  (Inventory/Wishlist/Columns/Clear Filters), `card_table.py`'s header
  paint metrics (sort arrow, filter dot, focus ring, resize margin) and
  the checkbox column's width. Row height needs no explicit handling at
  all — it's already font-metrics-derived by Qt, so text_scale grows it
  for free; `_apply_table_scale` just forces an immediate
  `resizeRowsToContents()` instead of waiting for an incidental repaint.
- **Done at CONSTRUCTION time only, not live for an already-open
  instance**: `card_detail_popup.py` (`CardDetailDialog`'s size/spacing/
  legality-column-width, `ImageZoomWidget`'s base size) — deliberate:
  `StatField`'s dynamic-anchor Type-column alignment took three real
  attempts to get right (see that entry below) and depends on
  `FIELD_INNER_MARGIN` being IDENTICAL between the margin actually
  applied at construction and the margin subtracted in `set_text()`'s
  anchor formula on every later call. Reapplying `sp()` mid-lifetime
  without re-deriving both together risks exactly the "two
  independently-computed numbers drift" failure mode debugging-lesson #3
  already warns about — not worth risking for a dialog that's recreated
  fresh on every double-click anyway (`card_table.py` never caches one).
  `card_popover.py` similarly sizes itself once at construction (it IS
  cached/reused per table, unlike the detail popup) — a hover preview is
  low-stakes enough that this is an accepted gap, not a solved one.
  `tree_pane.py`'s `_make_icon()` bakes a QPixmap at CALL time (correct
  for new icons after a scale change), but existing tree items' already-
  baked icons don't retroactively resize.
- **Partially done**: `options_dialog.py`'s remaining five pages
  (Language/Online/Interface's other rows/Input/Advanced) and
  `data_management_dialog.py`'s three pages are lazily built ONCE per
  dialog lifetime (`VerticalTabDialog`'s whole design, see that class's
  docstring) and not rebuilt on a scale change — a slider/checkbox row
  laid out before a scale change keeps its old metrics until the page is
  torn down and rebuilt (i.e. the app restarts, since these dialogs are
  cached instances). The FUNCTION-based styles (`APPLY_BUTTON_STYLE()`
  etc.) are correct at whatever moment a button's `setStyleSheet()` call
  actually runs, so a freshly-opened dialog is fine; an already-open one
  showing a page built before a scale change is not.
- **Not converted yet**: `card_detail_popup.py`'s `StatField` internal
  spacing (correct at construction — see above — this note is about the
  live-rescale gap specifically), `tag_apply_dialog.py`,
  `tag_assignments.py` styling (n/a — no UI), `data_management_dialog.py`
  page-internal fixed widths (`filename_label.setMinimumWidth`-style
  calls), a handful of remaining literal-pixel QSS fragments inside
  per-page builders across `options_dialog.py`/`data_management_dialog.py`
  that weren't part of this round's pass. None of these are visually
  broken today (Qt's default sizing still works, just doesn't grow/shrink
  with ui_scale) — they're a "doesn't yet participate in live rescaling"
  gap, not a "looks wrong" one. Next scaling pass should sweep these
  page-builder methods specifically.

**Scaling polish round 1 (post-initial-implementation feedback)**: four
follow-up fixes, all against the scaling infrastructure above rather than
new axes of scaling:

1. **Step size (WHEEL_STEP, slider singleStep/pageStep) -> 10%.**
   Originally 5% on the wheel and Qt's own un-set QSlider default (1%,
   arrow-key/click-track only) on the sliders -- two different step sizes
   for what's conceptually one setting, and both finer than useful for
   hand-tuning. Now both scaling.WHEEL_STEP and both Options sliders'
   singleStep/pageStep are 10, so every way of adjusting scale moves in
   the same-sized, predictable jump.

2. **Ctrl+wheel felt laggy -- root cause and fix.** NOT a PySide/Qt
   rendering ceiling: every single scale_changed emission triggers a real,
   nontrivial cost (main.py rebuilds and reapplies the ENTIRE app-wide QSS
   string, and every scale-aware widget across the app re-runs its own
   _apply_*_scale on top of that -- a full re-polish pass, not a cheap
   no-op). Applying that pass once per individual wheel EVENT (a fast
   physical flick can fire a dozen-plus in well under a second) is what
   actually felt slow. Fix: scale_manager.queue_wheel_delta() /
   _flush_wheel_steps() (scaling.py) accumulate the pending delta and
   apply it ONCE, ~WHEEL_FLUSH_INTERVAL_MS (50ms) after the most recent
   wheel event, via a restarted singleShot QTimer -- same final scale
   after a flick, far fewer full-app repolish passes along the way. main.py's
   wheel handler calls queue_wheel_delta() instead of adjust_combined()
   directly now; adjust_combined() itself is unchanged and still the
   thing that actually applies a delta (queue_wheel_delta just defers and
   batches calls into it). A genuinely CHEAPER per-change cost (e.g.
   moving off QSS entirely toward QPalette-driven theming, already a
   parked TODO -- see "Theming" below) would help further but is a much
   bigger, separately-tracked project; coalescing was the fix available
   within the existing QSS-based approach.

3. **Dialogs could grow off-screen at a high scale -- fixed at the shared
   base, not per-dialog.** Every popup in this app (card detail, tag-apply,
   Options, Data Management) is a FramelessDialog. That class's resize()
   is now overridden to clamp whatever size a subclass asks for to the
   CURRENT screen's availableGeometry (minus a margin, floored at a
   minimum usable size) -- transparent to every subclass's existing
   `self.resize(sp(W), sp(H))` call, no call sites needed to change.
   self.content_layout now lives inside a QScrollArea (both scrollbars,
   Qt's default ScrollBarAsNeeded) instead of being added straight to the
   dialog, so content that's still too big for the clamped size scrolls
   instead of being clipped or forcing the window past the screen's own
   edges. The two pieces are complementary, not redundant: clamping alone
   would crop content with no way to reach the rest of it; scrolling
   alone wouldn't stop the WINDOW itself from overflowing the screen.
   Caught along the way: DataManagementDialog's own resize(880, 620) was
   never routed through sp() at all (a pre-existing gap, unrelated to this
   round's actual bug) -- fixed to sp(880)/sp(620) with a matching
   scale_changed connection, same pattern OptionsDialog already used.
   KNOWN MINOR OVERLAP: Data Management's own per-tab pages already wrap
   their content in their own QScrollArea (see data_management_dialog.py)
   -- nesting that inside FramelessDialog's new outer scroll area can in
   principle produce a scrollbar-inside-a-scrollbar in an extreme case.
   Accepted rather than special-cased: the OUTER scroll only actually
   engages once the whole dialog (tab list + page area together) can't
   fit the clamped window, which the inner per-page scroll already
   protects against for the common "one page's content is too tall" case.
   Revisit only if the nested-scrollbar case is ever actually hit in
   practice.

4. **Text clipping at a high text_scale -- "Tag Database" on the side
   nav was the reported example.** Two different fixes for two different
   Qt widgets, since they have two different native capabilities:
   - QListWidget (Options'/Data Management's own tab list,
     dialog_common.py) supports word-wrap NATIVELY --
     `tab_list.setWordWrap(True)` was simply never turned on. One line,
     no manual wrap logic needed; Qt handles re-wrapping and row-height
     growth itself.
   - QPushButton (SideNav's own tab buttons) has NO native word-wrap
     property at all -- same gap card_detail_popup.py's StatField already
     hit for QToolButton's Condition/Language fields, and solved there
     with a manual "\n"-insertion helper (_wrap_to_pixel_width). SideNav
     now has its own copy of that same helper (duplicated rather than
     imported -- see side_nav.py's own comment for why: it's a small,
     pure, dependency-free function, and reaching into card_detail_
     popup.py's private helper would be a stranger coupling than
     repeating six lines), re-run against each button's live font metrics
     and the nav's current width budget both at construction and on every
     scale_changed.
   TRACKED GAP, NOT FIXED THIS ROUND: every OTHER QPushButton row that
   could plausibly overflow at an extreme text_scale -- CardDatabaseView's
   Inventory/Wishlist/Columns/Clear Filters meta-button row in particular
   -- still has no wrap handling and will clip exactly like SideNav used
   to. Not fixed here since it wasn't the reported symptom and this app's
   existing convention (see "Per-file conversion status" above) is to fix
   the reported case, document the remaining ones, and sweep them in a
   dedicated pass rather than guessing at every theoretical overflow site
   in one round. If a report comes in about a specific clipped button
   elsewhere, side_nav.py's _wrap_to_pixel_width /
   _refresh_button_labels shape is the template to reuse.

**Scaling polish round 2 (screen-fit growth, wheel-drift fix, slider
debounce)** -- follow-up feedback after round 1 shipped:

1. **Dialogs showed scrollbars far from any screen edge.** Round 1's
   screen-clamp (FramelessDialog.resize()) was correct but not the
   actual cause here -- the dialogs weren't anywhere NEAR the clamp.
   The real cause: a subclass's design-time `self.resize(sp(W), sp(H))`
   is a fixed FORMULA tuned around a "normal" text_scale; at a
   meaningfully higher text_scale the real content (taller wrapped
   labels, bigger fonts) can outgrow that formula's guess well before it
   outgrows the SCREEN, and round 1's new QScrollArea faithfully started
   showing scrollbars for that gap -- technically correct, but
   unnecessary when the desktop plainly had room to just make the window
   bigger. Fix: FramelessDialog._grow_to_fit_content() (new) measures
   self._content_widget.sizeHint() -- content_layout's own, real,
   recursively-computed preferred size, not the formula's guess -- and
   grows the window to match (still subject to resize()'s existing
   screen-clamp) if bigger than what's already set. Runs synchronously
   in showEvent (before any subclass's own deferred singleShot(0) post-
   show work -- see the method's own docstring for why synchronous-and-
   in-showEvent specifically avoids a race with e.g. CardDetailDialog's
   column-locking), and again, debounced via scale_changed, whenever the
   dialog is already open and scale changes further (e.g. dragging
   Options' own sliders while Options itself is the dialog being sized).
   The scroll area from round 1 is now the genuine LAST-resort fallback
   (screen truly too small) rather than the first thing a text_scale
   change hit.

2. **Ctrl+wheel scale drifted off the 10% grid on a laptop trackpad
   gesture (103%, 129%, 147%, ...).** Round 1's coalescing was real and
   necessary but didn't touch this bug -- it batched EVENTS, but each
   event's own delta/120 fraction was still computed and applied
   independently once the batch flushed. A physical detented mouse wheel
   reports angleDelta() in clean multiples of 120; a trackpad's
   synthesized "smooth scroll" gesture mostly doesn't, so summing
   fractional per-event steps landed off WHEEL_STEP's clean 10%
   increments. Fixed by accumulating the RAW angleDelta().y() units
   themselves (queue_wheel_delta, scaling.py) and only ever converting a
   WHOLE multiple of WHEEL_UNITS_PER_STEP (120) into an actual scale
   step on each flush -- any leftover remainder stays queued toward the
   NEXT flush rather than being applied fractionally or discarded, so a
   long trackpad gesture still eventually lands exactly on the grid no
   matter how oddly its individual events happened to be sliced.
   Verified with a standalone simulation (400 arbitrary, non-120-aligned
   deltas) landing exactly on a clean multiple of 10%.

3. **Still laggy -- root cause was the OPTIONS SLIDERS, not (only) the
   wheel.** Round 1 only wired coalescing into the Ctrl+wheel path;
   dragging an Options slider called scale_manager.set_ui_scale()/
   set_text_scale() DIRECTLY from _on_*_scale_slider_changed, and
   QSlider fires valueChanged continuously WHILE being dragged (not just
   on release) -- so a single drag across the slider's range was
   triggering the full expensive rescale pass (rebuild the whole app QSS
   string, rerun every scale-aware widget's own _apply_*_scale) once per
   pixel of mouse movement, which is what actually produced the
   multi-second freeze reported. NOT a PySide/Qt rendering ceiling --
   the underlying QSS-repolish cost is real and inherent to this app's
   current theming approach (a future move to QPalette-driven theming,
   already a parked TODO -- see "Theming" below -- would make each
   individual change cheaper; that's a separately-tracked, much bigger
   project), but nothing was stopping that cost from running dozens of
   times across the span of one drag gesture. Fixed by giving the
   sliders their own debounced entry points
   (scale_manager.queue_ui_scale/queue_text_scale, sharing the exact
   same flush timer and SCALE_FLUSH_INTERVAL_MS the wheel path already
   used) instead of calling the immediate setters directly -- the
   percent-value LABEL still updates on every tick (cheap, just text, so
   the number stays live while dragging), but the actual app-wide
   rescale now only fires once dragging genuinely pauses, not
   continuously through the gesture. This is a deliberate DEBOUNCE (wait
   for a pause), not a rate-limited THROTTLE (fire at most every N ms
   even during continuous motion) -- during a smooth, uninterrupted drag
   the app now does ZERO expensive work until the user stops, which is
   the actual fix; a throttle would still have done many redundant
   passes across one long drag.

**General lesson from round 2**: "coalesce rapid signals" isn't one fix
reusable by inference across an app -- it has to be wired into EVERY call
site that can fire rapidly, not just the first one identified. Round 1
fixed the wheel path and read as "scaling is smoother now," which was
true but incomplete; the sliders were a second, independent rapid-fire
source of the exact same underlying cost that hadn't been touched yet.
Worth checking for sibling call sites (anything else calling
set_ui_scale/set_text_scale/adjust_combined directly) before considering
a "make X respond to rapid input" fix actually done.

**General lesson for future scaling work**: a hardcoded pixel constant
is only a REAL bug once it's actually READ somewhere without going
through `sp()`/`scale_manager.sp()` — the constant itself being a bare
number (`ARROW_ZONE_HEIGHT = 90`) is fine to keep as a named "design-time
base value" as long as every USE SITE wraps it. Grep for
`setFixedWidth(`, `setFixedHeight(`, `setFixedSize(`, `resize(`, and
inline `px` inside triple-quoted QSS strings to find what's still
unconverted in a given file — same mechanical check this round's pass
used file-by-file.



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
8. **An application-level `eventFilter` (`QApplication.installEventFilter`)
   receives QWindow events too, not just QWidget ones.** `watched` can be
   a bare `QWindow` (native window-manager plumbing underneath a
   top-level widget), which fails `isinstance(watched, QWidget)` and
   crashes any branch that calls a QWidget-only method on it
   (`isAncestorOf()`, `.window()`, etc.) with a `TypeError`. Every
   app-level filter in this codebase (`collapsible_pane.py`,
   `card_database_view.py`, `card_table.py`'s `CardTableHeader`/
   `_MenuSearchBox`, `frameless_dialog.py`, `main.py`) touches `watched`
   as a widget — `frameless_dialog.py` already guarded this correctly
   from the start (`isinstance(watched, QWidget)` before calling
   `.window()`); `collapsible_pane.py`'s Tab/collapse filter didn't, and
   intermittently crashed with "Error calling Python override of
   QSplitter::eventFilter()" the moment a QWindow event reached it (real
   log output, not hypothetical — this is what surfaced the gap). Fixed
   there by hoisting the same `isinstance` guard above every branch.
   Worth checking any NEW app-level filter added to this codebase against
   this same gap before it ships.
