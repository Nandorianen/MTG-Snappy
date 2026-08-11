## Filter menu follow-ups: Type's search box, Price Source keyboard access, Clear Filter cleanup (this round)

Three more real, reported problems on top of last round's filter work:

- **Type's search box now actually searches the full type line.** Last
  round's word-based checklist (Artifact/Creature/Legendary/... checkable
  independently) was correct and unchanged -- what still didn't work was
  typing free text and pressing Enter: it could only match the checklist's
  own short words, never a subtype ("Bird," "Human Soldier") or an
  arbitrary substring. Type's Enter now applies a typed EXPRESSION against
  the card's full raw type line (the same machinery `EXPRESSION_COLUMNS`
  use), layered on top of the checklist's own word exclusion -- both must
  pass. Confirmed: `type~artifact` finds "Baleful Strix" (Artifact
  Creature), `type~legendary` finds "Thalia," `type~bird` finds a subtype
  past the em dash.
- **"Price Source" is a real drop-to-the-side submenu again, now properly
  keyboard-operable.** A first attempt replaced it with flat checkable
  actions to fix navigability, but that traded away the submenu affordance
  entirely -- reverted. A second attempt kept the real submenu and tried
  to let Qt's own native nested-popup keyboard handling take over once
  opened via `.exec()`, but that raced against an undocumented Qt side
  effect (highlighting an action with a submenu opens it immediately, on
  its own) -- causing a visible position jitter and Left/Enter/Space
  becoming unreliable after the first use. **Fixed properly** by no longer
  trusting native routing at all: this box now drives the submenu's own
  Up/Down/Left/Enter/Space itself, the same way it already drives the
  parent menu's, adopting whatever Qt already auto-opened rather than
  re-showing it. Reachable via Down (right after Clear Filter, same
  position "Group by Type" occupies on checklist columns), opened via
  Right arrow or Space with its first item highlighted immediately, Left
  or Escape backs out cleanly and repeatedly, Enter or Space both select.
  See NOTES.md for the full diagnosis.
- **"Clear Filter" and "Clear All Filters" now also forget each column's
  remembered search-narrowing text**, not just the real filter state --
  previously a cleared column's search box could still come back prefilled
  with old text on next open. New `CardTableHeader.
  clear_all_search_memory()` and `CardTableView.clear_all_filters()` (the
  latter now what both the CardDatabaseView button and Ctrl+Alt+F bind to,
  instead of the model method directly) are the two places this is fixed.

## Filter menu keyboard-nav fixes, Type filter redesign (earlier round)

Follow-up round fixing real, reported problems in last round's filter
overhaul:

- **The typed EXPRESSION box (Have/Want/Power/Toughness/Price/Name) now
  shares the checklist columns' own keyboard-navigation class
  (`_MenuSearchBox`)** instead of being a bare `QLineEdit`. It was missing
  ALL of that class's arrow-key interception, so Down would fall through
  to QMenu's own native handling and could land back on the box itself --
  reported as "pressing Down goes back to the textbox, skipping Clear
  Filter." Fixed by construction: every filter box in the app is now the
  same class, so this failure mode can't recur elsewhere either.
- **Every filterable column's menu now has a "Clear Filter" action, right
  below its search/expression box** -- previously only the expression
  columns had one. It's a proper keyboard-navigable stop (Down from the
  box reaches it first; Space activates it), not just a mouse target.
- **Pressing Up now correctly collapses the menu again**, on every column
  -- this had quietly stopped working for the expression columns since
  they never ran through the collapse-aware navigation code at all before
  this round's `_MenuSearchBox` reuse.
- **Focusing any filter/search box now selects its existing text**, so a
  single keystroke replaces a previous search or expression outright
  instead of needing a manual select-all first.
- **Checklist columns' typed search-narrowing text is now remembered
  across reopens** (`CardTableHeader._search_box_memory`), matching how
  the expression box's typed filter already persisted via
  `get_column_expression()` -- previously only expression columns "kept"
  what was typed, which read as an arbitrary inconsistency between menus.
- **Fixed a real bug in Type filtering**: it could never find "Artifact"
  in "Artifact Creature" or "Legendary" in "Legendary Creature," because
  it was reusing the single-category function built for GROUPING (which
  deliberately collapses a type line to one bucket and strips supertypes
  entirely). Type's filter is now WORD-based (`_type_words`,
  `type_excluded_words`) -- the same set-membership-exclusion shape Mana
  Cost's own color filter already used for the identical underlying
  problem -- so a card matches a filter on ANY of its type/supertype
  words independently. Group by Type's own grouping logic is completely
  unaffected; only filtering was ever wrong.

## Column split + filter overhaul, menu focus-leak fix (earlier round)

- **Edition and Rarity are now two ordinary, independent columns**, not one
  custom-painted "Edition / Rarity" section drawn as two independently-
  sortable halves. Each sorts, filters, and resizes exactly like any other
  column now — the old "Ed"/"Rar" split-section painting
  (`_paint_split_section`) and its special-cased click/keyboard handling are
  gone. `SplitDropdownHeader` is renamed `CardTableHeader` to match (its
  namesake behavior no longer exists). This was a space-saving choice, not a
  load-bearing design decision, so removing it didn't touch any data model —
  see NOTES.md for the one thing worth remembering when touching either
  column going forward: rarity belongs to a specific PRINTING, never the
  card in the abstract, so code that reads/changes it should always do so
  alongside a specific edition (the card detail popup's edition switcher
  already gets this right).
- **Value-checklist filters are gone for the columns where they didn't
  scale**: Have, Want, Power, Toughness, Price, and Name now use a typed
  EXPRESSION box instead of a list of every distinct value currently in the
  table (an unbounded quantity, a continuous price, and thousands of card
  names were never going to work as a browsable checklist). Supports `>`,
  `>=`, `<`, `<=`, `!=` against a number, or a bare case-insensitive
  substring match (wildcards at both ends, automatically) against text —
  which mode applies is auto-detected per typed expression by whether the
  operand parses as a number, so there's no separate "numeric mode" toggle
  and no quoting needed to force text matching. A card that isn't numeric
  for a given column (Power's "*") simply never matches a numeric
  comparison. Type, Mana Cost's color, Edition, and Rarity keep the
  original checklist-with-search-box UI — they're genuinely small, bounded
  category sets, which is exactly the case a checklist is the right tool
  for. The Inventory/Wishlist toggle buttons are unaffected: they still
  drive Have/Want's own "0" exclusion the same way as before, and a typed
  expression on top of that narrows further rather than replacing it.
- **Fixed a real, reported bug**: a filter menu's search/expression box
  could keep showing a blinking text cursor after the menu had closed.
  Root cause: every filter menu is a fresh `QMenu` parented to the header
  (which lives for the whole session), and nothing ever explicitly deleted
  a closed one — they just piled up, hidden, forever. Fixed with
  `menu.deleteLater()` right after `menu.exec()` returns (both in the
  header's own context-menu path and `CardDatabaseView`'s standalone
  Columns-button menu, which has the identical shape), plus an explicit
  `clearFocus()` wired to each search/expression box's `aboutToHide` rather
  than relying on Qt's implicit focus handling to get to it eventually.
- Parked as an explicit TODO (see NOTES.md), not built this round: a
  folder-grouped edition-picker widget (editions listed by name/code/year,
  collapsible by block/era) to eventually replace today's flat Edition
  checklist here AND `data_management_dialog.py`'s equally-flat Card Images
  edition picker — both have the same "a real Scryfall edition list is
  thousands of entries, not nine mock set codes" scaling problem, and both
  should share one widget rather than growing two separately.

## Keyboard access for table headers (this round)

Headers were completely mouse-only until now -- no way to sort, filter, or
open a column's menu without clicking. Fixed by making a column header
itself keyboard-focusable, unified with the meta-button row's existing
arrow-key/Tab conventions (card_database_view.py):

- **Alt+Shift+Up or Alt+Shift+Down from any cell** jumps to that column's
  own header and opens its filter/context menu (if it has one), with focus
  on the menu's search box -- same as right-clicking, just from the
  keyboard. A column with nothing to filter (Checkbox) just gets plain
  focus; there's nothing to open.
- **Left/Right** between headers **wraps** at both ends, once a header has
  keyboard focus -- deliberately matching CardDatabaseView's own
  meta-button row, not a new convention.
- **Down** opens the focused column's menu; **Up at the very top of an open
  menu's checklist** (nothing left to highlight) now collapses the menu
  back to the header button instead of clamping in place.
- **Enter/Space** sorts by the focused column -- the keyboard equivalent of
  a left-click.
- **Tab / Ctrl+Tab / Shift+Tab** hand focus to the table, landing group-
  aware (first cell of the first/last group) via the exact same
  `focus_table_for_metabutton_tab` the meta-button row already used.
- **Ctrl+Tab from the meta-button row** now goes straight to the table's
  leftmost column header (focus only, no menu) instead of a cell -- plain
  Tab from there still lands on a cell as before.

Mouse-driven right-click filtering is **unchanged**: closing a menu that
way still hands focus back to the table exactly as before. Only menus
opened via the new keyboard paths keep focus on the header column
afterward (`SplitDropdownHeader._run_context_menu`'s `keyboard` flag) --
deliberate, so this doesn't disturb the already-documented mouse workflow.

**Two follow-up fixes, plus one small addition, same round:**
- **Tab/Shift+Tab from a focused header now actually releases focus --
  root cause found this time.** The cell selection was already moving
  correctly, but the header itself kept real Qt focus (and its ring)
  afterward. Turned out `keyPressEvent` was never the right place to
  catch a plain Tab/Shift+Tab at all: `QHeaderView` is a
  `QAbstractItemView`, and Qt's own `QWidget::event()` runs its internal
  `focusNextPrevChild()` handling for an unmodified Tab/Shift+Tab
  *before* a widget's `keyPressEvent()` ever runs -- but that internal
  handling explicitly skips Ctrl/Alt-modified keys, which is exactly why
  Ctrl+Tab already worked correctly while plain Tab didn't (a very
  useful clue). Fixed by moving Tab/Backtab handling to an
  APPLICATION-level event filter (`SplitDropdownHeader.eventFilter`),
  installed ahead of Qt's own routing -- the identical fix shape already
  used for this exact class of bug in `collapsible_pane.py` and
  `card_database_view.py`'s meta-button row. `_release_focus_to_table`
  still explicitly clears the header's own state before handing off,
  rather than trusting a `focusOutEvent` alone.
- **Up in an open filter menu is now two steps, not one** (unchanged from
  the previous round's fix, still holding).
- **Page Up / Page Down / Home / End now work inside an open filter
  menu's checklist**, alongside the existing Up/Down/Tab/Shift+Tab/Space/
  Enter -- Home/End jump straight to the first/last visible value; Page
  Up/Down jump `PAGE_STEP` (10) rows at a time, clamped at both ends.
  Routed through the same `_MenuSearchBox` app-level filter and
  `setActiveAction()` mechanism Up/Down already use, for the same reason:
  QMenu's own native handling for these keys would hit the identical
  "state changes, but invisibly, since real focus never left the search
  box" problem Up/Down already had before this class existed.

# MTG Local Database — Prototype

## Row context menu rework: selection-scoped actions, no more per-row "..." column (this round)

- **Right-clicking a card row (or a multi-row selection) now opens a real
  action menu** instead of jumping straight to the tag-apply dialog. Top
  batch, all real: **Apply Tags... (Alt+A)**, **Add to Deck... (Alt+D)**,
  **Add to Inventory (Alt+E)**, **Add to Wishlist (Alt+W)** -- every one
  operates on the WHOLE current selection, computed fresh whether triggered
  from the menu or the hotkey directly (`CardTableView._get_selected_cards`).
  Add to Inventory/Wishlist bump that card's Have/Want qty by 1 (mutating
  the same dict the table already displays, then one model refresh for the
  whole batch); Add to Deck is an honest stub (`QMessageBox`, same pattern
  File > Import/Export already use) since Deck Viewer has no real per-deck
  card storage yet.
- Below a separator: six **disabled** "Filter by Name/Edition/Rarity/Type/
  Subtype/Color" placeholders -- reserving the spot for once the flexible
  search engine (parked in NOTES.md) exists to actually back them.
  Deliberately no default hotkey on these, unlike the four real actions
  above.
- **The old rightmost "..." actions column is gone** (`ActionButtonDelegate`
  removed entirely). Every action it used to offer was already a
  selection-scoped operation dressed up as a per-row button -- the new
  right-click menu is the correct shape for that, not a second, narrower
  "just this one row" pathway.

## Keyboard navigation polish: group-aware edges, focus return, edge-collapse (this round)

Two follow-up fixes on top of the five below, both from real usage after
the first pass landed:

- **Ctrl+Up/Down at a group's edge now hops into the ADJACENT group**
  instead of staying put. Previously, once Ctrl+Up reached the current
  group's top row, pressing it again was a no-op -- there was no way to
  reach a neighboring group with Ctrl+Up/Down at all, short of the
  wrapping Ctrl+Tab. `_edge_target_for_key` now checks whether the
  current cell is ALREADY at that edge; if so, it looks two rows past it
  (`_group_bounds_for_row(first_row - 2)` / `(last_row + 2)` -- a header
  row always sits exactly one row outside its own group's near edge, so
  the neighboring group's FAR edge is exactly two rows further out) and
  jumps there instead. Repeated presses walk edge-to-edge, group by
  group, clamping (not wrapping) at the table's actual ends --
  `_current_group_bounds` is now a thin wrapper around the new, more
  general `_group_bounds_for_row`.
- **Fixed a real selection-rendering bug**: extending a selection (plain
  Shift+Up/Down, or Ctrl+Shift+Up/Down once it crosses a group boundary)
  was selecting the ENTIRE spanned header row's width on both sides of
  the crossing, not just the current column -- because
  `_extend_selection_to` built one flat `QItemSelection(anchor, target)`
  rectangle, and a rectangle that merely PASSES THROUGH a group-header
  row (full-width `setSpan()`, see `_reapply_group_spans`) gets rendered
  by `QTableView` as that whole row selected, even though the header's
  own cells aren't individually selectable. Fixed by building the
  selection as one `QItemSelection` PER CONTIGUOUS RUN of real rows,
  skipping header rows entirely, rather than one flat rectangle that
  could unintentionally include one. Plain Shift+Up/Down also no longer
  relies on Qt's own native extend at all (same span quirk applied there
  too) -- a new `_adjacent_selectable_row_target` computes the next real
  row directly, skipping any header, and routes through the now-fixed
  `_extend_selection_to`.

## Keyboard navigation polish: group-aware edges, focus return, edge-collapse (earlier round)

Five small, independent fixes to the table's keyboard handling, all in
`card_table.py` (plus one line in `card_database_view.py`):

- **Ctrl+Arrow/Ctrl+Shift+Arrow now stop at the CURRENT group's edge, not
  the table's.** New `CardTableView._current_group_bounds()` walks
  outward from the current cell to the nearest group-header rows on
  either side (or the table's real top/bottom when nothing's grouped) --
  `_edge_target_for_key` reads Up/Down targets from this instead of
  always jumping to row 0 / the last row. Landing row is guaranteed to be
  a real CARD row, never the inert header itself, since the walk steps
  one row past a header before it starts.
- **Page Up/Down jump between groups** (clamped at the first/last group,
  a no-op past either end) when the table is grouped; native paging is
  untouched when it isn't. **Ctrl+Tab/Ctrl+Shift+Tab now wrap around**
  (past the last group jumps back to the first, and vice versa) --
  `_jump_to_adjacent_group` gained a `wrap` flag so the same method backs
  all three keys, cycling for Tab, clamping for Page Up/Down.
- **Headers/menus now hand keyboard focus back to the table when they
  close.** New `SplitDropdownHeader.focus_requested` signal (connected to
  `CardTableView.setFocus` in `__init__`), emitted after a sort-click and
  after any right-click context menu (filter checklist, group-by, price
  source) closes; `CardDatabaseView`'s standalone Columns menu does the
  same inline, since it isn't opened through the header. Previously the
  table needed a fresh click before arrow keys did anything again.
- **An arrow press with nothing selected now selects the top-left cell**
  (`_top_left_selectable_index` -- skips a leading group-header row the
  same way group-edge lookups do) instead of extending/edge-jumping from
  an undefined anchor.
- **A plain arrow already at the table's edge collapses the selection**
  to just that one cell (`_at_edge_for_key`) instead of silently doing
  nothing -- so a Ctrl+Shift+Left run to column 0 followed by one more
  Left actually clears the multi-cell selection, matching Excel.

## Header cleanup, Ctrl+Arrow/Ctrl+Tab, mono-color-X fix (earlier round)

- **Fixed a real bug**: two stray sort arrows painted on the Checkbox and
  Actions columns from the very first launch, before anything had ever
  been sorted. Cause: `dict.get()` on a column with no sort key returns
  `None`, and the header's freshly-initialized `_active_sort_key` is also
  `None` -- `None == None` was `True`, so both columns looked like they
  matched the (nonexistent) active sort. Fixed with an explicit
  `is not None` guard in `SplitDropdownHeader.paintSection`.
- **Type/Mana Cost/Price no longer have a separate dropdown-arrow zone.**
  "Group by Type," "Group by Color," and "Price Source" all moved into
  the same right-click filter menu the value checklist already lives in
  (as checkable actions / a submenu) -- see `_build_context_menu`. This
  removed a second, visually similar ▾ glyph that used to sit right next
  to the new sort arrow and was genuinely confusing (one opened a menu,
  the other just showed sort state). Clicking anywhere in one of these
  headers now just sorts, like every other column; the space the old
  dropdown-arrow zone reserved is just more room for the sort arrow now.
- **Mana Cost's "Monocolored only" no longer excludes colorless/X-cost
  cards.** Was `len(card_colors) != 1` (colorless has 0 colors, so it got
  excluded); now `len(card_colors) not in (0, 1)` -- still excludes
  genuine multicolor cards, but a card whose only "color" info is really
  just a generic/X symbol is meant to be untouched by ANY mana filter,
  this one included, not just the per-color checkboxes.
- **Plain Ctrl+Arrow now moves (doesn't extend) to the table's edge** --
  the missing sibling to Ctrl+Shift+Arrow, sharing its edge-computation
  via the new `_edge_target_for_key` helper.
- **Ctrl+Tab / Ctrl+Shift+Tab jump between groups** when the table is
  currently grouped (first card row of the next/previous group), and are
  a deliberate no-op otherwise -- real Excel has no worksheet-level
  behavior on Ctrl+Tab at all (it's an OS-level combo there), so "do
  nothing when there's nothing group-shaped to jump between" was the
  more faithful choice over inventing a new meaning for it.
- Parked in NOTES.md: an option to stop cell-selection movement at a
  group boundary instead of always falling through to the next group.

## Startup empty-state, tab reorder, Excel-parity fixes (earlier round)

- **App opens with NO tab selected** -- an empty pane ("Open any of the
  tabs on the left...") instead of defaulting to Tag Database. SideNav no
  longer auto-checks a button at startup; `main.py`'s stack has the empty
  pane at index 0, with every real tab's stack position offset by one
  (`MainWindow.STACK_OFFSET`). Nothing is built eagerly anymore either --
  every tab (including what used to be the eager default) now goes
  through the same lazy-build-on-first-visit path, backed by the same
  background preload queue as before.
- **Tab order is now Card Database, Tag Database, Deck Viewer** (was
  Tag/Card/Deck) -- `side_nav.py`'s `TABS` is still the single source of
  truth both the side-nav buttons and the digit shortcuts below derive
  from.
- **1/2/3 switch tabs directly, no Ctrl.** Previously Ctrl+1/2/3 via plain
  `QShortcut`s; a bare-digit `QShortcut` would have stolen '1'/'2'/'3' away
  from any focused text field (a filter search box, an in-progress Qty
  edit) before that widget ever saw the keystroke. Implemented instead as
  an app-level event filter (`MainWindow.eventFilter`) that only treats a
  bare digit as a tab switch when this window is the active one AND focus
  isn't in a `QLineEdit` -- every editable text field in this app is one
  under the hood, including the table's own default cell editor.
- **Card Database header now shows sort direction + a filter indicator
  per column** (`SplitDropdownHeader`'s new `_paint_sort_arrow`/
  `_paint_filter_dot`) -- a small ▲/▼ for the actively-sorted column
  (previously only the Edition/Rarity split column showed anything, and
  it was direction-blind), and a gold dot on any column with an active
  value filter (including Mana Cost's mono-only/excluded-color state,
  which isn't a plain `_column_filters` entry). No more right-clicking
  every column to check whether it's currently filtered.
- **New "Clear Filters" button** (`CardDatabaseView`, next to Columns) and
  **Ctrl+Alt+F** (`CardTableView`) both call the same new
  `CardTableModel.clear_all_filters()` -- resets every column's value
  filter plus Mana Cost's separate mono/excluded-color state in one shot,
  without touching sort or grouping.
- **Keyboard selection now actually matches Excel** -- see "Keyboard
  navigation rewrite" below, its own section since the bug and fix are
  worth understanding in detail.
- **Mana Cost color filtering is now robust against non-color symbols
  (e.g. "X") in a card's `colors` list** -- see "Mana Cost / X robustness"
  below.

### Keyboard navigation rewrite: anchor tracking

Two real bugs, both from the same root cause: the old code used
`self.currentIndex()` as one corner of a selection rectangle, but
`currentIndex()` is also what gets MOVED by every one of these actions --
so it couldn't simultaneously be "the fixed starting corner" too.

- **Ctrl+Shift+Right then Ctrl+Shift+Down only selected the last column**,
  not the whole rectangle -- because the second call read `currentIndex()`
  (now sitting at the FAR corner from the first extend) as its anchor,
  instead of the cell the whole chain actually started from.
- **Ctrl+End looked like it selected both the current cell and the last
  cell** -- `QAbstractItemView.setCurrentIndex()` doesn't reliably CLEAR a
  prior selection; it can just add the new cell on top of whatever was
  already selected.

**The fix**: `CardTableView` now tracks a real `self._selection_anchor` --
the fixed corner a Ctrl+Shift+... chain extends FROM, updated only on
non-shift navigation (a plain click, a plain arrow key, Ctrl+Home/End) and
left untouched by anything that EXTENDS a selection (plain Shift+Arrow,
Ctrl+Shift+Arrow/Home/End). Every extend now re-derives the FULL
anchor-to-target rectangle from scratch (`_extend_selection_to`) rather
than unioning onto whatever was already selected, and Ctrl+Home/End go
through the selection model directly with an explicit `ClearAndSelect`
(`_move_current_clearing_selection`) instead of the unreliable
convenience `setCurrentIndex()`. Ctrl+Shift+Home/End (select-to-corner,
which Excel also supports and the old code didn't have at all) came along
for free once `_extend_selection_to` existed as a shared primitive.
Confirmed headlessly: a Shift+Right (native Qt) followed by a
Ctrl+Shift+Down (ours) correctly extends from the ORIGINAL anchor, not
wherever the first extension left off -- the two mechanisms share the
same anchor concept without any coordination code, because neither one
ever touches it during a shift-held move, only ever reads it.

### Mana Cost / X robustness

Investigated the reported "{X} should count as colorless, not be affected
by filters" -- turns out the mock data already gets this right structurally
(Endless One's `colors` is `[]`, and colorless cards were already
structurally exempt from every color-filter check). The REAL latent bug:
`_color_category()` did `COLOR_NAMES[colors[0]]` with no validation, so if
a card's `colors` list ever contained anything other than a genuine WUBRG
letter -- e.g. a stray "X" from messier real-world/imported data -- it
would raise `KeyError` and crash. New `_real_colors()` helper strips
`colors` down to genuine WUBRG letters before ANY category/rank/filter
logic touches it, everywhere colors are read (`_color_category`,
`_color_rank`, `CardTableModel._passes_filters`) -- consistent with the
app's offline-first "pick up whatever valid-ish data it's given" priority,
and makes the exemption robust by construction instead of by accident of
today's mock data happening to already model it as `colors: []`.

## Loading time optimizations

Tabs/dialogs still build lazily (fast launch), but now preload in the background
afterward on a staggered timer instead of sitting un-built until first visit —
closes the "first click into Card Database/Deck Viewer/Options hitches" gap
without giving back the launch-time win. See main.py's _run_next_preload_step /
NOTES.md for why this is a main-thread timer chain, not a real thread (Qt
widgets aren't thread-safe).

## Data Management window + shared dialog base extracted (this round)

The real first UI step toward the local-JSON/Scryfall-API data layer (goals
#1/#3/#4/#7) -- reachable via **File > Data Management...** or **Ctrl+M**. Same
UI-shell status as the Options window: everything looks and behaves correctly,
but no actual download/parse/persistence pipeline exists yet.

- **New `data_management_dialog.py` / `DataManagementDialog`**, three tabs:
  - **Metadata** -- one row per Scryfall bulk-data export (Oracle Cards, Unique
    Artwork, Default Cards, All Cards, Rulings) plus the separate Tagger-project
    exports (Art Tags, Oracle Tags). Each row: Browse, filename, size,
    last-changed date, and an Update button, followed by a description of what
    that file actually contains.
  - **Card Images** -- a target folder (with a real recursive folder-size read),
    checkboxes for every image size/crop (png, small, normal, large,
    border_crop, art_crop, thumb) each with its own description, a
    print-language dropdown (reuses `mock_data.LANGUAGES` -- this genuinely is
    the same "which printed language" concept, unlike Options' separate
    UI-language setting), an edition-picker menu (checklist of placeholder sets,
    "All Editions" as a master toggle), and a Download button.
  - **Decks & Tags** -- structurally identical to the Metadata tab (same row
    layout), pointed at this app's own local save data instead of Scryfall's --
    `decks.json` / `tags.json`. The action button reads "Locate..." instead of
    "Update" here, since there's nothing to redownload for your own data.
- **Browse buttons are genuinely functional**, not mocked: real `QFileDialog`s,
  and picking a real file/folder reads its actual size and modified time
  straight off disk. Update/Locate/Download, by contrast, have nothing real to
  do yet -- they give the same brief "working" feedback CardDetailDialog's Apply
  button already established, rather than sitting inert.
- **New `dialog_common.py`**: the vertical-tab-list-plus-stack-plus- Ctrl+Tab
  chrome that used to live directly in `options_dialog.py` is now a shared
  `VerticalTabDialog` base, extracted once Data Management needed the exact same
  wiring. `OptionsDialog` and `DataManagementDialog` are both thin subclasses of
  it now -- siblings sharing one base, not one inheriting the other.
- **`main.py`'s global stylesheet gained explicit `QScrollBar` styling**, added
  proactively rather than reactively -- both new dialogs' tabs are this app's
  first use of `QScrollArea`, and this app already learned once (the filter-menu
  `QMenu` styling gap) that any unstyled native widget looks visibly wrong the
  moment custom QSS exists anywhere in the app.

## Options window: UI shell only (earlier round)

Resolves the "window shell exists" half of NOTES.md's parked Options-menu entry
-- reachable via **File > Options...** or **Ctrl+,**. Nothing here reads from or
writes to a real settings store yet; see NOTES.md for the full list of what's
still not wired up.

- **New `options_dialog.py` / `OptionsDialog`**: a frameless modal window (same
  `FramelessDialog` base as the card detail popup and tag-apply dialog) with a
  vertical tab strip -- Language, Themes, Online, Interface, Input, Advanced --
  and Apply/Cancel/OK along the bottom.
- **Tab strip is a `QListWidget`, not `SideNav`-style buttons** -- deliberately,
  so Up/Down/Home/End navigation and type-ahead jump-to-tab come free from Qt
  itself rather than needing custom key handling (same "let the native widget do
  what it already does" reasoning `tree_pane.py` uses for `QTreeWidget` over a
  hand-rolled tree).
- **Accent-color swatches (Themes tab) are `QRadioButton`s styled as flat color
  squares**, not `QToolButton`s -- an exclusive `QRadioButton` group gets native
  arrow-key cycling between its members; a row of checkable tool buttons
  wouldn't, and reimplementing that by hand would be exactly the kind of
  hand-rolled navigation this app tries to avoid when Qt already provides it.
- **Ctrl+Tab / Ctrl+Shift+Tab (also Ctrl+PageDown/Up) switch tabs from anywhere
  in the dialog**, bound via `WidgetWithChildrenShortcut` the same way
  `tree_pane.py` already binds Ctrl+N/Ctrl+X/etc. -- so tab-switching doesn't
  require the tab list to specifically have focus first.
- Escape-to-cancel and Enter-to-confirm are `QDialog`'s own native behavior --
  not reimplemented here.
- Apply gives the same transient "Applied ✓" feedback CardDetailDialog's Apply
  button already uses, without actually persisting anything (there's nowhere to
  persist to yet).
- Known limitation, same one CardDetailDialog already has and for the same
  reason: fixed-size window (frameless windows lose native edge-drag resize) --
  see NOTES.md's DPI/scaling entry, which already flags this dialog as one of
  the places that'll need real resize/reflow support.

## Reticle-select zoom on the card image, real pan+zoom viewer (earlier round)

Resolves the idea parked in NOTES.md. Third real design -- see "Design journey"
at the end for the two that came before and exactly what each one got wrong;
worth reading before touching this file again, since each failure was subtle and
each fix revealed the next problem.

**Final design: a real camera-position-plus-zoom-level viewer, not a crop
rectangle.** `ImageZoomWidget` now tracks exactly two things: `_zoom` (a scalar;
1.0 = fit-to-screen, the opening state) and `_pan_center` (a normalized point in
the full image; which point is centered in the viewport). Nothing else. Both
mouse-wheel and reticle-select read and write these same two variables.

- **The window's on-screen size is derived, not stored** (`_geometry_for_zoom`):
  the full image at the current zoom has a size of `fit_size * zoom` in BOTH
  dimensions together (uniform scaling -- the card's true aspect ratio is never
  distorted, only enlarged or shrunk as a whole), and the window's actual size
  is that, clamped INDEPENDENTLY per axis to the screen. This is what makes
  zooming in from the opening state grow the window correctly: whichever axis
  already touches the screen edge (typically height, for a portrait card on a
  landscape screen) stays capped there, while the OTHER axis -- still growing,
  since the image keeps enlarging uniformly -- keeps widening the window to fill
  more of the screen, until it ALSO hits the screen edge. Past that point (both
  axes maxed), further zoom can't grow the window at all and instead shows
  progressively less of the image on both axes -- exactly matching how zooming
  into a photo past "fit to window" behaves in a real viewer. Confirmed
  headlessly: 40 wheel-zoom- in ticks from the opening state genuinely widen the
  window horizontally while its height stays pinned at the screen's height, then
  eventually land on an exactly-fullscreen window once both axes are capped.
- **Plain click+drag now actually pans**, not just moves the window -- built and
  tested this round rather than deferred. Once the image (at the current zoom)
  exceeds the screen on at least one axis, there's real content sitting outside
  the window for `_pan_center` to point at, so drag adjusts `_pan_center`
  instead (dragging right/down reveals content that was further left/up -- the
  pan center moves OPPOSITE the drag direction, the standard "grab and drag the
  canvas" convention). When nothing is cropped (the whole image already fits),
  drag still moves the window as before, since there's nothing to pan to.
  Confirmed headlessly: a simulated drag while zoomed in moves `_pan_center` in
  the correct direction and leaves the window's on-screen position untouched;
  the same drag at the default zoom still moves the window and leaves
  `_pan_center` alone.
- **Reticle-select now computes a new `_zoom` and `_pan_center`** from the
  dragged rectangle (mapped through the CURRENT visible fraction into normalized
  image coordinates, so a selection made while already zoomed/ panned composes
  correctly against that state) rather than touching a separate crop concept.
  The zoom increase is whichever is smaller of the two per-axis fit ratios, so
  the WHOLE selection becomes visible without being clipped on either axis --
  same "fit, don't overflow" convention `_geometry_for_zoom` already uses for
  fitting to the screen.
- **`MAX_ZOOM = 4.0` (default) is now a real, explicit ceiling** applied to both
  wheel and reticle zoom identically -- requested after the previous design let
  a chain of reticle zooms push effective magnification far higher than a single
  wheel-out tick could gracefully unwind (see design journey). Intended to
  become a configurable Options- window setting eventually; hardcoded for now
  since that's explicitly low priority. `MIN_ZOOM = 0.3` remains as the lower
  floor, allowing zooming out slightly below "fit to screen" as before.
- Ctrl+drag reticle selection, the translucent blue selection overlay,
  Escape-cancels-an-in-progress-selection, and right-click/Escape/
  outside-click-closes are all unchanged from before.

### Design journey (worth keeping -- three designs, each fixed a real bug and revealed the next one)

**Attempt 1** treated the reticle-cropped region and the window's own pixel size
as the same thing: a reticle zoom just set the window to fill the screen
directly, with no persistent state to compose a second zoom against.

**Attempt 2** split this into two variables -- `_zoom` (window pixel scale,
wheel-adjusted) and `_view_rect` (a normalized crop fraction, reticle-adjusted
only). This let repeated zooms compose, but wheel-zoom touched `_zoom` alone, so
scrolling out after several reticle zooms shrank the window while the crop (and
the multiplier it drove) stayed frozen -- the displayed number could report huge
magnification even once the window was smaller than its own starting size.

**Attempt 3** deleted `_zoom` entirely and let a single crop rectangle drive
everything, with wheel scaling BOTH the rectangle's width and height by the same
factor. This fixed the drift from attempt 2, and correctly reproduced "zooming
all the way out returns to the exact opening state." But it revealed a new,
different problem: scaling both crop dimensions together means the crop's shape
can never change under wheel alone -- zooming in from the default (card-shaped)
crop just produces a smaller, STILL card-shaped crop, and "fit a
still-card-shaped rectangle to the screen" always produces the IDENTICAL window
shape regardless of how small the rectangle conceptually is. So the window never
grew past its initial letterboxed size under wheel zoom at all -- the number
climbed, but nothing about the window's actual size or shape changed, matching
the exact "indicator keeps counting up, the card doesn't fill more space to the
sides" symptom. Reticle-select worked because it could deliberately produce an
odd-shaped crop; wheel alone structurally never could, no matter how the factor
or clamping was tuned. Repeated unclamped reticle zooms could also push the crop
far below any wheel-side floor, so a single wheel-out tick afterward could snap
the number down by a huge amount in one step instead of shrinking gradually.

**The actual fix (this round)**: stop trying to represent "how zoomed in" and
"what shape is currently framed" with a single rectangle. Track them as what
they actually are -- a scalar zoom level and a separate pan point -- the same
"camera position + zoom" model any real 2D viewer uses. Once the crop's SHAPE is
allowed to be a pure side effect of "the image enlarged uniformly, clamped
per-axis to the screen" rather than something wheel-zoom has to directly
preserve or manipulate, the window naturally grows into whatever shape the
screen allows, exactly as a real viewer does.

**General lesson, worth remembering next time state doesn't quite behave
right**: when a single piece of state (a rectangle, in this case) is being asked
to answer two conceptually different questions at once ("how much is shown" and
"what shape is it"), consider whether those are actually two SEPARATE,
independent facts that got conflated into one representation -- not just a
formula that needs more tuning.

## Card detail popup: Type-column alignment overhaul, QGridLayout rewrite (earlier round)

Three rounds of alignment fixes on the same underlying complaint ("Type's
caption/value don't visually line up with Edition/Language's column"), the first
two of which didn't actually work despite looking correct on paper — worth
reading in full if this class of bug shows up again elsewhere, since the general
lesson generalizes past this one dialog.

- **The fix that actually worked**: all three stat rows (Type/Mana,
  Edition/Rarity/Price, Language/Condition/Foil) now live in ONE `QGridLayout`
  instead of three independent `QHBoxLayout`s. A `QGridLayout` guarantees every
  cell in the same COLUMN shares the exact same pixel width across every row — a
  hard invariant Qt itself enforces — instead of something reconstructed via a
  formula that has to correctly guess how a DIFFERENT, independently-laid-out
  row divides up its own width. Type's own grid cell spans columns 0+1
  (`columnSpan=2`), giving a long type line (e.g. Thalia's "Legendary Creature —
  Human Soldier") room to grow rightward into column 1's otherwise-empty space
  before it needs to wrap, instead of wrapping early or truncating. Confirmed
  via actual headless instantiation + measuring real rendered pixel positions
  (`QFontMetrics.boundingRect`, `.mapTo()`), not just re-deriving the algebra
  again — see "Debugging journey" below for why that mattered.
- **Column widths are explicitly LOCKED** to a fixed pixel value shortly after
  the dialog's first real layout pass
  (`CardDetailDialog._lock_column_widths()`), rather than left to
  `QGridLayout`'s own stretch-based sizing. Necessary, not just tidy:
  `QGridLayout` apparently consults a cell's uncapped `minimumSizeHint()` when
  deciding how wide a COLUMN itself needs to be, even when every individual cell
  already has an explicit `setMaximumWidth()` — so selecting a long
  Language/Condition value could still widen the whole column, a failure mode
  the OLD per-row `QHBoxLayout` structure never had (each row solved its own
  width independently, with nothing to reconcile against a different row's
  content). Locking BOTH `setColumnMinimumWidth()` and `setMaximumWidth()` to
  the identical number removes that degree of freedom entirely. **This fix is
  explicitly justified by the dialog being a fixed-size window (900x560, never
  resized)** — see NOTES.md's new "variable text scaling & DPI" entry for why
  this needs revisiting before the app can support different font sizes /
  accessibility scaling / DPI settings.
- Value buttons (Edition/Price/Language/Condition) no longer draw a dropdown
  arrow at all — the earlier fix reserved space for one via `padding-right` + a
  `menu-indicator` CSS rule, which was itself the root cause of an even earlier
  "text drifts left" bug two rounds ago. Removed entirely; the value text itself
  is the click target.
- Apply button restyled to match `CardDatabaseView`'s Inventory/Wishlist toggle
  buttons (bright fill, rounded border) instead of a flat default `QPushButton`,
  renamed from "Apply to Inventory" to just "Apply," and given explicit spacing
  above it matching the gap between stat rows.
- Card pane header text removed from the window's own title-bar-substitute
  (`frameless_dialog.py`'s `_TitleBar` gained a `show_title` parameter) — the
  card's NAME is now shown once, styled as the Card pane's own header, instead
  of duplicated in both places.
- Every pane's caption ("Legality", "Rulings") is now horizontally centered with
  a fixed gap before its content (shared via `_pane_layout()`), instead of
  defaulting to left-aligned with no gap.
- Two named spacing constants (`CAPTION_VALUE_SPACING`, `STAT_ROW_SPACING`)
  replace what used to be inconsistent hardcoded literals, specifically so "gap
  between a caption and its own value" and "gap between one stat row and the
  next" can never drift back to being the wrong way around relative to each
  other.

### Debugging journey (worth keeping — three attempts before the real fix)

1. **First attempt**: derive Type's anchor point purely from Type's own width
   (`width / 4`). Wrong because gameplay_row (Type + Mana, one inter-column gap)
   and a real 3-column row (two gaps) divide up their width differently — "1/4
   of Type's own width" answers a structurally DIFFERENT question than "half of
   a real column's width," even though the two numbers looked deceptively close.
2. **Second attempt**: read a live sibling widget's width directly
   (`edition_field.width()`) at the exact moment of computing the anchor.
   Reasonable in principle, but timing-fragile in practice — it depended on a
   completely separate, independently-laid-out widget having already settled
   into its FINAL geometry, and nothing actually guaranteed that ordering
   relative to a deferred `QTimer.singleShot(0, ...)` refresh (Qt doesn't
   promise a 0ms timer fires after every pending layout pass). The person
   testing this confirmed it made no visible difference.
3. **Third attempt**: an analytical correction formula
   (`anchor_center = width/4 - spacing/6`) derived from first principles to
   account for the different gap counts between the two row shapes. Checked out
   exactly on paper — and STILL didn't fix the visible problem, because it
   depended on an assumption (Qt's actual default inter-column spacing matching
   what the code assumed) that had never actually been verified against a real
   render.
4. **The actual fix** required two separate things working together: (a)
   restructuring to a real `QGridLayout` so column-1 width became ONE
   authoritative number instead of something independently re-derived per row,
   confirmed via `QGridLayout.cellRect()`; and (b) — critically — actually
   instantiating the dialog headlessly (`QT_QPA_PLATFORM=offscreen`) and
   measuring REAL rendered pixel positions instead of trusting the derivation a
   fourth time. That measurement caught a genuinely separate, previously
   invisible bug: the anchor math was being applied via `setContentsMargins()`
   on a label whose own coordinate origin was already shifted ~4px by
   `StatField`'s own inner layout margin — a real, exact, measured error that no
   amount of re-deriving the algebra would have caught, since the algebra itself
   was internally consistent; the bug was in a completely different, uninspected
   coordinate-space assumption.

- **General takeaway**: alignment bugs across independently-laid-out Qt layouts
  (two separate `QHBoxLayout`s, in this case) resist being fixed by formula
  alone, however carefully re-derived — two layouts computing "the same"
  quantity independently can silently disagree for reasons (a hidden margin, an
  unverified spacing assumption, a coordinate-space mismatch) invisible to
  algebra done on paper. When the bug IS alignment specifically, prefer giving
  the two things a SINGLE SHARED AUTHORITY to agree with (one real shared
  layout, not two independent ones computing matching-but-separate answers) over
  trying to reconcile two calculations — and verify any pixel-level claim
  against actual rendered widget geometry (`.geometry()`, `.mapTo()`,
  `QFontMetrics.boundingRect()`), not just re-checked math. This generalizes the
  existing "logic runs but nothing visibly happens" lesson from the filter-menu
  keyboard-nav saga (see NOTES.md) to a new failure class: logic that LOOKS
  provably correct on paper and still isn't, because the paper version omitted a
  real coordinate-space detail only actual rendering reveals.
- **Separate, smaller lesson worth keeping on its own**: `setMaximumWidth()` on
  a widget doesn't reliably stop `QGridLayout` from wanting to grow that
  widget's COLUMN based on the widget's own uncapped `minimumSizeHint()` — a
  failure mode the old independent-per-row structure never had. If a
  `QGridLayout` column mysteriously grows despite an apparent per-widget
  max-width cap anywhere else in this app later, this is the mechanism to
  suspect first; the fix is locking BOTH `setColumnMinimumWidth()` and
  `setMaximumWidth()` to the identical value, not just capping the widget.

## Card Database merge + filter-menu keyboard navigation fixed (earlier round)

- **All Card Database and Inventory are now ONE tab, "Card Database."** Same
  realization as the earlier Wishlist collapse: Inventory was always just "the
  full catalog, filtered to Have > 0" — `mock_data.py` had two functions
  (`get_all_cards()`, `get_inventory_cards()`) returning identically-shaped data
  under different names. `get_inventory_cards()` is gone; there's one dataset
  now, with Have/Want filtering applied live via the UI instead of baked into
  which function got called.
- New `card_database_view.py` / `CardDatabaseView` wraps a `CardTableView` with
  a button row above it: **Inventory** and **Wishlist** toggle buttons
  (shortcuts for excluding Have/Want == 0 — identical in effect to
  right-clicking that column and unchecking "0," just faster, and both can be on
  at once since they filter independent columns), plus a **Columns** dropdown
  for column visibility. `CardTableView` itself didn't need to change at all for
  this — the button row lives in a wrapper composing a table, the same shape
  `DeckViewerView`/`TagTreePanel` already use for composing a `TreePane`. This
  also gives the still-parked flexible search engine (see NOTES.md) an obvious
  future home: `CardDatabaseView`'s button row already reserves space for it via
  `addStretch()`.
- **Inventory/Wishlist buttons are real two-way toggles**, not one-shot actions:
  clicking one updates the model; a filter change from ANY source (the button,
  or manually via the header's own right-click checklist) updates both — so the
  buttons never silently show a state that isn't actually applied. Implemented
  via two new generic `CardTableModel` methods, `is_value_excluded()` /
  `set_value_excluded()`, that the header checklist's own toggle handler now
  also routes through (one add/discard-from-set implementation instead of two
  copies that could drift).
- **"Show Columns" is no longer duplicated into every column's right-click
  menu** — it was rebuilt identically inside each one. It's now the standalone
  Columns button above, built via a new
  `SplitDropdownHeader.build_show_columns_menu()`; right-clicking a
  non-filterable column header (Checkbox, Actions) now correctly shows no menu
  at all instead of an empty popup.
- **Filter-menu search box keyboard navigation, actually fixed this time** —
  this took several real dead ends worth recording (see "Debugging journey"
  below): Up/Down/Tab/Shift+Tab now all move the highlighted checklist value
  (Tab and Shift+Tab share the exact same logic as Up/Down, which is what makes
  them automatically skip the disabled "Filter by X" label and any
  submenu-opening action — that logic already only considers checkable actions),
  clamped at both ends, correctly skipping values hidden by the search-narrowing
  text. Space toggles the currently highlighted value once you've navigated to
  one (typing a space before that still works normally, e.g. for "Lightly
  Played"). Enter still applies the typed text directly as a filter, as before.
- Added real `QMenu` / `QMenu::item:selected` styling to `main.py`'s global
  stylesheet — previously absent entirely, which turned out to be the root cause
  behind the keyboard-nav symptoms (see below).

### Debugging journey (worth keeping — this was genuinely tricky)

Three fix attempts, in order, each ruled something out:

1. **First attempt**: moved Up/Down/Enter handling from
   `_MenuSearchBox .keyPressEvent()` to an app-level `eventFilter`,
   hypothesizing `QMenu`'s own internal arrow-key handling was intercepting the
   keys before `keyPressEvent` ever ran (mirroring how `collapsible_pane.py`
   already solves an analogous Tab-interception problem). Verified correct in
   isolation (a headless test confirmed `activeAction()` moved through visible
   actions correctly) — but the test was flawed: it called
   `app.sendEvent(box, ev)` directly, which _forces_ the event's receiver to be
   the search box by construction. That never actually exercised the real
   ambiguity, and the fix had no effect in a real window.
2. **Second attempt**: dropped the `watched is self` condition in the event
   filter entirely, hypothesizing Qt's real popup keyboard-grab routing might
   not report the search box as `watched` the way a manually constructed test
   event does. Verified this time with a test that deliberately passed an
   unrelated decoy object as `watched` — proving the broadened filter no longer
   depended on receiver identity. Still had no effect in the real window.
3. **The actual fix**: reframed the symptom. "Nothing happens" didn't
   necessarily mean the events weren't arriving — `main.py`'s global stylesheet
   had never styled `QMenu` at all, and once _any_ custom QSS is applied to an
   application, Qt's style engine stops relying on the native platform style's
   automatic hover/selected rendering for anything not explicitly re-declared.
   So `setActiveAction()` may have been working correctly the entire time, just
   invisibly. Adding explicit `QMenu::item:selected` styling (reusing the app's
   existing `#3d6a8f` selection color) made the — already-correct — navigation
   logic visible. Separately, Space-to-toggle had never been implemented at all:
   real `QMenu` only handles Space when the menu itself holds actual keyboard
   focus, which this design deliberately never grants (focus stays on the search
   box so typing keeps narrowing the list) — so Space was always just a literal
   character typed into the field.

- **Takeaway for next time a "the events must not be reaching my handler" bug
  shows up**: check whether the logic is actually running and simply invisible
  (missing QSS state styling is an easy thing to overlook once _any_ custom
  stylesheet is in play) before assuming the event routing itself is broken.

## Detail popup, mono-color, and keyboard-parity fixes (earlier round)

- Fixed the actual bug behind the "inconsistent" alignment complaint: the
  reserved-width calculation for centered dropdown fields only subtracted the
  arrow's space ONCE, when symmetric padding means it needed subtracting TWICE —
  this made short values look fine but medium-length ones (Price, "Lightly
  Played") wrap/elide against the wrong width. Fixed uniformly for every
  clickable+centered field, not case-by-case.
- Type's value now uses the same indent magic number (16px) as the centered
  fields' effective content start, instead of an approximate guess.
- Switching price source no longer resets your selected language — it was being
  re-derived from print data on every refresh instead of just being displayed
  from the tracked selection.
- Added a real "Apply to Inventory" button: edition/language/condition/foil
  changes now actually write back into the card's real collection entry
  (previously these were preview-only with nowhere to commit to).
- Mana Cost filtering redesigned again: unchecking a single color now correctly
  hides multicolor cards containing it too (previously only an exact mono-color
  match was excluded) — implemented via a dedicated per-color-letter exclusion
  set rather than the generic value-checklist mechanism, which structurally
  couldn't express "any card containing this color."
- Filter-menu search box: fully rewritten navigation — Up/Down now move QMenu's
  highlight directly via `setActiveAction()` without ever transferring real
  keyboard focus away from the search box (the previous focus-handoff approach
  was fragile with QWidgetAction involved). Enter applies the typed text as a
  real filter and closes the menu.
- Tag-apply widget: restored a visible current-item indicator (the app's global
  "remove focus rectangle" style was suppressing it here too) and set initial
  focus/current-item so arrow-key navigation works immediately; confirmed Space
  already natively toggles the current item's checkbox.
- Table: added Excel-familiar shortcuts — F2 (Qty is now genuinely editable),
  Shift+Space (select row), Ctrl+Space (select column), Ctrl+Home/End,
  Ctrl+Shift+Arrow (extend selection to an edge, with known simplifications
  noted in NOTES.md).

## Alignment & interaction fixes (earlier round)

- Detail popup: Type's value now has a left indent so short values ("Instant")
  don't look stranded far from the caption above them; Type and Condition wrap
  onto multiple lines instead of truncating; Language and Mana Cost wrap too
  (needed for entries like "Chinese Simplified").
- CardDetailDialog and TagApplyDialog now share one `frameless_dialog.py` base
  (no OS title bar, custom draggable title bar, click-outside-closes) instead of
  duplicating that logic.
- Table headers: the Edition/Rarity sort arrow and the Type/Mana/Price dropdown
  arrow no longer shift the label text — labels are drawn at a fixed position
  and the arrow is a separate overlay, not part of the centered/positioned text
  itself.
- Mana Cost filter redesigned: the checklist now shows only the 5 mono colors
  (no Colorless, no multicolor combos) — colorless is structurally exempt from
  the checkboxes rather than specially skipped, and "Monocolored only" is a real
  persistent toggle (not a one-shot preset) that combines with the color
  checkboxes rather than overwriting them.
- Filter-menu search box: arrow-key navigation rewritten — Up is clamped (does
  nothing), Down jumps directly to the first _visible_ checkable action via
  `setActiveAction()` instead of re-dispatching a raw key event through the menu
  (which was landing on hidden/narrowed-out items and bouncing focus back to the
  search box).
- Right-click on a card row no longer drops a multi-row selection when the click
  lands on a different column than the one originally selected — right-button
  presses now skip Qt's default click handling entirely, leaving selection
  changes on right-click to our own deliberate logic.
- Tag-apply widget: now frameless (matches the card detail popup), and
  fully-checked tags are visually highlighted (bold + accent color).
- Parked for later (see NOTES.md): a search box inside the tag-apply widget
  itself, and user-assignable per-branch hotkey letter sequences for fast tag
  navigation.

## Detail-popup layout + filter-menu polish (earlier round)

- Detail popup: Type's caption now centers within a notional 1/3-of-row slot
  (matching every other caption's rhythm) even though its VALUE still spans the
  full 2/3 width it needs.
- Detail popup: Type and Condition now wrap onto multiple lines instead of
  truncating with "…" when text is too long for their space (Condition required
  a manual line-breaker since QToolButton has no native word-wrap).
- Detail popup: centered dropdown fields (Edition/Price/Language/Condition) now
  actually look centered — they were only getting right-side padding reserved
  for the arrow, which silently shifted the "centered" content box left;
  matching left padding fixes it.
- Filter menus: the search box now auto-focuses the instant you right-click (no
  need to click into it first), has a visibly different border when focused vs.
  not, and gives placeholder text a bit of left margin.
- Filter menus: pressing Up/Down in the search box hands focus to the menu and
  forwards that same keypress, so you can type a few characters to narrow the
  list then immediately arrow-key into the results.
- Mana Cost's filter now has a "Monocolored only" preset above a separator —
  checking it sets every single-color entry on and colorless/multicolor off in
  one action, so you can then fine-tune by unchecking specific colors.
- Price is now filterable too (with the same search box), consistent with every
  other column.

## Tag-apply widget (earlier round)

- **Right-click any card row** in All Card Database or Inventory to open it: a
  checkbox tree mirroring the Tag Database. Both folders AND leaf tags are
  checkable (a card can carry the broad "Removal" tag, a specific
  "Destroy"/"Exile" subtag, or any combination independently — matches the
  original spec's example directly).
- Right-clicking a row that's part of your current multi-selection keeps the
  whole selection (bulk-tag several cards at once); right-clicking outside it
  selects just that row first (standard Explorer-style behavior).
- Checkboxes start **tri-state**: fully checked if every selected card already
  has that tag, unchecked if none do, partially-checked if it's mixed. A partial
  checkbox left untouched is skipped entirely on Apply — only tags you
  explicitly resolve to fully checked/unchecked get applied across the whole
  selection.
- Backed by a new `tag_assignments.py` — a simple card-name → tag-id store,
  keyed by tag ID specifically so renaming a tag later never orphans existing
  assignments.

## Filter improvements + layout fixes (earlier round)

- Card detail popup: rows 2 and 3 (Edition/Rarity/Price, Language/
  Condition/Foil) now actually split into even thirds and center within them —
  the previous version used fixed pixel widths plus trailing empty space, which
  is why centering didn't visibly do anything.
- Card detail popup: a bit more space below the art, and a thin separator
  between the stat rows and the oracle text.
- Every column's filter menu now has an Excel-style search box that narrows the
  checkbox list as you type — useful once a column has many distinct values
  (quantities, etc).
- Mana Cost's filter now offers color categories (White, Blue, Colorless,
  multicolor combos like "U/B", ...) instead of literal mana-cost strings — this
  is what makes "show me mono-white cards only" possible.
- Power/Toughness missing values (non-creatures) now show as "(none)" in the
  filter checklist instead of being silently excluded from it, so "show only
  creatures" / "show only non-creatures" is now a real filter option. Added a
  card with variable power/toughness ("*", Endless One) so this is tested
  against real non-numeric data, not just claimed to work.
- Theming (system accent colors, light/dark presets) and a real flexible search
  engine are explicitly parked in NOTES.md rather than attempted as quick fixes
  — both are real subsystems, not polish.

## Repurposing pass (earlier round)

- **Wishlist is gone as a standalone tab.** It's replaced by "All Card Database"
  -- the full browsable catalog, showing both Have and Want counts for every
  card. Inventory is the same shape of data, filtered to what you actually own.
  Isolating "what I want" is now just: right-click the Want column on either
  table, uncheck "0". Tab order changed accordingly: Tag Database, All Card
  Database, Inventory, Deck Viewer (Ctrl+1..4) -- All Card Database took
  Inventory's old slot, Inventory took Wishlist's.
- Header background is now a deliberately darker near-black (matching what used
  to show up by accident before it got "fixed" to match the rows) -- applied
  uniformly across plain and custom-painted headers alike.
- Card detail popup: Edition/Rarity/Price and Language/Condition rows are now
  center-aligned across the board, instead of left-aligned in a way that read as
  inconsistent next to the Type/Mana row's intentional left/center split.

## Polish pass (earlier round)

- Side nav buttons now highlight the instant you press them, not after a visible
  dashed-focus-rect-then-highlight delay (the delay was a native focus rectangle
  Qt draws before our own styling takes over — removed via `outline: 0`, plus an
  explicit `:pressed` style for immediate feedback).
- Table headers are now visually uniform — the custom-painted ones
  (Edition/Rarity split, Type/Mana/Price dropdown arrows) were reading their
  background from the widget's base palette instead of the app's actual
  stylesheet color, which are two different things in Qt; they now share one
  explicit color constant with the plain headers.
- Added a cross-reference count column: Inventory shows "Wished" (how many
  you've wishlisted), Wishlist shows "Have" (how many you own) — sortable,
  toggleable via Show Columns like any other.
- Detail popup: Rulings pane now has a proper visible border (QListWidget wasn't
  in the app's bordered-widget style rule at all — now is) and is guaranteed at
  least as wide as the Legality pane.
- Detail popup: Language/Condition/Foil moved to their own third metadata row,
  separate from Edition/Rarity/Price, so the card pane isn't overcrowded.
- Detail popup: Foil now reads "Yes"/"No" instead of "On"/"Off".
- Detail popup: the Type/Mana Cost row is now a true proportional 2:1 split of
  the row's actual width (via layout stretch, not fixed pixel guesses) — Type
  left-aligned, Mana Cost centered.

## Frameless detail popup, Power/Toughness split, broader type filter

- Opening the detail popup now cancels any hover popover already showing or
  waiting out its delay timer.
- Tree panes (Tag Database / Deck Viewer): removed the "+ Item"/"+ Folder"
  toolbar buttons (right-click menu and Ctrl+N/Ctrl+Shift+N cover the same
  ground) and made tab-switching set focus deterministically — this is what
  actually fixes Tab not collapsing the pane on the very first press.
- Removed the native dashed "focus rectangle" Qt draws on top of selected items
  (kept the color highlight, which was already the intended look).
- Detail popup: Legality pane now sizes itself to the widest text that can
  actually occur, with word-wrap as a fallback, instead of a cramped
  proportional share of the width.
- Detail popup: removed the OS title bar entirely — frameless window with its
  own thin title bar (name + close button), draggable by that bar, closes
  automatically when you click anywhere in the main app window (verified this
  doesn't misfire when clicking the popup's own dropdown menus, which are
  technically separate top-level windows).
- Detail popup: added Language and Condition dropdowns and a Foil toggle
  alongside Edition/Rarity/Price.
- Table: Power and Toughness are now independent columns (sortable/ filterable
  separately) rather than one combined "P/T" column.
- The Type column's right-click filter checklist now offers broad categories
  (Creature, Instant, ...) instead of full literal type lines.
- Parked for later (see NOTES.md): an options/settings window with externalized
  per-language string files, "have"/"want"/"in-deck" count columns, and
  default-add behavior with variant grouping.

## Header filter, column picker, group-by

- **Right-click any header** in Inventory/Wishlist: for most columns, a
  checklist of every distinct value in that column (uncheck a value to hide
  matching rows — check it again to bring them back), plus a **"Show Columns"**
  submenu to toggle any column's visibility live.
- **Type / Mana Cost headers** now have the same ▾ dropdown arrow Price has —
  click it for **"Group by Type"** / **"Group by Color"**. Grouped view inserts
  a full-width sub-header bar between groups (Deckbox-style: Creatures, then
  Instants, etc.; Colorless, then White, Blue, ... then multicolor combos like
  "U/B"). Click again to un-group.
- Group-header rows are inert — not selectable, not checkable, don't open the
  detail popup or hover popover.
- ~~Known simplification: the Edition/Rarity column's filter checklist works
  off the Set only (not Rarity); Price isn't filterable this way since it's
  continuous data~~ — **superseded**: Edition and Rarity are now separate,
  independently filterable columns, and Price now has real range filtering
  (`>`, `>=`, `<`, `<=`, `!=`) via a typed expression box instead of a
  checklist. See "Column split + filter overhaul" below.

## Card detail popup

- Double-click any row: name, clickable art placeholder (opens a separate
  zoomable/draggable window), fixed-position stats (Type / Mana Cost / Edition /
  Rarity / Price), oracle + flavor text, Legality and Rulings tabs.
- Edition and Price fields are dropdowns — switching editions updates
  rarity/price/flavor text; switching price source updates the price shown.

## Tree tabs (Tag Database / Deck Viewer)

- Full folder/item CRUD: create, rename (F2), delete (with confirmation),
  drag-and-drop, Ctrl+X/C/V (with cycle-detection and same-name dedup),
  right-click menu with icon color picker.
- Collapsible/resizable side pane: drag the divider, click the tall arrow on it,
  press Tab, or click into the right-hand content area.

## What this is

A Deckbox-style layout: a tab strip (Tag Database / Card Database / Deck Viewer)
on the left driving swappable central views. Card Database is a spreadsheet (the
full catalog, with Inventory/Wishlist/Columns toggle buttons above the table as
filter shortcuts); Tag Database and Deck Viewer are collapsible folder/item
trees. Runs on mock data — no real database or images yet.

## Run it

```bash
pip install PySide6
python main.py
```

## Try — spreadsheet tab (Card Database)

- **Ctrl+2** — jump to Card Database.
- **Inventory / Wishlist buttons** (top of the table) — toggle excluding Have ==
  0 / Want == 0; both can be on at once. Same effect as right-clicking the Have
  or Want column and unchecking "0," just faster, and the buttons stay in sync
  either way — toggle one on, then manually uncheck "0" again via the header's
  own right-click menu, and the button un-highlights to match.
- **Columns button** — dropdown to toggle any column's visibility (used to be
  duplicated into every column's own right-click menu; now lives here only).
- **Click / Ctrl+click / Shift+click** cells — Excel-like multi-selection.
- **Ctrl+C** — copy the selection as tab/newline-separated text.
- **"Price" header** — pick a price source from its right-click menu's "Price
  Source" submenu; click anywhere in the header to sort by it.
- **Right-click any filterable column header** — Type/Mana Cost's
  color/Edition/Rarity get a search-narrowable value checklist; Have/Want/
  Power/Toughness/Price/Name get a typed expression box instead (`>10`,
  `<=3.2`, `!=sliver`, or a bare partial name — see "Column split + filter
  overhaul" below). Either way: type to narrow/filter, **Up/Down or
  Tab/Shift+Tab** to move the highlight (now including **Clear Filter**,
  reachable right after the box), **Space** to toggle/activate the
  highlighted item, **Enter** to apply the typed text directly, **Up again
  with nothing highlighted** collapses the menu.
- **Hover a card's Name** — popover with placeholder art + text.
- **Right-click a card row** (or a multi-selection of rows) — opens the
  tag-apply dialog: check/uncheck tags from the Tag Database, Apply to every
  selected card at once.

## Try — tree tabs (Tag Database / Deck Viewer)

- **Ctrl+1 / Ctrl+3** — jump to Tag Database / Deck Viewer.
- **Ctrl+N / Ctrl+Shift+N** — create a new item/folder; it's immediately
  renameable with all text pre-selected, so typing replaces the name right away.
  (Also available via right-click.)
- **F2** — rename the selected item. **Delete** — delete selected item(s).
- **Drag and drop** — reorder/reparent items (drop onto a folder to move inside
  it). **Ctrl+X / Ctrl+C / Ctrl+V** — cut/copy/paste as an alternative to
  dragging.
- **Right-click** — full context menu, including a color-swatch submenu to
  recolor an item's icon.
- **Click the small ◂/▸ arrow at the top of the divider** between the tree and
  the content area — collapses/expands the tree pane. **Tab** — same toggle,
  from anywhere in that view. **Clicking anywhere in the right-hand content
  area** — also collapses the tree pane, to reclaim space once you've picked
  something.

## What's deliberately NOT here yet

Stale as of early rounds — tag-based filtering, deck contents view, column
filtering/grouping, the card detail popup, and the tag-apply widget are all
built now (see the sections above and PROJECT_CONTEXT.md's "Current status").
What's still genuinely missing:

- Real card images, and the real Scryfall/SQLite data layer generally — see
  PROJECT_CONTEXT.md's "Current status" for the full up-to-date list (real
  data layer, deck contents, the flexible search engine, an edition
  mini-widget for large edition lists, theming, DPI/scaling awareness,
  undo/redo, internationalization).
- Delete confirmation dialogs (documented limitation in `tree_pane.py`).
