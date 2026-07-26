"""
main.py
-------
Entry point. Assembles the Deckbox-style layout: a narrow tab strip on the
left (SideNav) driving a QStackedWidget on the right that swaps between the
Tag Database view and the Inventory / Wishlist spreadsheets.

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
from mock_data import get_inventory_cards, get_wishlist_cards


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MTG Local Database — Prototype")
        self.resize(1300, 780)

        # --- Build the views that live in the stack ---
        self.tag_panel = TagTreePanel()
        self.inventory_table = CardTableView(get_inventory_cards())
        self.wishlist_table = CardTableView(get_wishlist_cards())
        self.deck_viewer = DeckViewerView()

        self.stack = QStackedWidget()
        # Order here defines the stack INDEX for each view; self._tab_indexes
        # below maps the SideNav's string keys to these indexes, so the two
        # never need to be kept in sync by hand elsewhere.
        self.stack.addWidget(self.tag_panel)         # index 0
        self.stack.addWidget(self.inventory_table)    # index 1
        self.stack.addWidget(self.wishlist_table)      # index 2
        self.stack.addWidget(self.deck_viewer)          # index 3
        self._tab_indexes = {"tags": 0, "inventory": 1, "wishlist": 2, "decks": 3}

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

    def _on_tab_changed(self, key):
        self.stack.setCurrentIndex(self._tab_indexes[key])
        self._refresh_status_bar()

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
QTableView, QTreeWidget {
    background-color: #2b2d31;
    border: 1px solid #3a3c41;
    gridline-color: #3a3c41;
}
QTableView::item:selected, QTreeWidget::item:selected {
    background-color: #3d6a8f;
}
QHeaderView::section {
    background-color: #2b2d31;
    border: 1px solid #3a3c41;
    padding: 4px;
}
SideNav QPushButton {
    text-align: left;
    padding: 8px;
    border: none;
    border-radius: 4px;
    background-color: transparent;
}
SideNav QPushButton:checked {
    background-color: #3d6a8f;
}
SideNav QPushButton:hover:!checked {
    background-color: #2b2d31;
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
