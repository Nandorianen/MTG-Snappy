"""
card_database_view.py
----------------------
Wraps a CardTableView with an outer button row -- Inventory/Wishlist filter-
preset toggles plus a Columns visibility dropdown (replacing what used to be
a "Show Columns" submenu duplicated into every column's own right-click
menu). This is deliberately the same architectural slot NOTES.md's
"Flexible search engine" entry describes wanting later (a Ctrl+F popup
living ABOVE whichever table has focus). Building that outer layer now
means the future search box has an obvious home instead of forcing another
"does this belong inside or outside CardTableView" decision when it arrives.

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

WHY THIS REPLACES THE SEPARATE INVENTORY TAB:
Inventory was always "All Card Database, pre-filtered to Have > 0" --
mock_data.py's get_inventory_cards() and get_all_cards() already returned
identically-shaped rows (same qty/cross_qty source lists), just under two
different function names. That's the exact same redundancy the Wishlist
tab had before it got folded into a filter lens on "All Card Database"
(see PROJECT_CONTEXT.md's "mid-project architectural pivot" section) --
Inventory gets the same treatment here: one table, one Inventory-mode
toggle button standing in for what used to be a whole separate tab.

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
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QApplication
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeySequence, QShortcut

from card_table import CardTableView, COL_QTY, COL_CROSS_QTY

TOGGLE_STYLE = """
QPushButton {
    padding: 5px 14px;
    border: 1px solid #3a3c41;
    border-radius: 4px;
    background-color: #2b2d31;
}
QPushButton:checked {
    background-color: #3d6a8f;
    border: 1px solid #4f8fc0;
}
QPushButton:hover:!checked {
    background-color: #313338;
}
QPushButton:focus {
    /* Same "outline: 0" trick main.py's SideNav buttons already use to
       drop Qt's native dashed focus rectangle -- replaced here with an
       underline on the button's own text instead, a much less visually
       jarring "this has keyboard focus" cue for a row of small buttons
       than a box drawn around them. See _install_metabutton_keyboard_nav
       below for how these buttons are actually navigated once focused. */
    outline: none;
    text-decoration: underline;
}
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
            button.setStyleSheet(TOGGLE_STYLE)

        # Not checkable -- this is a plain dropdown-opening button, not a
        # persistent on/off state like the two toggles either side of it.
        # Reuses the SAME menu-building code that used to be duplicated
        # into every column's own right-click menu (SplitDropdownHeader.
        # build_show_columns_menu) -- one shared instance now, rebuilt
        # fresh on each click (same pattern card_table.py's own price-
        # source dropdown already uses) so it can never show a stale
        # snapshot of which columns are currently visible.
        self.columns_button = QPushButton("Columns \u25be")
        self.columns_button.setStyleSheet(TOGGLE_STYLE)
        self.columns_button.clicked.connect(self._show_columns_menu)

        # One-shot action (not checkable, like Columns) -- resets every
        # per-column value filter AND the Mana Cost row's separate mono-
        # only/excluded-color state in one go. Same underlying model method
        # (CardTableModel.clear_all_filters) the table's own Ctrl+Alt+F
        # shortcut calls -- see card_table.py -- so the button and the
        # hotkey can never drift apart on what "clear filters" actually
        # means. Deliberately does NOT touch the Inventory/Wishlist toggle
        # buttons directly; they're just another filter on Qty/Cross Qty
        # columns and get reset the same way everything else does, then
        # re-sync themselves via the modelReset listener below like always.
        self.clear_filters_button = QPushButton("Clear Filters")
        self.clear_filters_button.setStyleSheet(TOGGLE_STYLE)
        self.clear_filters_button.clicked.connect(self.table.card_model.clear_all_filters)

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
        self._install_metabutton_keyboard_nav()

        button_row = QHBoxLayout()
        button_row.setContentsMargins(8, 6, 8, 6)
        button_row.addWidget(self.inventory_toggle)
        button_row.addWidget(self.wishlist_toggle)
        button_row.addWidget(self.columns_button)
        button_row.addWidget(self.clear_filters_button)
        button_row.addStretch()  # reserved space -- future search box lands here

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(button_row)
        layout.addWidget(self.table)

    def _show_columns_menu(self):
        menu = self.table.header.build_show_columns_menu()
        menu.exec(self.columns_button.mapToGlobal(self.columns_button.rect().bottomLeft()))
        # Focus goes back to the BUTTON that opened this, not the table.
        # Unlike SplitDropdownHeader's own filter/group-by menus (which
        # open FROM the table's header and hand focus back to the table
        # when they close), this menu opens from a button that lives
        # outside the table entirely -- closing it (via a selection, or
        # Escape) should leave the user right back where they started,
        # not silently relocate them into the table underneath.
        self.columns_button.setFocus()

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
        # one of our four buttons" inside eventFilter below.
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
        # doesn't get delivered until it closes.
        #
        # Each hotkey ACTIVATES its button (button.click()), not just
        # focuses it -- Alt+1 should behave like actually pressing the
        # Inventory button, toggling it off again on a second press, the
        # same as clicking it would. click() already does the right thing
        # whether the button is checkable (Inventory/Wishlist -- toggles)
        # or a one-shot action (Columns opens its menu, Clear Filters
        # runs), so there's no need to branch on which kind of button this
        # particular hotkey happens to target.
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

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and watched in self._meta_buttons:
            key = event.key()
            mods = event.modifiers()

            if key in (Qt.Key_Left, Qt.Key_Up):
                self._focus_adjacent_metabutton(watched, -1)
                return True
            if key in (Qt.Key_Right, Qt.Key_Down):
                self._focus_adjacent_metabutton(watched, 1)
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
            if key == Qt.Key_Tab and mods in (Qt.NoModifier, Qt.ControlModifier):
                # Plain Tab and Ctrl+Tab both just hand focus to the table
                # here (landing on its first cell/group) -- Ctrl+Tab's
                # OWN meaning (jump to the next group) only applies once
                # focus is actually inside the table; see
                # CardTableView.keyPressEvent for what Ctrl+Tab does from
                # there on.
                self.table.focus_table_for_metabutton_tab(backward=False)
                return True

        return super().eventFilter(watched, event)

    def _focus_adjacent_metabutton(self, current_button, direction):
        """
        Moves focus one step (+1/-1) along self._meta_buttons from
        `current_button`, WRAPPING at both ends (Python's % already wraps
        negative indices correctly) -- unlike Tab, which deliberately
        leaves this row instead of looping (see eventFilter above), arrow
        keys are meant to stay a closed loop over just these buttons.
        """
        index = self._meta_buttons.index(current_button)
        next_index = (index + direction) % len(self._meta_buttons)
        self._meta_buttons[next_index].setFocus(Qt.TabFocusReason)
