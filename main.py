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
    QStatusBar, QMessageBox, QSplashScreen,
)
from PySide6.QtGui import QKeySequence, QShortcut, QPixmap, QColor, QPainter
from PySide6.QtCore import Qt

from side_nav import SideNav, TABS
from tag_tree import TagTreePanel
from deck_viewer import DeckViewerView
from card_database_view import CardDatabaseView
from mock_data import get_all_cards
# OptionsDialog and DataManagementDialog are deliberately NOT imported here
# at module level -- see _open_options/_open_data_management below.


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MTG Local Database — Prototype")
        self.resize(1300, 780)

        # Options/Data Management are constructed once and reused across
        # opens (see _open_options/_open_data_management below) rather
        # than rebuilt from scratch on every menu click -- a modal
        # settings-style dialog has no reason to discard and rebuild its
        # entire widget tree just because it was closed; nothing in either
        # dialog holds state that needs a fresh start on reopen.
        self._options_dialog = None
        self._data_management_dialog = None

        # --- Build the views that live in the stack ---
        # LAZY VIEW CONSTRUCTION: only the initially-visible tab (Tag
        # Database, per SideNav's own default) gets built during startup.
        # Card Database and Deck Viewer are real, non-trivial widget trees
        # -- CardDatabaseView alone measured ~60ms even against today's
        # tiny 9-card mock dataset, before any real data replaces it --
        # that the user may not look at for a while, or at all, in a given
        # session. Building them anyway on every single launch is exactly
        # the kind of work standing between opening the app and having a
        # usable window that conflicts with this app's snappiness
        # priority. Same lazy-build-on-first-visit pattern
        # VerticalTabDialog already uses for dialog tabs (dialog_common.py)
        # -- see that module's docstring for the general reasoning;
        # applied here to the top-level SideNav tabs instead.
        self._view_builders = [
            ("tags", self._build_tag_panel),
            ("cards", self._build_card_database),
            ("decks", self._build_deck_viewer),
        ]
        # Derived from _view_builders' own order rather than written out a
        # second time -- the two can never drift apart this way.
        self._tab_indexes = {key: i for i, (key, _builder) in enumerate(self._view_builders)}
        self._built_view_indexes = set()

        self.stack = QStackedWidget()
        for _ in self._view_builders:
            self.stack.addWidget(QWidget())  # placeholder, replaced on first visit
        self._ensure_view_built(self._tab_indexes["tags"])  # eager: the default visible tab

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

    def _build_tag_panel(self):
        self.tag_panel = TagTreePanel()
        return self.tag_panel

    def _build_card_database(self):
        self.card_database = CardDatabaseView(get_all_cards())
        # Right-click-to-tag needs a reference to the Tag Database's tree --
        # safe to wire up here (rather than passed into CardDatabaseView's
        # constructor) because Tag Database is always the eager default
        # tab, so self.tag_panel already exists by the time this ever
        # runs, however much later that turns out to be. Goes through
        # .table since CardDatabaseView WRAPS the real CardTableView
        # rather than being one itself (see card_database_view.py's
        # module docstring for why).
        self.card_database.table.tag_source = self.tag_panel.tree_pane
        return self.card_database

    def _build_deck_viewer(self):
        self.deck_viewer = DeckViewerView()
        return self.deck_viewer

    def _ensure_view_built(self, index):
        """Builds the view for `index` and swaps it into the stack, unless
        that's already been done -- see the lazy-construction comment
        above self._view_builders in __init__."""
        if index in self._built_view_indexes:
            return
        _key, builder = self._view_builders[index]
        real_widget = builder()
        placeholder = self.stack.widget(index)
        self.stack.removeWidget(placeholder)
        placeholder.deleteLater()
        self.stack.insertWidget(index, real_widget)
        self._built_view_indexes.add(index)

    def _on_tab_changed(self, key):
        index = self._tab_indexes[key]
        self._ensure_view_built(index)
        self.stack.setCurrentIndex(index)
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
        data_management_action = file_menu.addAction("Data Management...")
        data_management_action.setShortcut(QKeySequence("Ctrl+M"))
        data_management_action.triggered.connect(self._open_data_management)
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
        # Built once, reused thereafter (see self._options_dialog's own
        # comment in __init__). The import itself is deferred to here
        # too, not done at module level -- options_dialog.py (plus
        # dialog_common.py and tree_pane's ICON_PALETTE it pulls in)
        # measured a real, nonzero import cost; paying that on every
        # single app launch, whether or not this menu item is ever
        # clicked in a given session, is exactly the kind of avoidable
        # startup work this app's snappiness priority argues against.
        # Python caches the import either way, so this only costs
        # anything on the FIRST open, same as OptionsDialog itself.
        if self._options_dialog is None:
            from options_dialog import OptionsDialog
            self._options_dialog = OptionsDialog(self)
        self._options_dialog.exec()

    def _open_data_management(self):
        if self._data_management_dialog is None:
            from data_management_dialog import DataManagementDialog
            self._data_management_dialog = DataManagementDialog(self)
        self._data_management_dialog.exec()

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
QScrollBar:vertical, QScrollBar:horizontal {
    /* Added alongside DataManagementDialog's scroll areas (its Metadata/
       Card Images/Decks & Tags tabs are the first place this app uses a
       QScrollArea). Same lesson as the QMenu rules above, pre-empted this
       time instead of rediscovered: once ANY custom QSS is applied to the
       QApplication, Qt stops rendering EVERY unstyled native widget with
       its normal platform look, not just the ones we happen to be testing
       -- a scrollbar with no rule here would show up as a jarring light
       native bar in an otherwise flat dark app. */
    background: #1e1f22;
    border: none;
    margin: 0px;
}
QScrollBar:vertical { width: 12px; }
QScrollBar:horizontal { height: 12px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #3a3c41;
    border-radius: 5px;
}
QScrollBar::handle:vertical { min-height: 24px; }
QScrollBar::handle:horizontal { min-width: 24px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: #4f8fc0;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    height: 0px;
    width: 0px;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
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


def _build_splash_pixmap():
    """
    Drawn with QPainter rather than loading a bundled image file -- same
    reasoning tree_pane.py's own _make_icon() already established for
    icons: no extra asset to ship or a new dependency to manage, and a
    solid-color pixmap plus a couple of drawText() calls is plenty for a
    screen that's only ever on-screen for a moment.
    """
    pixmap = QPixmap(380, 220)
    pixmap.fill(QColor("#1e1f22"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#3a3c41"))
    painter.drawRect(pixmap.rect().adjusted(0, 0, -1, -1))
    painter.setPen(QColor("#e3e3e3"))
    title_font = painter.font()
    title_font.setPointSize(15)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(pixmap.rect().adjusted(0, -20, 0, -20), Qt.AlignCenter, "MTG Local Database")
    painter.end()
    return pixmap


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE_SHEET)

    # Shown immediately, before MainWindow's own construction (which does
    # real, measurable work -- see the lazy-view-construction comment in
    # MainWindow.__init__) even begins. This doesn't make the app launch
    # any FASTER -- most of a cold Qt app's startup cost is native
    # libraries loading, which is well outside anything Python-level code
    # can speed up -- but it means the user sees SOMETHING respond to
    # their double-click right away instead of a blank/frozen window for
    # however long that takes. Standard, honest mitigation for PERCEIVED
    # responsiveness in any native-toolkit-heavy GUI app's cold start;
    # doesn't pretend to fix the underlying cost, just stops hiding it
    # behind nothing happening.
    splash = QSplashScreen(_build_splash_pixmap())
    splash.showMessage("Loading\u2026", Qt.AlignHCenter | Qt.AlignBottom, QColor("#a8adb5"))
    splash.show()
    app.processEvents()  # force the splash to actually paint before MainWindow's construction blocks the event loop

    window = MainWindow()
    window.show()
    splash.finish(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
