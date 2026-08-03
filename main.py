"""
main.py
-------
Entry point. Assembles the Deckbox-style layout: a narrow tab strip on the
left (SideNav) driving a QStackedWidget on the right that swaps between
Tag Database, Card Database, and Deck Viewer.

Card Database is the full browsable catalog (every card, showing both Have
and Want counts) -- there's no separate always-filtered "Inventory" or
"Wishlist" tab anymore; both are just filter LENSES on this same catalog.
CardDatabaseView (card_database_view.py) puts Inventory/Wishlist toggle
buttons above the table as a shortcut for excluding qty == 0 on the Have or
Want column -- the exact same effect as right-clicking that column's header
and unchecking "0" manually, just faster and with visible on/off state.

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
from card_database_view import CardDatabaseView
from options_dialog import OptionsDialog
from mock_data import get_all_cards


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MTG Local Database — Prototype")
        self.resize(1300, 780)

        # --- Build the views that live in the stack ---
        self.tag_panel = TagTreePanel()
        self.card_database = CardDatabaseView(get_all_cards())
        self.deck_viewer = DeckViewerView()

        # Right-click-to-tag needs a reference to the Tag Database's tree --
        # wired here (after both exist) rather than passed into
        # CardDatabaseView's constructor, matching the late-bound tag_source
        # attribute pattern. Goes through .table since CardDatabaseView
        # WRAPS the real CardTableView rather than being one itself (see
        # card_database_view.py's module docstring for why).
        self.card_database.table.tag_source = self.tag_panel.tree_pane

        self.stack = QStackedWidget()
        # Order here defines the stack INDEX for each view; self._tab_indexes
        # below maps the SideNav's string keys to these indexes, so the two
        # never need to be kept in sync by hand elsewhere.
        self.stack.addWidget(self.tag_panel)        # index 0
        self.stack.addWidget(self.card_database)     # index 1
        self.stack.addWidget(self.deck_viewer)         # index 2
        self._tab_indexes = {"tags": 0, "cards": 1, "decks": 2}

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
        becomes active. Tag Database and Deck Viewer focus their tree; Card
        Database focuses the table itself (reached via .table, since
        CardDatabaseView wraps a CardTableView rather than being one -- see
        card_database_view.py). This matters beyond general keyboard-UX
        niceness: it's what makes Tab reliably collapse the tree pane on
        the very FIRST press rather than only from the second press onward
        (see TreePane.focus_tree's docstring).
        """
        current = self.stack.currentWidget()
        if hasattr(current, "tree_pane"):
            current.tree_pane.focus_tree()
        elif hasattr(current, "table"):
            current.table.setFocus()

    def _build_menu_bar(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        import_action = file_menu.addAction("Import...")
        import_action.triggered.connect(self._stub_action("Import"))
        export_action = file_menu.addAction("Export...")
        export_action.triggered.connect(self._stub_action("Export"))
        file_menu.addSeparator()
        options_action = file_menu.addAction("Options...")
        options_action.setShortcut(QKeySequence("Ctrl+,"))
        options_action.triggered.connect(self._open_options)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)

    def _open_options(self):
        # Modal, like TagApplyDialog -- a settings window is exactly the
        # "focused task, dismiss when done" shape .exec() is for, unlike
        # the card detail popup's .show() (browse-while-open) behavior.
        dialog = OptionsDialog(self)
        dialog.exec()

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
        if hasattr(current, "table"):
            count = current.table.card_model.rowCount()
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
QMenu {
    /* Nothing styled QMenu at all before this -- once ANY QSS is applied
       to the application (as main.py does via app.setStyleSheet below),
       Qt's style engine stops relying on the native platform style's
       automatic hover/selected rendering for widgets it hasn't been told
       about. A menu's "currently active/highlighted action" (whether set
       by real mouse hover OR programmatically via QMenu.setActiveAction(),
       as card_table.py's _MenuSearchBox does for keyboard navigation) had
       no visible effect under the app's stylesheet without a matching
       ::item:selected rule below -- the navigation logic itself could be
       working perfectly and still look like nothing was happening.
       Background/border here match QTableView/QTreeWidget's own styling
       above for visual consistency with the rest of the app. */
    background-color: #2b2d31;
    border: 1px solid #3a3c41;
}
QMenu::item {
    padding: 4px 24px 4px 8px;
    background-color: transparent;
}
QMenu::item:selected {
    /* Same selection color QTableView/QTreeWidget already use above --
       this is the rule that makes arrow-key navigation in the filter-menu
       search box (and ordinary mouse hover in every other menu in the
       app) actually visible. */
    background-color: #3d6a8f;
}
QMenu::item:disabled {
    color: #6b6f76;
}
QMenu::separator {
    height: 1px;
    background-color: #3a3c41;
    margin: 4px 0px;
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
