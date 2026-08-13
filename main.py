"""
main.py
-------
Entry point. Assembles the Deckbox-style layout: a narrow tab strip on the
left (SideNav) driving a QStackedWidget on the right that swaps between
Card Database, Tag Database, and Deck Viewer (in that order -- see
side_nav.py's TABS).

The app opens with NO tab selected -- an empty placeholder pane ("Open
any of the tabs on the left...") until the user picks one -- see
self._build_empty_state() and the stack-index-offset comment in __init__.
Tabs are switchable via 1/2/3 (no Ctrl -- see _handle_digit_shortcut)
matching TABS' order, in addition to clicking the side nav.

Card Database is the full browsable catalog (every card, showing both Have
and Want counts); Inventory and Wishlist are filter LENSES on it, not
separate tabs -- see card_database_view.py's CardDatabaseView, which puts
Inventory/Wishlist toggle buttons above the table as a shortcut for
excluding qty == 0 on the Have or Want column (the same effect as right-
clicking that column's header and unchecking "0" manually, just faster
and with visible on/off state).

The detail view lives in card_table.py's hover popover, leaving the full
window width available for the spreadsheet itself.
"""

import sys
from collections import deque
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QLabel, QStackedWidget,
    QStatusBar, QMessageBox, QSplashScreen, QLineEdit,
)
from PySide6.QtGui import QKeySequence, QPixmap, QColor, QPainter
from PySide6.QtCore import Qt, QEvent, QTimer

from side_nav import SideNav, TABS
from tag_tree import TagTreePanel
from deck_viewer import DeckViewerView
from card_database_view import CardDatabaseView
from mock_data import get_all_cards
# OptionsDialog and DataManagementDialog are deliberately NOT imported here
# at module level -- see _open_options/_open_data_management, and the
# background-preload block in __init__, below.

# How long to wait between each background-preload step, in milliseconds.
# Long enough that a click/keypress arriving mid-preload gets its turn on
# the event loop before the NEXT chunk of construction starts (Qt services
# pending input/paint events ahead of a timer that hasn't fired yet); short
# enough that preloading everything only takes a few hundred ms total once
# the app is sitting idle after launch. Not tuned against real hardware --
# a reasonable starting guess, easy to adjust in one place if it ever feels
# too eager or too slow in practice.
PRELOAD_STEP_DELAY_MS = 60


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
        # LAZY VIEW CONSTRUCTION: no tab is built during startup -- the
        # app opens on the empty-state placeholder (see below), so EVERY
        # tab is deferred until either the user clicks it or the
        # background preload queue gets to it. Card Database and Deck
        # Viewer are real, non-trivial widget trees -- CardDatabaseView
        # alone measured ~60ms even against today's tiny 9-card mock
        # dataset, before any real data replaces it -- so building any of
        # them before they're actually needed is exactly the kind of work
        # standing between opening the app and having a usable window,
        # which conflicts with this app's snappiness priority. Same
        # lazy-build-on-first-visit pattern VerticalTabDialog uses for
        # dialog tabs (dialog_common.py) -- see that module's docstring
        # for the general reasoning; applied here to the top-level
        # SideNav tabs instead.
        #
        # Lazy alone just MOVES the one-time construction cost from launch
        # to "whenever the user first clicks over" -- still a real, felt
        # hitch, just at a worse moment (mid-interaction instead of before
        # the window's even up). See the background-preload block near the
        # end of __init__ for how that gap gets closed without giving the
        # snappy-launch win back.
        self._view_builders = [
            ("cards", self._build_card_database),
            ("tags", self._build_tag_panel),
            ("decks", self._build_deck_viewer),
        ]
        # Derived from _view_builders' own order rather than written out a
        # second time -- the two can never drift apart this way. Offset by
        # STACK_OFFSET below since index 0 in the real QStackedWidget is
        # the empty-state placeholder, not a tab.
        self._tab_indexes = {key: i for i, (key, _builder) in enumerate(self._view_builders)}
        self._built_view_indexes = set()

        # index 0 = the "nothing open yet" placeholder shown at startup;
        # every real tab's stack position is its _view_builders index + 1.
        self.STACK_OFFSET = 1
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty_state())
        for _ in self._view_builders:
            self.stack.addWidget(QWidget())  # placeholder, replaced on first visit
        # No tab is built eagerly here -- the app opens on the empty-state
        # pane above, and every real tab is left to the background preload
        # queue below / an actual click.

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
        self._focus_current_view()  # no-op until a tab is actually opened

        # --- Background preload: fill the idle time AFTER launch instead
        # of wasting it, without giving back the fast-launch win above. ---
        #
        # NOT a real background thread: Qt widgets are not thread-safe --
        # constructing (or touching) a QWidget from anywhere but the GUI
        # thread is undefined behavior, full stop. There's no safe way to
        # build CardDatabaseView or OptionsDialog on a QThreadPool worker
        # the way data_management_dialog.py's _StatWorker safely backgrounds
        # a plain os.stat() call.
        #
        # So "async" here means a staggered TIMER CHAIN on the main thread
        # instead: one queued task runs, then schedules the next one after
        # PRELOAD_STEP_DELAY_MS rather than looping straight through the
        # whole queue in one call. That gap is what keeps this from just
        # being an eager-construction-at-launch freeze moved a few
        # hundred ms later -- Qt gets to service any pending input/paint
        # event in between two preload steps, so a click during preload
        # doesn't queue up behind one long unbroken freeze.
        #
        # Every queued task reuses the EXACT SAME builder/guard a user
        # triggering it directly would hit (_ensure_view_built's
        # already-built check; _options_dialog/_data_management_dialog's
        # `is None` check) -- so whichever happens first, this queue or
        # the user actually clicking/opening the real thing, the other is
        # just a harmless no-op. Nothing downstream needed to change.
        self._preload_queue = deque([
            lambda: self._ensure_view_built(self._tab_indexes["cards"]),
            lambda: self._ensure_view_built(self._tab_indexes["tags"]),
            lambda: self._ensure_view_built(self._tab_indexes["decks"]),
            self._preload_options_dialog,
            self._preload_data_management_dialog,
        ])
        QTimer.singleShot(PRELOAD_STEP_DELAY_MS, self._run_next_preload_step)

        # Digit-only (no Ctrl) tab shortcuts -- see _handle_digit_shortcut
        # for why this is an app-level event filter rather than a plain
        # QShortcut: a QShortcut would steal '1'/'2'/'3' away from any
        # text field (a filter search box, an in-progress Qty edit)
        # before that widget ever saw the keystroke.
        QApplication.instance().installEventFilter(self)

    def _build_empty_state(self):
        """
        The pane shown before the user has opened any tab -- launching the
        app never silently commits to building a tab the user didn't
        actually ask for.
        """
        label = QLabel("Open any of the tabs on the left to view their contents.")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #a8adb5;")
        return label

    def _build_tag_panel(self):
        self.tag_panel = TagTreePanel()
        return self.tag_panel

    def _build_card_database(self):
        # Right-click-to-tag needs a reference to the Tag Database's tree.
        # Views build lazily on first visit (see the empty-state startup
        # design above), so Tag Database isn't guaranteed to exist yet by
        # the time this runs -- explicitly ensure it first rather than
        # assuming some other code path already triggered it. Reuses the
        # same guarded builder every other path goes through, so this is a
        # harmless no-op if Tag Database already exists.
        self._ensure_view_built(self._tab_indexes["tags"])
        self.card_database = CardDatabaseView(get_all_cards())
        # Goes through .table since CardDatabaseView WRAPS the real
        # CardTableView rather than being one itself (see
        # card_database_view.py's module docstring for why).
        self.card_database.table.tag_source = self.tag_panel.tree_pane
        return self.card_database

    def _build_deck_viewer(self):
        self.deck_viewer = DeckViewerView()
        return self.deck_viewer

    def _ensure_view_built(self, index):
        """Builds the view for `index` (an index into self._view_builders,
        NOT a stack position -- see STACK_OFFSET) and swaps it into the
        stack, unless that's already been done -- see the lazy-
        construction comment above self._view_builders in __init__.
        Called from BOTH the on-demand tab-click path (_on_tab_changed)
        and the background preload queue -- this shared guard is what
        makes calling it twice (once from each, in either order) safe and
        free the second time."""
        if index in self._built_view_indexes:
            return
        _key, builder = self._view_builders[index]
        real_widget = builder()
        stack_index = index + self.STACK_OFFSET
        placeholder = self.stack.widget(stack_index)
        self.stack.removeWidget(placeholder)
        placeholder.deleteLater()
        self.stack.insertWidget(stack_index, real_widget)
        self._built_view_indexes.add(index)

    def _on_tab_changed(self, key):
        index = self._tab_indexes[key]
        self._ensure_view_built(index)
        self.stack.setCurrentIndex(index + self.STACK_OFFSET)
        self._refresh_status_bar(key)
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
        (see TreePane.focus_tree's docstring). The empty-state placeholder
        has neither attribute, so this is a no-op before any tab is opened.
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
        #
        # By the time a user actually clicks this, the background preload
        # queue (see __init__) has often already built self._options_dialog
        # -- in which case this is just an .exec() on an existing instance,
        # with none of the ~construction cost paid live. If preload hasn't
        # reached it yet (or the user is fast), this builds it the same way
        # _preload_options_dialog does, on demand, exactly as before that
        # queue existed. Either path is safe to hit first; see
        # _preload_options_dialog's docstring for why.
        if self._options_dialog is None:
            from options_dialog import OptionsDialog
            self._options_dialog = OptionsDialog(self)
        self._options_dialog.exec()

    def _open_data_management(self):
        if self._data_management_dialog is None:
            from data_management_dialog import DataManagementDialog
            self._data_management_dialog = DataManagementDialog(self)
        self._data_management_dialog.exec()

    # --- Background preload queue ---------------------------------------
    def _run_next_preload_step(self):
        """
        Pops and runs exactly ONE queued preload task, then -- if more are
        left -- schedules the next one after another PRELOAD_STEP_DELAY_MS
        gap rather than draining the whole queue in one call. That gap is
        the entire mechanism: it's what lets the event loop service any
        input/paint event that arrived while this step ran before the next
        chunk of construction starts, instead of the user's click sitting
        behind one long unbroken run of widget-building. See __init__'s
        background-preload comment for why this is a staggered main-thread
        timer chain rather than an actual background thread.
        """
        if not self._preload_queue:
            return
        task = self._preload_queue.popleft()
        task()
        if self._preload_queue:
            QTimer.singleShot(PRELOAD_STEP_DELAY_MS, self._run_next_preload_step)

    def _preload_options_dialog(self):
        """
        Same construction _open_options() does on demand -- just run early
        and quietly, from the background preload queue, instead of live
        under a menu click. Guarded by the identical `is None` check
        _open_options() uses, so whichever runs first -- this preload step,
        or the user genuinely opening File > Options before their turn in
        the queue comes up -- the other is a harmless no-op, not a
        double-build.
        """
        if self._options_dialog is None:
            from options_dialog import OptionsDialog
            self._options_dialog = OptionsDialog(self)

    def _preload_data_management_dialog(self):
        """Same reasoning as _preload_options_dialog, for Data Management."""
        if self._data_management_dialog is None:
            from data_management_dialog import DataManagementDialog
            self._data_management_dialog = DataManagementDialog(self)

    def _stub_action(self, name):
        def handler():
            QMessageBox.information(self, name, f"{name} isn't implemented yet.")
        return handler

    def _build_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._refresh_status_bar(None)  # empty state at startup -- nothing to report yet

    def _refresh_status_bar(self, key):
        current = self.stack.currentWidget()
        if hasattr(current, "table"):
            count = current.table.card_model.rowCount()
            self.status_bar.showMessage(f"{count} cards")
        elif key == "tags":
            self.status_bar.showMessage("Tag database")
        elif key == "decks":
            self.status_bar.showMessage("Deck viewer")
        else:
            self.status_bar.clearMessage()  # the empty-state placeholder -- nothing open

    # --- Digit-only tab shortcuts (1/2/3, no Ctrl) -----------------------
    # A plain QShortcut bound to Key_1/2/3 would intercept those keys
    # ahead of whichever widget actually has focus -- including a filter
    # search box or an in-progress Qty cell edit, both real QLineEdits a
    # user might legitimately be typing a digit into. An app-level event
    # filter lets this check what's actually focused first, the same
    # "install on QApplication, decide case-by-case" pattern
    # collapsible_pane.py and card_table.py's _MenuSearchBox already use
    # for analogous "this key means something different depending on
    # context" situations.
    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and event.modifiers() == Qt.NoModifier:
            key = event.key()
            if key in (Qt.Key_1, Qt.Key_2, Qt.Key_3) and self._digit_shortcuts_active():
                index = {Qt.Key_1: 0, Qt.Key_2: 1, Qt.Key_3: 2}[key]
                self.side_nav.select_tab(TABS[index][0])
                return True
        return super().eventFilter(watched, event)

    def _digit_shortcuts_active(self):
        """
        Only treat a bare 1/2/3 as a tab switch when: this window (not a
        modal dialog like Options) is the active one, AND focus isn't
        sitting in a text-entry widget that legitimately wants to receive
        a literal digit -- a filter menu's search box, the Qty column's F2
        edit, a QLineEdit anywhere in a dialog, etc. QLineEdit covers all
        of those (every editable text field in this app, including the
        table's own default cell editor, is a QLineEdit under the hood).
        """
        if QApplication.activeWindow() is not self:
            return False
        return not isinstance(QApplication.focusWidget(), QLineEdit)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)


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
    /* Required for keyboard navigation to be visible: once ANY QSS is
       applied to the QApplication, Qt's style engine stops relying on
       the native platform style's automatic hover/selected rendering for
       widgets it hasn't been told about. Without a matching
       ::item:selected rule below, a menu's "currently active/highlighted
       action" (set via mouse hover OR programmatically via
       QMenu.setActiveAction(), as card_table.py's _MenuSearchBox does
       for keyboard navigation) has no visible effect -- the navigation
       logic can be working perfectly and still look like nothing is
       happening (see NOTES.md's "state-vs-visibility" debugging entry).
       Background/border match QTableView/QTreeWidget's own styling above
       for visual consistency. */
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
    /* Same principle as the QMenu rule above: once ANY custom QSS is
       applied to the QApplication, Qt stops rendering EVERY unstyled
       native widget with its normal platform look, not just the ones
       being tested -- a QScrollArea (used by Data Management's tabs)
       with no rule here would show up as a jarring light native bar in
       an otherwise flat dark app. */
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
    /* Same focus-rectangle removal as above -- without it, Qt paints its
       native dashed focus rect immediately on click, while the checked-
       state color only arrives once our own styling catches up, so a
       press visibly shows "dashed rectangle, THEN highlight" as two
       separate steps instead of one. */
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
