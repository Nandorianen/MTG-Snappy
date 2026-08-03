# MTG Local Database — Prototype

## Reticle-select zoom on the card image, pan/zoom viewer model (this round)
Resolves the idea parked in NOTES.md. Went through three real designs
before landing on the one below -- see "Design journey" at the end for
the two that didn't hold up and why, worth reading if this class of bug
(numbers or shapes that quietly stop tracking reality) shows up again.

**Final design: standard image-viewer zoom/pan, one piece of state.**
`ImageZoomWidget` now behaves like a normal image viewer (ACDSee/XnView-
style): opens fit-to-screen, zoom is purely a VIEW operation that never
touches the underlying image, and zooming all the way back out reproduces
the *exact* opening state -- not just something close to it.

- **A single normalized crop rectangle (`_view_rect`) is the only state
  that exists.** (0,0,1,1) means "the whole card." Mouse wheel scales
  both its width and height by the same factor, centered on the crop's
  own current center -- shrinking to zoom in, growing (capped at 1.0 per
  axis) to zoom out. Ctrl+drag reticle-select computes a new crop by
  composing the dragged rectangle against whatever crop was already
  active, so a second reticle zoom crops further into the first rather
  than re-measuring from the original image. **Both the on-screen window
  size and the displayed zoom-multiplier number are pure functions of
  this one rectangle** (`_window_size_for_crop`, `_effective_zoom_multiplier`)
  -- there is no second, independently-adjustable variable they could
  quietly disagree with each other about.
- **The window opens, and always renders, as "the current crop, fit to
  the current screen, in the crop's own shape."** At the default crop
  (the whole card), that shape is the card's own aspect ratio, so it
  opens and fully-zoomed-out looks exactly card-shaped. Once a reticle
  selection narrows the crop to some other shape (a wide, short
  selection, say), the window takes on THAT shape instead -- and that's
  correct, not distortion: the window is showing exactly the rectangle
  the user asked to see, at whatever shape that rectangle actually is.
  Only once the crop widens back toward (0,0,1,1) does the window
  necessarily return to card-shaped, since that's the only shape
  (0,0,1,1) can ever produce.
- **Zooming all the way out reproduces the exact opening state because
  it's the exact same computation, not a special case for it.** The
  window size at ANY moment is `_window_size_for_crop(current _view_rect)`;
  the opening size is the identical function applied to the starting
  value of that same rectangle. Confirmed headlessly: two deep,
  intentionally odd-shaped (non-card) reticle zooms in a row (reaching
  roughly 700x), then 120 wheel-zoom-out ticks, land on a window size,
  aspect ratio, multiplier (1.0), and crop rectangle ((0,0,1,1)) all
  *exactly* matching the freshly-opened state -- and every one of those
  120 ticks shrinks by a bounded, gradual amount, with no single-tick
  jump bigger than 2x anywhere in the unwind.
- **Deliberately not built yet: panning.** A real image viewer lets you
  drag to pan once zoomed in past what fits on screen. `_view_rect`'s
  position (not just its size) is tracked as real, adjustable state
  specifically so wiring up an actual pan gesture later is a small,
  scoped addition -- but it isn't wired to a gesture in this round, both
  because it has zero visible effect on a flat color placeholder and
  because it would need to coexist with plain-drag's EXISTING job (moving
  the whole window around the screen) in a way not yet specified by any
  request so far.
- Layers on top of the click+drag-to-move-the-window gesture unchanged;
  Ctrl+drag is still what distinguishes "start a reticle selection" from
  a plain window move. The translucent blue selection overlay (same
  accent color used for selection elsewhere in the app) still stays
  visible while dragging, and Escape still cancels an in-progress
  selection specifically rather than closing the whole viewer.
- `grabMouse()`/`releaseMouse()` still bracket a reticle drag, same
  reasoning as before: the window can be much larger than a small fixed
  starting size now that it opens fit-to-screen, so a real drag gesture
  crossing outside its bounds mid-gesture is even more likely than it
  was, not less.

### Design journey (worth keeping -- two earlier attempts, each fixed a real bug and revealed the next one)

**Attempt 1** treated the reticle-cropped region and the window's own
pixel size as one and the same: a reticle zoom just set the window to
fill the screen directly. This worked once, but a SECOND reticle zoom
(or any wheel-zoom afterward) had no reliable way to combine with the
first -- there was no persistent "how much is currently cropped" state
to compose against, so repeated zooming didn't stack sensibly and the
zoom label had nothing accurate to read from.

**Attempt 2** introduced two separate variables to fix that: `_zoom` (a
plain scale factor driving window pixel size, adjusted by the mouse
wheel) and `_view_rect` (a normalized crop fraction, narrowed only by
reticle selections). This fixed the composition problem, but created a
new one: a reticle zoom PEGGED `_zoom` to whatever fit the screen and
left `_view_rect` to keep narrowing independently forever. Since wheel-
zoom only ever touched `_zoom`, never `_view_rect`, scrolling out after
several reticle zooms shrank the WINDOW while the CROP stayed frozen at
whatever a deep chain of reticle zooms had left it at -- so the displayed
multiplier (driven by the frozen crop) could report a huge number even
once the window was smaller than its own original starting size, wheel-
zooming out jumped disproportionately right after a reticle zoom (since
`_zoom` had just been reset to a big screen-relative value with no
smooth path back down), and the window was force-fit to the CARD's own
aspect ratio always, fighting against reticle selections that were
legitimately a different shape. Three symptoms, each traced back to the
same root cause: two variables that were each supposed to represent
"how zoomed in are we," only one of which (the crop) was actually real.

**The actual fix (this round)**: delete the second variable. Let the
crop alone (`_view_rect`) drive both the window's size and the displayed
number, so they can never independently drift -- see the final design
above. The general lesson, worth remembering for the next time a UI
shows two numbers/states that both claim to describe "the same thing"
from different angles: check whether one of them can be deleted entirely
and DERIVED from the other, rather than trying to keep the two in sync
after the fact.

## Card detail popup: Type-column alignment overhaul, QGridLayout rewrite (earlier round)
Three rounds of alignment fixes on the same underlying complaint ("Type's
caption/value don't visually line up with Edition/Language's column"),
the first two of which didn't actually work despite looking correct on
paper — worth reading in full if this class of bug shows up again
elsewhere, since the general lesson generalizes past this one dialog.

- **The fix that actually worked**: all three stat rows (Type/Mana,
  Edition/Rarity/Price, Language/Condition/Foil) now live in ONE
  `QGridLayout` instead of three independent `QHBoxLayout`s. A
  `QGridLayout` guarantees every cell in the same COLUMN shares the exact
  same pixel width across every row — a hard invariant Qt itself enforces
  — instead of something reconstructed via a formula that has to
  correctly guess how a DIFFERENT, independently-laid-out row divides up
  its own width. Type's own grid cell spans columns 0+1
  (`columnSpan=2`), giving a long type line (e.g. Thalia's "Legendary
  Creature — Human Soldier") room to grow rightward into column 1's
  otherwise-empty space before it needs to wrap, instead of wrapping
  early or truncating. Confirmed via actual headless instantiation +
  measuring real rendered pixel positions (`QFontMetrics.boundingRect`,
  `.mapTo()`), not just re-deriving the algebra again — see "Debugging
  journey" below for why that mattered.
- **Column widths are explicitly LOCKED** to a fixed pixel value shortly
  after the dialog's first real layout pass
  (`CardDetailDialog._lock_column_widths()`), rather than left to
  `QGridLayout`'s own stretch-based sizing. Necessary, not just tidy:
  `QGridLayout` apparently consults a cell's uncapped `minimumSizeHint()`
  when deciding how wide a COLUMN itself needs to be, even when every
  individual cell already has an explicit `setMaximumWidth()` — so
  selecting a long Language/Condition value could still widen the whole
  column, a failure mode the OLD per-row `QHBoxLayout` structure never
  had (each row solved its own width independently, with nothing to
  reconcile against a different row's content). Locking BOTH
  `setColumnMinimumWidth()` and `setMaximumWidth()` to the identical
  number removes that degree of freedom entirely. **This fix is
  explicitly justified by the dialog being a fixed-size window (900x560,
  never resized)** — see NOTES.md's new "variable text scaling & DPI"
  entry for why this needs revisiting before the app can support
  different font sizes / accessibility scaling / DPI settings.
- Value buttons (Edition/Price/Language/Condition) no longer draw a
  dropdown arrow at all — the earlier fix reserved space for one via
  `padding-right` + a `menu-indicator` CSS rule, which was itself the
  root cause of an even earlier "text drifts left" bug two rounds ago.
  Removed entirely; the value text itself is the click target.
- Apply button restyled to match `CardDatabaseView`'s Inventory/Wishlist
  toggle buttons (bright fill, rounded border) instead of a flat default
  `QPushButton`, renamed from "Apply to Inventory" to just "Apply," and
  given explicit spacing above it matching the gap between stat rows.
- Card pane header text removed from the window's own
  title-bar-substitute (`frameless_dialog.py`'s `_TitleBar` gained a
  `show_title` parameter) — the card's NAME is now shown once, styled as
  the Card pane's own header, instead of duplicated in both places.
- Every pane's caption ("Legality", "Rulings") is now horizontally
  centered with a fixed gap before its content (shared via
  `_pane_layout()`), instead of defaulting to left-aligned with no gap.
- Two named spacing constants (`CAPTION_VALUE_SPACING`,
  `STAT_ROW_SPACING`) replace what used to be inconsistent hardcoded
  literals, specifically so "gap between a caption and its own value" and
  "gap between one stat row and the next" can never drift back to being
  the wrong way around relative to each other.

### Debugging journey (worth keeping — three attempts before the real fix)
1. **First attempt**: derive Type's anchor point purely from Type's own
   width (`width / 4`). Wrong because gameplay_row (Type + Mana, one
   inter-column gap) and a real 3-column row (two gaps) divide up their
   width differently — "1/4 of Type's own width" answers a structurally
   DIFFERENT question than "half of a real column's width," even though
   the two numbers looked deceptively close.
2. **Second attempt**: read a live sibling widget's width directly
   (`edition_field.width()`) at the exact moment of computing the
   anchor. Reasonable in principle, but timing-fragile in practice — it
   depended on a completely separate, independently-laid-out widget
   having already settled into its FINAL geometry, and nothing actually
   guaranteed that ordering relative to a deferred
   `QTimer.singleShot(0, ...)` refresh (Qt doesn't promise a 0ms timer
   fires after every pending layout pass). The person testing this
   confirmed it made no visible difference.
3. **Third attempt**: an analytical correction formula
   (`anchor_center = width/4 - spacing/6`) derived from first principles
   to account for the different gap counts between the two row shapes.
   Checked out exactly on paper — and STILL didn't fix the visible
   problem, because it depended on an assumption (Qt's actual default
   inter-column spacing matching what the code assumed) that had never
   actually been verified against a real render.
4. **The actual fix** required two separate things working together: (a)
   restructuring to a real `QGridLayout` so column-1 width became ONE
   authoritative number instead of something independently re-derived
   per row, confirmed via `QGridLayout.cellRect()`; and (b) — critically
   — actually instantiating the dialog headlessly
   (`QT_QPA_PLATFORM=offscreen`) and measuring REAL rendered pixel
   positions instead of trusting the derivation a fourth time. That
   measurement caught a genuinely separate, previously invisible bug:
   the anchor math was being applied via `setContentsMargins()` on a
   label whose own coordinate origin was already shifted ~4px by
   `StatField`'s own inner layout margin — a real, exact, measured error
   that no amount of re-deriving the algebra would have caught, since
   the algebra itself was internally consistent; the bug was in a
   completely different, uninspected coordinate-space assumption.
- **General takeaway**: alignment bugs across independently-laid-out Qt
  layouts (two separate `QHBoxLayout`s, in this case) resist being fixed
  by formula alone, however carefully re-derived — two layouts computing
  "the same" quantity independently can silently disagree for reasons
  (a hidden margin, an unverified spacing assumption, a coordinate-space
  mismatch) invisible to algebra done on paper. When the bug IS
  alignment specifically, prefer giving the two things a SINGLE SHARED
  AUTHORITY to agree with (one real shared layout, not two independent
  ones computing matching-but-separate answers) over trying to reconcile
  two calculations — and verify any pixel-level claim against actual
  rendered widget geometry (`.geometry()`, `.mapTo()`,
  `QFontMetrics.boundingRect()`), not just re-checked math. This
  generalizes the existing "logic runs but nothing visibly happens"
  lesson from the filter-menu keyboard-nav saga (see NOTES.md) to a new
  failure class: logic that LOOKS provably correct on paper and still
  isn't, because the paper version omitted a real coordinate-space detail
  only actual rendering reveals.
- **Separate, smaller lesson worth keeping on its own**: `setMaximumWidth()`
  on a widget doesn't reliably stop `QGridLayout` from wanting to grow
  that widget's COLUMN based on the widget's own uncapped
  `minimumSizeHint()` — a failure mode the old independent-per-row
  structure never had. If a `QGridLayout` column mysteriously grows
  despite an apparent per-widget max-width cap anywhere else in this app
  later, this is the mechanism to suspect first; the fix is locking BOTH
  `setColumnMinimumWidth()` and `setMaximumWidth()` to the identical
  value, not just capping the widget.

## Card Database merge + filter-menu keyboard navigation fixed (earlier round)
- **All Card Database and Inventory are now ONE tab, "Card Database."**
  Same realization as the earlier Wishlist collapse: Inventory was always
  just "the full catalog, filtered to Have > 0" — `mock_data.py` had two
  functions (`get_all_cards()`, `get_inventory_cards()`) returning
  identically-shaped data under different names. `get_inventory_cards()` is
  gone; there's one dataset now, with Have/Want filtering applied live via
  the UI instead of baked into which function got called.
- New `card_database_view.py` / `CardDatabaseView` wraps a `CardTableView`
  with a button row above it: **Inventory** and **Wishlist** toggle
  buttons (shortcuts for excluding Have/Want == 0 — identical in effect to
  right-clicking that column and unchecking "0," just faster, and both can
  be on at once since they filter independent columns), plus a **Columns**
  dropdown for column visibility. `CardTableView` itself didn't need to
  change at all for this — the button row lives in a wrapper composing a
  table, the same shape `DeckViewerView`/`TagTreePanel` already use for
  composing a `TreePane`. This also gives the still-parked flexible search
  engine (see NOTES.md) an obvious future home: `CardDatabaseView`'s button
  row already reserves space for it via `addStretch()`.
- **Inventory/Wishlist buttons are real two-way toggles**, not one-shot
  actions: clicking one updates the model; a filter change from ANY source
  (the button, or manually via the header's own right-click checklist)
  updates both — so the buttons never silently show a state that isn't
  actually applied. Implemented via two new generic `CardTableModel`
  methods, `is_value_excluded()` / `set_value_excluded()`, that the header
  checklist's own toggle handler now also routes through (one
  add/discard-from-set implementation instead of two copies that could
  drift).
- **"Show Columns" is no longer duplicated into every column's right-click
  menu** — it was rebuilt identically inside each one. It's now the
  standalone Columns button above, built via a new
  `SplitDropdownHeader.build_show_columns_menu()`; right-clicking a
  non-filterable column header (Checkbox, Actions) now correctly shows no
  menu at all instead of an empty popup.
- **Filter-menu search box keyboard navigation, actually fixed this time**
  — this took several real dead ends worth recording (see "Debugging
  journey" below): Up/Down/Tab/Shift+Tab now all move the highlighted
  checklist value (Tab and Shift+Tab share the exact same logic as Up/Down,
  which is what makes them automatically skip the disabled "Filter by X"
  label and any submenu-opening action — that logic already only
  considers checkable actions), clamped at both ends, correctly skipping
  values hidden by the search-narrowing text. Space toggles the currently
  highlighted value once you've navigated to one (typing a space before
  that still works normally, e.g. for "Lightly Played"). Enter still
  applies the typed text directly as a filter, as before.
- Added real `QMenu` / `QMenu::item:selected` styling to `main.py`'s global
  stylesheet — previously absent entirely, which turned out to be the root
  cause behind the keyboard-nav symptoms (see below).

### Debugging journey (worth keeping — this was genuinely tricky)
Three fix attempts, in order, each ruled something out:
1. **First attempt**: moved Up/Down/Enter handling from `_MenuSearchBox
   .keyPressEvent()` to an app-level `eventFilter`, hypothesizing `QMenu`'s
   own internal arrow-key handling was intercepting the keys before
   `keyPressEvent` ever ran (mirroring how `collapsible_pane.py` already
   solves an analogous Tab-interception problem). Verified correct in
   isolation (a headless test confirmed `activeAction()` moved through
   visible actions correctly) — but the test was flawed: it called
   `app.sendEvent(box, ev)` directly, which *forces* the event's receiver
   to be the search box by construction. That never actually exercised the
   real ambiguity, and the fix had no effect in a real window.
2. **Second attempt**: dropped the `watched is self` condition in the
   event filter entirely, hypothesizing Qt's real popup keyboard-grab
   routing might not report the search box as `watched` the way a manually
   constructed test event does. Verified this time with a test that
   deliberately passed an unrelated decoy object as `watched` — proving
   the broadened filter no longer depended on receiver identity. Still had
   no effect in the real window.
3. **The actual fix**: reframed the symptom. "Nothing happens" didn't
   necessarily mean the events weren't arriving — `main.py`'s global
   stylesheet had never styled `QMenu` at all, and once *any* custom QSS is
   applied to an application, Qt's style engine stops relying on the
   native platform style's automatic hover/selected rendering for anything
   not explicitly re-declared. So `setActiveAction()` may have been
   working correctly the entire time, just invisibly. Adding explicit
   `QMenu::item:selected` styling (reusing the app's existing `#3d6a8f`
   selection color) made the — already-correct — navigation logic visible.
   Separately, Space-to-toggle had never been implemented at all: real
   `QMenu` only handles Space when the menu itself holds actual keyboard
   focus, which this design deliberately never grants (focus stays on the
   search box so typing keeps narrowing the list) — so Space was always
   just a literal character typed into the field.
- **Takeaway for next time a "the events must not be reaching my handler"
  bug shows up**: check whether the logic is actually running and simply
  invisible (missing QSS state styling is an easy thing to overlook once
  *any* custom stylesheet is in play) before assuming the event routing
  itself is broken.

## Detail popup, mono-color, and keyboard-parity fixes (earlier round)
- Fixed the actual bug behind the "inconsistent" alignment complaint: the
  reserved-width calculation for centered dropdown fields only subtracted
  the arrow's space ONCE, when symmetric padding means it needed subtracting
  TWICE — this made short values look fine but medium-length ones (Price,
  "Lightly Played") wrap/elide against the wrong width. Fixed uniformly for
  every clickable+centered field, not case-by-case.
- Type's value now uses the same indent magic number (16px) as the
  centered fields' effective content start, instead of an approximate guess.
- Switching price source no longer resets your selected language — it was
  being re-derived from print data on every refresh instead of just being
  displayed from the tracked selection.
- Added a real "Apply to Inventory" button: edition/language/condition/foil
  changes now actually write back into the card's real collection entry
  (previously these were preview-only with nowhere to commit to).
- Mana Cost filtering redesigned again: unchecking a single color now
  correctly hides multicolor cards containing it too (previously only an
  exact mono-color match was excluded) — implemented via a dedicated
  per-color-letter exclusion set rather than the generic value-checklist
  mechanism, which structurally couldn't express "any card containing
  this color."
- Filter-menu search box: fully rewritten navigation — Up/Down now move
  QMenu's highlight directly via `setActiveAction()` without ever
  transferring real keyboard focus away from the search box (the previous
  focus-handoff approach was fragile with QWidgetAction involved). Enter
  applies the typed text as a real filter and closes the menu.
- Tag-apply widget: restored a visible current-item indicator (the app's
  global "remove focus rectangle" style was suppressing it here too) and
  set initial focus/current-item so arrow-key navigation works immediately;
  confirmed Space already natively toggles the current item's checkbox.
- Table: added Excel-familiar shortcuts — F2 (Qty is now genuinely
  editable), Shift+Space (select row), Ctrl+Space (select column),
  Ctrl+Home/End, Ctrl+Shift+Arrow (extend selection to an edge, with known
  simplifications noted in NOTES.md).

## Alignment & interaction fixes (earlier round)
- Detail popup: Type's value now has a left indent so short values ("Instant")
  don't look stranded far from the caption above them; Type and Condition
  wrap onto multiple lines instead of truncating; Language and Mana Cost
  wrap too (needed for entries like "Chinese Simplified").
- CardDetailDialog and TagApplyDialog now share one `frameless_dialog.py`
  base (no OS title bar, custom draggable title bar, click-outside-closes)
  instead of duplicating that logic.
- Table headers: the Edition/Rarity sort arrow and the Type/Mana/Price
  dropdown arrow no longer shift the label text — labels are drawn at a
  fixed position and the arrow is a separate overlay, not part of the
  centered/positioned text itself.
- Mana Cost filter redesigned: the checklist now shows only the 5 mono
  colors (no Colorless, no multicolor combos) — colorless is structurally
  exempt from the checkboxes rather than specially skipped, and "Monocolored
  only" is a real persistent toggle (not a one-shot preset) that combines
  with the color checkboxes rather than overwriting them.
- Filter-menu search box: arrow-key navigation rewritten — Up is clamped
  (does nothing), Down jumps directly to the first *visible* checkable
  action via `setActiveAction()` instead of re-dispatching a raw key event
  through the menu (which was landing on hidden/narrowed-out items and
  bouncing focus back to the search box).
- Right-click on a card row no longer drops a multi-row selection when the
  click lands on a different column than the one originally selected —
  right-button presses now skip Qt's default click handling entirely,
  leaving selection changes on right-click to our own deliberate logic.
- Tag-apply widget: now frameless (matches the card detail popup), and
  fully-checked tags are visually highlighted (bold + accent color).
- Parked for later (see NOTES.md): a search box inside the tag-apply
  widget itself, and user-assignable per-branch hotkey letter sequences
  for fast tag navigation.

## Detail-popup layout + filter-menu polish (earlier round)
- Detail popup: Type's caption now centers within a notional 1/3-of-row
  slot (matching every other caption's rhythm) even though its VALUE still
  spans the full 2/3 width it needs.
- Detail popup: Type and Condition now wrap onto multiple lines instead of
  truncating with "…" when text is too long for their space (Condition
  required a manual line-breaker since QToolButton has no native word-wrap).
- Detail popup: centered dropdown fields (Edition/Price/Language/Condition)
  now actually look centered — they were only getting right-side padding
  reserved for the arrow, which silently shifted the "centered" content box
  left; matching left padding fixes it.
- Filter menus: the search box now auto-focuses the instant you right-click
  (no need to click into it first), has a visibly different border when
  focused vs. not, and gives placeholder text a bit of left margin.
- Filter menus: pressing Up/Down in the search box hands focus to the menu
  and forwards that same keypress, so you can type a few characters to
  narrow the list then immediately arrow-key into the results.
- Mana Cost's filter now has a "Monocolored only" preset above a separator
  — checking it sets every single-color entry on and colorless/multicolor
  off in one action, so you can then fine-tune by unchecking specific colors.
- Price is now filterable too (with the same search box), consistent with
  every other column.

## Tag-apply widget (earlier round)
- **Right-click any card row** in All Card Database or Inventory to open
  it: a checkbox tree mirroring the Tag Database. Both folders AND leaf
  tags are checkable (a card can carry the broad "Removal" tag, a specific
  "Destroy"/"Exile" subtag, or any combination independently — matches the
  original spec's example directly).
- Right-clicking a row that's part of your current multi-selection keeps
  the whole selection (bulk-tag several cards at once); right-clicking
  outside it selects just that row first (standard Explorer-style behavior).
- Checkboxes start **tri-state**: fully checked if every selected card
  already has that tag, unchecked if none do, partially-checked if it's
  mixed. A partial checkbox left untouched is skipped entirely on Apply —
  only tags you explicitly resolve to fully checked/unchecked get applied
  across the whole selection.
- Backed by a new `tag_assignments.py` — a simple card-name → tag-id store,
  keyed by tag ID specifically so renaming a tag later never orphans
  existing assignments.

## Filter improvements + layout fixes (earlier round)
- Card detail popup: rows 2 and 3 (Edition/Rarity/Price, Language/
  Condition/Foil) now actually split into even thirds and center within
  them — the previous version used fixed pixel widths plus trailing empty
  space, which is why centering didn't visibly do anything.
- Card detail popup: a bit more space below the art, and a thin separator
  between the stat rows and the oracle text.
- Every column's filter menu now has an Excel-style search box that
  narrows the checkbox list as you type — useful once a column has many
  distinct values (quantities, etc).
- Mana Cost's filter now offers color categories (White, Blue, Colorless,
  multicolor combos like "U/B", ...) instead of literal mana-cost strings —
  this is what makes "show me mono-white cards only" possible.
- Power/Toughness missing values (non-creatures) now show as "(none)" in
  the filter checklist instead of being silently excluded from it, so
  "show only creatures" / "show only non-creatures" is now a real filter
  option. Added a card with variable power/toughness ("*", Endless One) so
  this is tested against real non-numeric data, not just claimed to work.
- Theming (system accent colors, light/dark presets) and a real flexible
  search engine are explicitly parked in NOTES.md rather than attempted as
  quick fixes — both are real subsystems, not polish.

## Repurposing pass (earlier round)
- **Wishlist is gone as a standalone tab.** It's replaced by "All Card
  Database" -- the full browsable catalog, showing both Have and Want
  counts for every card. Inventory is the same shape of data, filtered to
  what you actually own. Isolating "what I want" is now just: right-click
  the Want column on either table, uncheck "0". Tab order changed
  accordingly: Tag Database, All Card Database, Inventory, Deck Viewer
  (Ctrl+1..4) -- All Card Database took Inventory's old slot, Inventory took
  Wishlist's.
- Header background is now a deliberately darker near-black (matching what
  used to show up by accident before it got "fixed" to match the rows) --
  applied uniformly across plain and custom-painted headers alike.
- Card detail popup: Edition/Rarity/Price and Language/Condition rows are
  now center-aligned across the board, instead of left-aligned in a way
  that read as inconsistent next to the Type/Mana row's intentional
  left/center split.

## Polish pass (earlier round)
- Side nav buttons now highlight the instant you press them, not after a
  visible dashed-focus-rect-then-highlight delay (the delay was a native
  focus rectangle Qt draws before our own styling takes over — removed via
  `outline: 0`, plus an explicit `:pressed` style for immediate feedback).
- Table headers are now visually uniform — the custom-painted ones
  (Edition/Rarity split, Type/Mana/Price dropdown arrows) were reading their
  background from the widget's base palette instead of the app's actual
  stylesheet color, which are two different things in Qt; they now share
  one explicit color constant with the plain headers.
- Added a cross-reference count column: Inventory shows "Wished" (how many
  you've wishlisted), Wishlist shows "Have" (how many you own) — sortable,
  toggleable via Show Columns like any other.
- Detail popup: Rulings pane now has a proper visible border (QListWidget
  wasn't in the app's bordered-widget style rule at all — now is) and is
  guaranteed at least as wide as the Legality pane.
- Detail popup: Language/Condition/Foil moved to their own third metadata
  row, separate from Edition/Rarity/Price, so the card pane isn't
  overcrowded.
- Detail popup: Foil now reads "Yes"/"No" instead of "On"/"Off".
- Detail popup: the Type/Mana Cost row is now a true proportional 2:1
  split of the row's actual width (via layout stretch, not fixed pixel
  guesses) — Type left-aligned, Mana Cost centered.

## Frameless detail popup, Power/Toughness split, broader type filter
- Opening the detail popup now cancels any hover popover already showing
  or waiting out its delay timer.
- Tree panes (Tag Database / Deck Viewer): removed the "+ Item"/"+ Folder"
  toolbar buttons (right-click menu and Ctrl+N/Ctrl+Shift+N cover the same
  ground) and made tab-switching set focus deterministically — this is
  what actually fixes Tab not collapsing the pane on the very first press.
- Removed the native dashed "focus rectangle" Qt draws on top of selected
  items (kept the color highlight, which was already the intended look).
- Detail popup: Legality pane now sizes itself to the widest text that can
  actually occur, with word-wrap as a fallback, instead of a cramped
  proportional share of the width.
- Detail popup: removed the OS title bar entirely — frameless window with
  its own thin title bar (name + close button), draggable by that bar,
  closes automatically when you click anywhere in the main app window
  (verified this doesn't misfire when clicking the popup's own dropdown
  menus, which are technically separate top-level windows).
- Detail popup: added Language and Condition dropdowns and a Foil toggle
  alongside Edition/Rarity/Price.
- Table: Power and Toughness are now independent columns (sortable/
  filterable separately) rather than one combined "P/T" column.
- The Type column's right-click filter checklist now offers broad
  categories (Creature, Instant, ...) instead of full literal type lines.
- Parked for later (see NOTES.md): an options/settings window with
  externalized per-language string files, "have"/"want"/"in-deck" count
  columns, and default-add behavior with variant grouping.

## Header filter, column picker, group-by
- **Right-click any header** in Inventory/Wishlist: for most columns, a
  checklist of every distinct value in that column (uncheck a value to hide
  matching rows — check it again to bring them back), plus a **"Show
  Columns"** submenu to toggle any column's visibility live.
- **Type / Mana Cost headers** now have the same ▾ dropdown arrow Price
  has — click it for **"Group by Type"** / **"Group by Color"**. Grouped
  view inserts a full-width sub-header bar between groups (Deckbox-style:
  Creatures, then Instants, etc.; Colorless, then White, Blue, ... then
  multicolor combos like "U/B"). Click again to un-group.
- Group-header rows are inert — not selectable, not checkable, don't open
  the detail popup or hover popover.
- Known simplification: the Edition/Rarity column's filter checklist works
  off the Set only (not Rarity); Price isn't filterable this way since it's
  continuous data — real range filtering is planned as part of the
  upcoming Search feature.

## Card detail popup
- Double-click any row: name, clickable art placeholder (opens a separate
  zoomable/draggable window), fixed-position stats (Type / Mana Cost /
  Edition / Rarity / Price), oracle + flavor text, Legality and Rulings tabs.
- Edition and Price fields are dropdowns — switching editions updates
  rarity/price/flavor text; switching price source updates the price shown.

## Tree tabs (Tag Database / Deck Viewer)
- Full folder/item CRUD: create, rename (F2), delete (with confirmation),
  drag-and-drop, Ctrl+X/C/V (with cycle-detection and same-name dedup),
  right-click menu with icon color picker.
- Collapsible/resizable side pane: drag the divider, click the tall arrow
  on it, press Tab, or click into the right-hand content area.

## What this is
A Deckbox-style layout: a tab strip (Tag Database / Card Database / Deck
Viewer) on the left driving swappable central views. Card Database is a
spreadsheet (the full catalog, with Inventory/Wishlist/Columns toggle
buttons above the table as filter shortcuts); Tag Database and Deck Viewer
are collapsible folder/item trees. Runs on mock data — no real database or
images yet.

## Run it
```bash
pip install PySide6
python main.py
```

## Try — spreadsheet tab (Card Database)
- **Ctrl+2** — jump to Card Database.
- **Inventory / Wishlist buttons** (top of the table) — toggle excluding
  Have == 0 / Want == 0; both can be on at once. Same effect as
  right-clicking the Have or Want column and unchecking "0," just faster,
  and the buttons stay in sync either way — toggle one on, then manually
  uncheck "0" again via the header's own right-click menu, and the button
  un-highlights to match.
- **Columns button** — dropdown to toggle any column's visibility (used to
  be duplicated into every column's own right-click menu; now lives here
  only).
- **Click / Ctrl+click / Shift+click** cells — Excel-like multi-selection.
- **Ctrl+C** — copy the selection as tab/newline-separated text.
- **"Edition / Rarity" header** — click left half to sort by set, right half
  by rarity.
- **"Price" header** — click the ▾ to pick a price source; click elsewhere
  to sort by price.
- **Right-click any filterable column header** — a search-narrowable value
  checklist; type to narrow, **Up/Down or Tab/Shift+Tab** to move the
  highlighted value (clamped at both ends, skips anything hidden by the
  search text), **Space** to toggle the highlighted value once you've
  navigated to one, **Enter** to apply the typed text directly as a filter.
- **⋯ button** — stub actions menu. **Hover a card's Name** — popover with
  placeholder art + text.
- **Right-click a card row** (or a multi-selection of rows) — opens the
  tag-apply dialog: check/uncheck tags from the Tag Database, Apply to
  every selected card at once.

## Try — tree tabs (Tag Database / Deck Viewer)
- **Ctrl+1 / Ctrl+3** — jump to Tag Database / Deck Viewer.
- **Ctrl+N / Ctrl+Shift+N** — create a new item/folder; it's immediately
  renameable with all text pre-selected, so typing replaces the name right
  away. (Also available via right-click.)
- **F2** — rename the selected item. **Delete** — delete selected item(s).
- **Drag and drop** — reorder/reparent items (drop onto a folder to move
  inside it). **Ctrl+X / Ctrl+C / Ctrl+V** — cut/copy/paste as an
  alternative to dragging.
- **Right-click** — full context menu, including a color-swatch submenu to
  recolor an item's icon.
- **Click the small ◂/▸ arrow at the top of the divider** between the tree
  and the content area — collapses/expands the tree pane. **Tab** — same
  toggle, from anywhere in that view. **Clicking anywhere in the right-hand
  content area** — also collapses the tree pane, to reclaim space once
  you've picked something.

## What's deliberately NOT here yet
- Real card images.
- Any real database — the tree/table data all comes from hardcoded seed
  data (`mock_data.py`, `deck_viewer.py`, `tag_tree.py`); each has one clearly
  marked function/constant that gets swapped for a real query later.
- Tag-based card filtering, deck contents view, column right-click filtering
  and grouping, card detail popup, and the tag-apply widget — all upcoming.
- Drag-to-resize specifically on the Edition/Rarity and Price header cells
  (documented limitation in `card_table.py`).
- Delete confirmation dialogs (documented limitation in `tree_pane.py`).
