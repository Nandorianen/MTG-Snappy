"""
card_database_view.py
----------------------
Wraps a CardTableView with an outer button row -- Inventory/Wishlist filter-
preset toggles plus a Columns visibility dropdown. This is deliberately the
same architectural slot NOTES.md's "Flexible search engine" entry describes
wanting later (a Ctrl+F popup living ABOVE whichever table has focus).
Building that outer layer now means the future search box has an obvious
home instead of forcing another "does this belong inside or outside
CardTableView" decision when it arrives.

WHY THIS IS A SEPARATE WIDGET RATHER THAN CHANGING CardTableView ITSELF:
CardTableView's job (per its own module docstring) is the table: model,
header, selection, hotkeys. A button row above it is part of what SURROUNDS
this tab's content, not part of the table widget. This mirrors a pattern
already established elsewhere in the app -- deck_viewer.py's DeckViewerView
and tag_tree.py's TagTreePanel don't inherit from TreePane, they each HOLD
one (plus a CollapsibleSplitter) inside their own small QWidget. Composing
a CardTableView here the same way means CardTableView itself needs zero
changes, and nothing that already reaches into it (main.py's tag_source
wiring, the status bar's rowCount() read) breaks -- it just now reaches
through self.table instead.

Inventory and Wishlist are both filter LENSES on the one Card Database
table (Have > 0 / Want > 0), not separate tabs or datasets -- see
PROJECT_CONTEXT.md's "recurring patterns" section for why that's the
standing rule in this app. The Inventory toggle excludes qty == "0" from
the Qty column; Wishlist does the same for cross_qty -- identical in
effect to right-clicking that column's header and unchecking "0" by hand.

TOGGLE STATE IS TWO-WAY, NOT A SHORTCUT THAT FIRES AND FORGETS:
Clicking "Inventory" excludes qty == "0" from the Qty column (identical to
manually right-clicking the Have column header and unchecking "0"); it does
NOT touch the Wishlist filter, so both can be active together ("cards I
both own copies of AND still want more of"). The two toggle buttons and the
header's own right-click checklist are two different UIs over the exact
same underlying model state (CardTableModel._column_filters), so they're
kept in sync in BOTH directions:
  - button click -> model, via CardTableModel.set_value_excluded()
  - model change (from EITHER source) -> button, via a modelReset listener
    that re-reads current state and updates checked-ness to match
Only syncing one direction would let a manual header-checklist edit leave
a button showing the wrong state -- silently lying about what filter is
actually applied, which is worse than not having the buttons show state
at all.

KEYBOARD ACCESS TO TABLE HEADERS: headers are themselves
keyboard-focusable (see card_table.py's CardTableHeader), so this row's
own Ctrl+Tab (below) jumps straight to the table's HEADER (leftmost
visible column) rather than a cell -- a header is a meaningfully
different, closer destination than a cell once it's operable on its own.
Plain Tab still lands on a cell.

UP/DOWN VS. LEFT/RIGHT ON A FOCUSED METABUTTON -- these mean genuinely
different things, not "cycle the row" for all four (a real bug in an
earlier version, since fixed): Left/Right move focus along the row of
buttons (wrapping, see _focus_adjacent_metabutton). Down/Up instead
EXPAND/COLLAPSE whichever popup menu the focused button owns (currently
only Columns) -- Down opens it, Up is reserved for closing it. A button
with no menu (Inventory/Wishlist/Clear Filters) just treats Down/Up as a
no-op, since there's nothing to expand or collapse.

MENU TOGGLE + ALT+N WHILE OPEN: a live QMenu grabs the keyboard for the
whole application while showing (see _install_metabutton_keyboard_nav's
own comment on this), which means the Alt+1..4 QShortcuts genuinely can't
fire a second time while a menu they opened is still up -- pressing Alt+3
again to close Columns' menu would otherwise silently do nothing. Fixed
via the SAME application-level eventFilter this class already installs
for its other keyboard handling: it still receives keypresses during a
grab (the same reasoning _MenuSearchBox and ImageZoomWidget's own
outside-click filters depend on elsewhere in this app), so it recognizes
"the hotkey that opened this menu was pressed again" and closes it. See
self._open_menu / _show_columns_menu / _on_columns_menu_closed for the
open/closed tracking this relies on, and card_table.py's _StayOpenMenu
for the matching fix to Up/Down's own native cycling inside the menu
itself (Up at the top now collapses instead of wrapping to the bottom).

MOUSE-CLICK TOGGLE HAD THE SAME PROBLEM, FOR A DIFFERENT REASON, FIXED
THE SAME WAY: clicking the Columns button again while its own menu is
open is, from Qt's point of view, a click OUTSIDE the popup -- QMenu
closes itself for that reason alone. But that same press+release still
goes on to complete a normal button CLICK once the popup is gone, which
re-invokes _show_columns_menu() and reopens exactly what the click just
closed -- visible as the menu collapsing and immediately re-expanding on
every attempted mouse toggle-close (a real, reported bug: Alt+3 toggled
correctly; a mouse click didn't). Fixed the same way as Alt+N above --
intercepted in the SAME application-level eventFilter, BEFORE the press
can complete a click -- but matched by POSITION (the press's global
point against self._open_menu_button's own on-screen rect) rather than
by comparing `watched` against the button directly: while a QMenu holds
the mouse grab, Qt reports `watched` as the MENU for any event routed
through that grab, never the widget visually underneath it -- the exact
same reason the Alt+N branch below can't key off `watched` either.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QApplication
from PySide6.QtCore import Qt, QEvent, QRect
from PySide6.QtGui import QKeySequence, QShortcut

from card_table import CardTableView, COL_QTY, COL_CROSS_QTY
from scaling import scale_manager, sp


def _toggle_style():
    """Function, not a static string -- see main.py's build_stylesheet
    comment for why any QSS carrying a pixel metric has to be rebuilt
    fresh against the current ui_scale rather than frozen at import."""
    return f"""
QPushButton {{
    padding: {sp(5)}px {sp(14)}px;
    border: 1px solid #3a3c41;
    border-radius: {sp(4)}px;
    background-color: #2b2d31;
}}
QPushButton:checked {{
    background-color: #3d6a8f;
    border: 1px solid #4f8fc0;
}}
QPushButton:hover:!checked {{
    background-color: #313338;
}}
QPushButton:focus {{
    /* Same "outline: 0" trick main.py's SideNav buttons already use to
       drop Qt's native dashed focus rectangle -- replaced here with an
       underline on the button's own text instead, a much less visually
       jarring "this has keyboard focus" cue for a row of small buttons
       than a box drawn around them. See _install_metabutton_keyboard_nav
       below for how these buttons are actually navigated once focused. */
    outline: none;
    text-decoration: underline;
}}
"""


class CardDatabaseView(QWidget):
    def __init__(self, cards):
        super().__init__()

        # Public attribute (not a private name) so external code can reach
        # the real table the same way main.py already reaches DeckViewerView
        # .tree_pane / TagTreePanel.tree_pane -- one established convention
        # for "the real content lives one level down," not a new one.
        self.table = CardTableView(cards, qty_label="Have", cross_qty_label="Want")

        self.inventory_toggle = QPushButton("Inventory")
        self.wishlist_toggle = QPushButton("Wishlist")
        for button in (self.inventory_toggle, self.wishlist_toggle):
            button.setCheckable(True)
            button.setStyleSheet(_toggle_style())

        # Not checkable -- this is a plain dropdown-opening button, not a
        # persistent on/off state like the two toggles either side of it.
        # Uses CardTableHeader.build_show_columns_menu(), rebuilt fresh on
        # each open (same pattern card_table.py's own price-source
        # dropdown uses) so it can never show a stale snapshot of which
        # columns are currently visible. See _show_columns_menu for the
        # open/close TOGGLE logic this button now needs (see module
        # docstring's "MENU TOGGLE + ALT+N WHILE OPEN" section).
        self.columns_button = QPushButton("Columns \u25be")
        self.columns_button.setStyleSheet(_toggle_style())
        self.columns_button.clicked.connect(self._show_columns_menu)

        # One-shot action (not checkable, like Columns) -- resets every
        # per-column value filter AND the Mana Cost row's separate mono-
        # only/excluded-color state, AND every filter menu's own
        # remembered search-box text, in one go. Same underlying method
        # (CardTableView.clear_all_filters, which itself wraps
        # CardTableModel.clear_all_filters + CardTableHeader.
        # clear_all_search_memory) the table's own Ctrl+Alt+F shortcut
        # calls -- see card_table.py -- so the button and the hotkey can
        # never drift apart on what "clear filters" actually resets.
        # Deliberately does NOT touch the Inventory/Wishlist toggle
        # buttons directly; they're just another filter on Qty/Cross Qty
        # columns and get reset the same way everything else does, then
        # re-sync themselves via the modelReset listener below like always.
        self.clear_filters_button = QPushButton("Clear Filters")
        self.clear_filters_button.setStyleSheet(_toggle_style())
        self.clear_filters_button.clicked.connect(self.table.clear_all_filters)


        # Direction 1: button -> model. Each button only ever adds/removes
        # the single "0" value from its own column's exclusion set (via
        # set_value_excluded), leaving any OTHER manual exclusion a user
        # set on that same column via the header checklist untouched.
        self.inventory_toggle.toggled.connect(
            lambda checked: self.table.card_model.set_value_excluded(COL_QTY, "0", checked)
        )
        self.wishlist_toggle.toggled.connect(
            lambda checked: self.table.card_model.set_value_excluded(COL_CROSS_QTY, "0", checked)
        )

        # Direction 2: model -> buttons. modelReset already fires at the
        # end of CardTableModel._commit_reorder() -- the one choke point
        # every filter-changing action funnels through, whether it's these
        # buttons, the header checklist, or the search box's Enter-to-filter
        # path -- so listening here catches every source uniformly rather
        # than needing a bespoke signal per code path that can change a filter.
        self.table.card_model.modelReset.connect(self._sync_toggle_buttons)

        # Ordered list of every focusable button in this row -- the single
        # source of truth both the looped-arrow-key navigation and the
        # Alt+1..4 hotkeys below index into, so the two can never disagree
        # about "button 3" being a different button.
        self._meta_buttons = [
            self.inventory_toggle, self.wishlist_toggle,
            self.columns_button, self.clear_filters_button,
        ]

        # Tracks whichever metabutton-owned popup menu is currently open
        # (only Columns has one today, but keying this off the OWNING
        # BUTTON rather than hardcoding "the Columns menu" lets a future
        # menu-owning metabutton reuse the exact same toggle/Down/Up/Alt+N
        # machinery for free). None whenever nothing's open. See
        # _show_columns_menu (toggle open/close), _on_columns_menu_closed
        # (clears this the instant the menu's own aboutToHide fires, for
        # every way it can close), and eventFilter's Alt+N/Down branches.
        self._open_menu = None
        self._open_menu_button = None
        self._metabutton_menu_openers = {self.columns_button: self._show_columns_menu}

        self._install_metabutton_keyboard_nav()

        button_row = QHBoxLayout()
        button_row.setContentsMargins(sp(8), sp(6), sp(8), sp(6))
        button_row.addWidget(self.inventory_toggle)
        button_row.addWidget(self.wishlist_toggle)
        button_row.addWidget(self.columns_button)
        button_row.addWidget(self.clear_filters_button)
        button_row.addStretch()  # reserved space -- future search box lands here
        self._button_row = button_row

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(button_row)
        layout.addWidget(self.table)

        # Live rescaling: re-apply the four buttons' QSS (padding/border-
        # radius) and the row's own margins whenever ui_scale changes --
        # neither is touched automatically by Qt's font-metrics reflow,
        # unlike the buttons' own TEXT, which already scales for free via
        # the app-wide font (see scaling.py).
        scale_manager.scale_changed.connect(self._apply_button_row_scale)

    def _apply_button_row_scale(self):
        for button in self._meta_buttons:
            button.setStyleSheet(_toggle_style())
        self._button_row.setContentsMargins(sp(8), sp(6), sp(8), sp(6))

    def _show_columns_menu(self):
        """
        Opens the Columns visibility-checklist menu -- or, if it's ALREADY
        open, closes it instead (the `if self._open_menu is not None`
        branch below). A second activation -- another click on the
        button, or the same Alt+3 that opened it -- should dismiss it,
        the same "press again to put it away" convention any native popup
        button gets for free. In practice neither activation path relies
        on THIS method being reached naturally a second time to do that:
        both a repeat click and a repeat Alt+3 are intercepted earlier, in
        eventFilter, before the click/keypress that would otherwise
        reopen the menu ever completes -- see that method's own comments
        on the mouse-click and Alt+N branches for why each needs its own
        interception rather than trusting this method's close branch to
        fire on its own. self._open_menu is still the single source of
        truth both this method and eventFilter read/act on.
        """
        if self._open_menu is not None:
            self._open_menu.close()
            return

        menu = self.table.header.build_show_columns_menu()
        self._open_menu = menu
        self._open_menu_button = self.columns_button
        menu.aboutToHide.connect(self._on_columns_menu_closed)
        menu.exec(self.columns_button.mapToGlobal(self.columns_button.rect().bottomLeft()))
        # This menu is parented to the header (see build_show_columns_menu
        # -> _StayOpenMenu(self)), which outlives every menu built from
        # it -- without an explicit teardown, every open here would leave
        # one more hidden, never-deleted menu behind. Same fix, same
        # reasoning, as card_table.py's own CardTableHeader._run_context_menu
        # -- see NOTES.md's "menu search box focus leak" entry.
        menu.deleteLater()
        # Focus goes back to the BUTTON that opened this, not the table.
        # Unlike CardTableHeader's own filter/group-by menus (which
        # open FROM the table's header and hand focus back to the table
        # when they close), this menu opens from a button that lives
        # outside the table entirely -- closing it (via a selection,
        # Escape, an outside click, the menu's own Up-collapse, or the
        # Alt+3 toggle-close above) should leave the user right back
        # where they started, not silently relocate them into the table.
        self.columns_button.setFocus()

    def _on_columns_menu_closed(self):
        """
        Clears the open-menu tracking the instant the menu's own
        aboutToHide fires -- which happens SYNCHRONOUSLY, before
        menu.exec() in _show_columns_menu() above even returns, for every
        way the menu can close: an item picked, Escape, an outside click,
        _StayOpenMenu's own Up-collapse (see card_table.py), or the Alt+3
        toggle-close in eventFilter below. Nothing else needs its own
        separate cleanup path.
        """
        self._open_menu = None
        self._open_menu_button = None

    def _sync_toggle_buttons(self):
        for button, column in (
            (self.inventory_toggle, COL_QTY),
            (self.wishlist_toggle, COL_CROSS_QTY),
        ):
            # blockSignals is required here, not just tidy: setChecked()
            # fires `toggled`, which is connected to set_value_excluded()
            # above -> set_column_filter() -> _commit_reorder() ->
            # modelReset -> this method again. Without blocking, a manual
            # header-checklist edit would recurse back through here a
            # second time (harmlessly, since pass two is a no-op -- the
            # state's already correct -- but it's wasted work and a bad
            # habit to leave in a signal chain that WILL grow later).
            button.blockSignals(True)
            button.setChecked(self.table.card_model.is_value_excluded(column, "0"))
            button.blockSignals(False)

    # --- Meta-button keyboard navigation ---------------------------------
    # Plain QPushButtons in a QHBoxLayout don't loop on arrow keys, and Qt's
    # normal Tab chain would just walk off the last button into whatever's
    # next in the window's focus order (the table, but via the DEFAULT
    # chain, not deliberately). Both are handled explicitly here via an
    # event filter on the four buttons themselves -- same "install a filter
    # to catch a key before the widget's own default handling" pattern
    # collapsible_pane.py (Tab) and card_table.py's _MenuSearchBox
    # (Up/Down) already use elsewhere in this app, rather than subclassing
    # QPushButton four times over for one-off key handling.
    def _install_metabutton_keyboard_nav(self):
        # Installed on the APPLICATION rather than directly on each
        # button. A per-widget installEventFilter() looked like it should
        # be enough on paper (Qt delivers to installed filters before an
        # object's own event() handling either way) -- but in practice it
        # only reliably caught plain Tab and Ctrl+Tab, not Shift+Tab (Qt
        # reports Shift+Tab as a distinct Key_Backtab, and Qt's own
        # internal Tab/Backtab focus-navigation can act on it before a
        # plain per-object filter gets a real chance to consume it first).
        # collapsible_pane.py's module docstring documents this exact
        # class of bug for its own Tab handling and fixes it the same
        # way: an application-level filter runs ahead of that internal
        # handling unconditionally, for every keypress anywhere in the
        # app -- we narrow it straight back down to "was this actually
        # one of our four buttons" (or, for the Alt+N-while-a-menu-is-
        # open case, "is a metabutton menu currently open at all") inside
        # eventFilter below. This SAME app-level reach is also what makes
        # the Alt+N-while-open branch possible in the first place: it
        # still sees keypresses even while a QMenu we opened has the
        # keyboard grab (see module docstring's "MENU TOGGLE + ALT+N
        # WHILE OPEN" section).
        QApplication.instance().installEventFilter(self)
        # Alt+1..4, in the same order as self._meta_buttons -- a faster,
        # mouse-free way to jump straight to a specific meta-button instead
        # of arrowing over from wherever focus currently is. Deliberately
        # NUMBERED rather than per-button letter mnemonics (Qt's normal
        # "&Inventory" -> Alt+I convention) to avoid colliding with this
        # app's existing Alt+A/D/E/W row-action hotkeys (card_table.py).
        # Scoped via WidgetWithChildrenShortcut to this widget (which
        # contains both the buttons AND the table) -- same scoping
        # tree_pane.py's own shortcuts use -- so these only fire while
        # focus is genuinely somewhere in Card Database, and (for free,
        # with no extra guard needed) not at all while a QMenu is open:
        # a live popup menu grabs the keyboard for the whole application
        # while showing, so a shortcut on a background widget simply
        # doesn't get delivered until it closes -- see eventFilter's
        # Alt+N branch for how a SECOND Alt+N (to close that same menu)
        # is handled instead, since it can't rely on this QShortcut firing.
        #
        # Each hotkey ACTIVATES its button (button.click()), not just
        # focuses it -- Alt+1 should behave like actually pressing the
        # Inventory button, toggling it off again on a second press, the
        # same as clicking it would. click() already does the right thing
        # whether the button is checkable (Inventory/Wishlist -- toggles)
        # or a one-shot action (Columns opens its menu -- toggle-closes it
        # via _show_columns_menu if pressed again while it's still able to
        # fire; Clear Filters runs), so there's no need to branch on which
        # kind of button this particular hotkey happens to target.
        self._metabutton_shortcuts = []  # kept alive -- QShortcut has no other owner
        for i, button in enumerate(self._meta_buttons, start=1):
            shortcut = QShortcut(QKeySequence(f"Alt+{i}"), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda b=button: self._activate_metabutton(b))
            self._metabutton_shortcuts.append(shortcut)

    def _activate_metabutton(self, button):
        """Focuses AND activates a meta-button, as if it had been clicked
        -- see _install_metabutton_keyboard_nav's comment on the Alt+1..4
        hotkeys for why click() alone is enough regardless of which of the
        four buttons this is."""
        button.setFocus(Qt.ShortcutFocusReason)
        button.click()

    def _alt_key_for_button(self, button):
        """
        Qt.Key_1..Key_4 map onto self._meta_buttons by POSITION -- the
        same order the Alt+1..4 QShortcuts are bound in above. Used by
        eventFilter to recognize "the same hotkey that opened this menu
        was just pressed again" while a metabutton's menu is open and its
        own QShortcut can't fire a second time (see module docstring's
        "MENU TOGGLE + ALT+N WHILE OPEN" section).
        """
        return Qt.Key_1 + self._meta_buttons.index(button)

    def eventFilter(self, watched, event):
        # Mouse click landing on the open menu's OWNING BUTTON (currently
        # only ever Columns) -- closed HERE, at PRESS time, rather than
        # letting the click complete normally. See module docstring's
        # "MOUSE-CLICK TOGGLE" section for the bug this fixes: without
        # this, the same press both closes the menu (QMenu's own "click
        # outside itself" rule) AND still goes on to finish a normal
        # click on the button once the menu's gone -- reopening what the
        # click just closed. Checked independent of `watched`, and BEFORE
        # the KeyPress-only early return just below, for the same reason
        # the Alt+N branch further down is: while a QMenu holds the mouse
        # grab, Qt reports `watched` as the MENU for any event routed
        # through that grab, never the widget visually underneath it --
        # comparing `watched` against self.columns_button would never
        # match here. Matching by POSITION (the press's global point
        # against the button's own on-screen rect, via
        # self._open_menu_button -- generic over any future menu-owning
        # metabutton, not hardcoded to Columns) is what actually works.
        if event.type() == QEvent.MouseButtonPress and self._open_menu is not None:
            button = self._open_menu_button
            if button is not None:
                global_pos = event.globalPosition().toPoint()
                button_rect = QRect(button.mapToGlobal(button.rect().topLeft()), button.size())
                if button_rect.contains(global_pos):
                    self._metabutton_menu_openers[button]()
                    return True

        if event.type() != QEvent.KeyPress:
            return super().eventFilter(watched, event)

        # A metabutton-owned menu is open (currently only ever Columns)
        # and the SAME Alt+N that opened it was pressed again -- toggle
        # it closed. Checked FIRST and independent of `watched`: a live
        # QMenu grabs the keyboard for the whole application while
        # showing, so `watched` here is the MENU, never one of our
        # buttons -- this event would never reach the `watched in
        # self._meta_buttons` branch below at all, which is exactly why
        # this needs its own separate check rather than folding into it.
        if (self._open_menu is not None and event.modifiers() == Qt.AltModifier
                and event.key() == self._alt_key_for_button(self._open_menu_button)):
            self._metabutton_menu_openers[self._open_menu_button]()
            return True

        if watched not in self._meta_buttons:
            return super().eventFilter(watched, event)

        key = event.key()
        mods = event.modifiers()

        if key in (Qt.Key_Left, Qt.Key_Right):
            self._focus_adjacent_metabutton(watched, -1 if key == Qt.Key_Left else 1)
            return True

        if key == Qt.Key_Down:
            # Down EXPANDS -- opens the focused button's own menu, if it
            # has one (currently only Columns, via
            # self._metabutton_menu_openers). A deliberate no-op for the
            # plain toggle/one-shot buttons, which have nothing to
            # expand. NOT the same as Left/Right (an earlier version
            # aliased Up/Down to the same cycling Left/Right does --
            # fixed here: these are two conceptually different actions,
            # not four-way cycling).
            opener = self._metabutton_menu_openers.get(watched)
            if opener is not None:
                opener()
            return True

        if key == Qt.Key_Up:
            # Up COLLAPSES -- but by construction, a menu can only be open
            # while keyboard events are routed to IT (its own grab), never
            # to a genuinely focused button (see the Alt+N branch above
            # for why an open menu's own Up-collapse is instead handled
            # inside _StayOpenMenu.keyPressEvent, in card_table.py). So Up
            # reaching a focused button here means there is, structurally,
            # nothing currently open to collapse -- still explicitly
            # consumed (not left to fall through to the Left/Right
            # cycling it used to alias) so the "Up/Down mean something
            # different from Left/Right" rule holds without exception.
            return True

        if key == Qt.Key_Escape:
            # A quick, NON-destructive way out of this row -- unlike
            # Tab/Shift+Tab/Ctrl+Tab below (which deliberately jump the
            # table's cell selection to a specific group boundary, see
            # focus_table_for_metabutton_tab), Escape just hands focus
            # back to the table exactly as it already was, leaving
            # whatever cell selection was active before the user
            # tabbed up here completely untouched. A plain setFocus()
            # -- no selection-model call at all -- is what guarantees
            # that: Qt doesn't touch selection state just because
            # focus moves within the same window.
            self.table.setFocus()
            return True

        # Shift+Tab: Qt reports this as a distinct Key_Backtab on most
        # platforms rather than Key_Tab with ShiftModifier set, so both
        # forms are checked -- same belt-and-suspenders check used for
        # this exact ambiguity elsewhere in the app (_MenuSearchBox,
        # CardTableView.keyPressEvent).
        if key == Qt.Key_Backtab or (key == Qt.Key_Tab and mods & Qt.ShiftModifier):
            self.table.focus_table_for_metabutton_tab(backward=True)
            return True
        if key == Qt.Key_Tab and mods == Qt.ControlModifier:
            # Ctrl+Tab specifically goes one level UP from a cell --
            # straight to the table's HEADER row (its leftmost visible
            # column) instead of a card row. Split out from plain Tab
            # below now that headers are keyboard-focusable in their
            # own right (see card_table.py's CardTableHeader) --
            # Ctrl+Tab is the fast, direct path to column sorting/
            # filtering without detouring through the grid first.
            # Focus-only (see CardTableView.focus_leftmost_header) --
            # arriving via a plain focus hop shouldn't also open that
            # column's filter menu.
            self.table.focus_leftmost_header()
            return True
        if key == Qt.Key_Tab and mods == Qt.NoModifier:
            # Plain Tab hands focus to a CELL in the table (landing on
            # its first cell/group) -- see CardTableView.keyPressEvent
            # for what Ctrl+Tab means once focus is actually IN the
            # table (jump to the next group), a separate, later
            # meaning from the header-focused Ctrl+Tab above.
            self.table.focus_table_for_metabutton_tab(backward=False)
            return True

        return super().eventFilter(watched, event)

    def _focus_adjacent_metabutton(self, current_button, direction):
        """
        Moves focus one step (+1/-1) along self._meta_buttons from
        `current_button`, WRAPPING at both ends (Python's % already wraps
        negative indices correctly) -- Left/Right stay a closed loop over
        just these buttons (unlike Tab, which deliberately leaves this
        row instead -- see eventFilter above). Up/Down no longer route
        through here at all (see eventFilter's Down/Up branches) -- they
        mean expand/collapse now, not "cycle like Left/Right."
        """
        index = self._meta_buttons.index(current_button)
        next_index = (index + direction) % len(self._meta_buttons)
        self._meta_buttons[next_index].setFocus(Qt.TabFocusReason)
