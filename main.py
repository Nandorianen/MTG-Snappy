"""
main.py
-------
Entry point. Assembles the Deckbox-style layout: a narrow tab strip on the
left (SideNav) driving a QStackedWidget on the right that swaps between
Tag Database, All Card Database, Inventory, and Deck Viewer.

All Card Database is the full browsable catalog (every card, showing both
Have and Want counts); Inventory is the same underlying kind of data
filtered down to what you actually own. There's no separate always-filtered
"Wishlist" view anymore -- right-click the Have or Want column and uncheck
"0" to get that lens on demand, from either table.

This replaces the earlier three-panel-with-persistent-detail-panel design --
the detail view now lives in card_table.py's hover popover instead of a
fixed panel, freeing up horizontal space for the spreadsheet itself.
"""

import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QStackedWidget,
    QStatusBar, QMessageBox,
)
from PySide6.QtGui import QKeySequence, QShortcut

from side_nav import SideNav, TABS
from tag_tree import TagTreePanel
from deck_viewer import DeckViewerView
from card_table import CardTableView
from mock_data import get_inventory_cards, get_all_cards


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MTG Local Database — Prototype")
        self.resize(1300, 780)

        # --- Build the views that live in the stack ---
        self.tag_panel = TagTreePanel()
        self.all_cards_table = CardTableView(get_all_cards(), qty_label="Have", cross_qty_label="Want")
        self.inventory_table = CardTableView(get_inventory_cards(), qty_label="Have", cross_qty_label="Want")
        self.deck_viewer = DeckViewerView()

        self.stack = QStackedWidget()
        # Order here defines the stack INDEX for each view; self._tab_indexes
        # below maps the SideNav's string keys to these indexes, so the two
        # never need to be kept in sync by hand elsewhere.
        self.stack.addWidget(self.tag_panel)          # index 0
        self.stack.addWidget(self.all_cards_table)     # index 1
        self.stack.addWidget(self.inventory_table)      # index 2
        self.stack.addWidget(self.deck_viewer)           # index 3
        self._tab_indexes = {"tags": 0, "all_cards": 1, "inventory": 2, "decks": 3}

        # --- Side nav ---
        self.side_nav = SideNav()
        self.side_nav.view_changed.connect(self._on_tab_changed)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.side_nav)
        layout.addWidget(self.stack)
        self.setCentralWidget(central)

        self._build_menu_bar()
        self._build_status_bar()
        self._build_shortcuts()
        self._focus_current_view()  # deterministic initial focus, not Qt's default guess

    def _on_tab_changed(self, key):
        self.stack.setCurrentIndex(self._tab_indexes[key])
        self._refresh_status_bar()
        self._focus_current_view()

    def _focus_current_view(self):
        """
        Gives a specific, sensible widget keyboard focus whenever a tab
        becomes active. Tag Database and Deck Viewer focus their tree;
        Inventory/Wishlist focus the table itself. This matters beyond
        general keyboard-UX niceness: it's what makes Tab reliably collapse
        the tree pane on the very FIRST press rather than only from the
        second press onward (see TreePane.focus_tree's docstring).
        """
        current = self.stack.currentWidget()
        if hasattr(current, "tree_pane"):
            current.tree_pane.focus_tree()
        elif isinstance(current, CardTableView):
            current.setFocus()

    def _build_menu_bar(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        import_action = file_menu.addAction("Import...")
        import_action.triggered.connect(self._stub_action("Import"))
        export_action = file_menu.addAction("Export...")
        export_action.triggered.connect(self._stub_action("Export"))
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)

    def _stub_action(self, name):
        def handler():
            QMessageBox.information(self, name, f"{name} isn't implemented yet.")
        return handler

    def _build_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._refresh_status_bar()

    def _refresh_status_bar(self):
        current = self.stack.currentWidget()
        if isinstance(current, CardTableView):
            count = current.card_model.rowCount()
            self.status_bar.showMessage(f"{count} cards")
        else:
            self.status_bar.showMessage("Tag database")

    def _build_shortcuts(self):
        # Ctrl+1/2/3 jump directly to a tab, in the same order as TABS in
        # side_nav.py -- defined there once so this loop and the button
        # order can never drift apart.
        for i, (key, _label) in enumerate(TABS, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            shortcut.activated.connect(lambda k=key: self.side_nav.select_tab(k))


STYLE_SHEET = """
QWidget {
    background-color: #1e1f22;
    color: #e3e3e3;
    font-size: 13px;
}
QTableView, QTreeWidget, QListWidget {
    background-color: #2b2d31;
    border: 1px solid #3a3c41;
    gridline-color: #3a3c41;
    /* Removes the platform's own dashed/dotted "current item" focus
       rectangle (a native Windows-style artifact in particular) that Qt
       draws on top of the selection highlight by default. We already show
       selection clearly via background-color below; the extra native
       focus outline just looks like a visual bug on top of it. */
    outline: 0;
}
QTableView::item:selected, QTreeWidget::item:selected {
    background-color: #3d6a8f;
}
QTableView::item:focus, QTreeWidget::item:focus {
    outline: none;
    border: none;
}
QHeaderView::section {
    background-color: #141517;
    border: 1px solid #3a3c41;
    padding: 4px;
}
SideNav QPushButton {
    text-align: left;
    padding: 8px;
    border: none;
    border-radius: 4px;
    background-color: transparent;
    /* Same focus-rectangle removal as above -- this was the actual cause
       of the visible "dashed rectangle THEN highlight" two-step: the
       native focus rect painted immediately on click, and only the
       checked-state color came from our own styling, so they visibly
       arrived in two separate steps. */
    outline: 0;
}
SideNav QPushButton:checked {
    background-color: #3d6a8f;
}
SideNav QPushButton:hover:!checked {
    background-color: #2b2d31;
}
SideNav QPushButton:pressed {
    /* Shows the highlight color the instant the mouse/touch goes DOWN,
       rather than waiting for release (when Qt actually fires the
       checked-state change) -- this is what makes the click feel
       immediate rather than laggy, especially noticeable on a touchpad
       where press-to-release timing is longer. */
    background-color: #3d6a8f;
}
"""


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE_SHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
