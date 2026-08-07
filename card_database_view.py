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

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton

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
