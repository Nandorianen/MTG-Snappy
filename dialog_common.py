"""
dialog_common.py
-----------------
Shared chrome for every "vertical tab list + stacked pages" modal window in
this app (OptionsDialog, DataManagementDialog, and any future one). Pulled
out once a SECOND such dialog needed the exact same tab-list/stack/
Ctrl+Tab wiring OptionsDialog already had, rather than copying that
~40-line pattern a second time.

WHY A SHARED BASE CLASS, NOT JUST SHARED CONSTANTS:
The tab-list-plus-stack wiring (building the QListWidget, syncing it to a
QStackedWidget, installing Ctrl+Tab/Ctrl+Shift+Tab/Ctrl+PgUp/PgDn shortcuts
that work regardless of which child widget currently has focus, setting
initial focus) is genuinely IDENTICAL behavior across every dialog that
wants this layout, not just similar-looking styling. Sharing only the QSS
strings and re-writing that wiring per dialog would still duplicate the
actual LOGIC. A base class is the right level to share this at.

WHY DataManagementDialog DOESN'T JUST SUBCLASS OptionsDialog:
They're siblings, not a hierarchy -- neither is a specialization of the
other, they just happen to want the same CHROME. Making one dialog inherit
from another because they look alike would tie their fates together for
the wrong reason (a change meant only for Options' settings-specific
behavior could leak into Data Management, or vice versa). Both depending
on one small shared base avoids that.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QListWidget, QListWidgetItem, QStackedWidget, QAbstractItemView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

from frameless_dialog import FramelessDialog

TAB_LIST_STYLE = """
QListWidget {
    background-color: transparent;
    border: none;
    outline: 0;
}
QListWidget::item {
    padding: 10px 14px;
    border-radius: 4px;
    margin: 2px 6px;
}
QListWidget::item:selected {
    background-color: #3d6a8f;
    color: #ffffff;
}
QListWidget::item:hover:!selected {
    background-color: #2b2d31;
}
"""

# Same accent-fill "this is the primary action" button reused by
# CardDatabaseView's Inventory/Wishlist toggles, CardDetailDialog's Apply
# button, and every settings-style dialog since -- one visual language for
# "the button that actually does the thing," app-wide.
APPLY_BUTTON_STYLE = """
QPushButton {
    padding: 5px 16px;
    border: 1px solid #4f8fc0;
    border-radius: 4px;
    background-color: #3d6a8f;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #4f8fc0;
}
"""

DANGER_BUTTON_STYLE = """
QPushButton {
    padding: 5px 14px;
    border: 1px solid #a83a3a;
    border-radius: 4px;
    background-color: transparent;
    color: #d3898f;
}
QPushButton:hover {
    background-color: #a83a3a;
    color: white;
}
"""


def vline():
    """Thin vertical rule -- e.g. separating a tab list from its page area."""
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setStyleSheet("color: #3a3c41;")
    return line


def section_label(text):
    """Small caps-style gray caption -- matches StatField's stat captions in
    card_detail_popup.py, reused here as a STYLE CHOICE (not a code import)
    so every settings-style page reads as the same visual family."""
    label = QLabel(text)
    label.setStyleSheet("color: #a8adb5; font-size: 11px; font-weight: 600;")
    return label


class VerticalTabDialog(FramelessDialog):
    """
    Base for a modal window shaped like: a vertical list of tabs on the
    left, a stack of pages on the right, an optional footer row along the
    bottom. Subclasses provide the tabs and pages; this class builds and
    wires the tab list and stack, and handles all the keyboard plumbing.

    Subclasses MUST implement `build_pages()` (returns a list of QWidget
    pages, same order as the `tab_specs` passed to __init__) and MAY
    override `build_footer()` (returns a QWidget for the bottom row, or
    None for no footer -- the default).

    KEYBOARD SUPPORT (originally worked out for OptionsDialog; now shared
    by everything built on this base):
      - Up/Down/Home/End/type-ahead in the tab list -- free, from
        QListWidget, not reimplemented.
      - Tab/Shift+Tab moves focus through a page's own controls in the
        order they were added to that page's layout -- free, from Qt's
        normal focus chain.
      - Ctrl+Tab / Ctrl+Shift+Tab (and Ctrl+PageDown / Ctrl+PageUp) switch
        tabs from ANYWHERE in the dialog, bound via
        WidgetWithChildrenShortcut (same pattern tree_pane.py uses for its
        own shortcuts) so they fire regardless of which child currently
        holds focus.
      - Escape closes (native QDialog behavior); Enter/Return activates
        whichever button is set as the dialog's default -- neither is
        reimplemented here.
    """

    def __init__(self, title, tab_specs, parent=None):
        super().__init__(title, parent)

        self.tab_list = QListWidget()
        self.tab_list.setFixedWidth(180)
        self.tab_list.setStyleSheet(TAB_LIST_STYLE)
        self.tab_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tab_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for _key, label in tab_specs:
            self.tab_list.addItem(QListWidgetItem(label))

        self.stack = QStackedWidget()
        for page in self.build_pages():
            self.stack.addWidget(page)
        # Selecting a tab and showing its page are the same action here --
        # unlike CardDatabaseView's Inventory/Wishlist buttons (which sync
        # two independent UIs over one shared model), there's only one
        # source of truth for "which tab is active," so a direct signal
        # connection is enough.
        self.tab_list.currentRowChanged.connect(self.stack.setCurrentIndex)

        body = QHBoxLayout()
        body.setSpacing(0)
        page_container = QWidget()
        page_layout = QVBoxLayout(page_container)
        page_layout.setContentsMargins(18, 10, 10, 10)
        page_layout.addWidget(self.stack)
        body.addWidget(self.tab_list)
        body.addWidget(vline())
        body.addWidget(page_container, stretch=1)
        self.content_layout.addLayout(body)

        footer = self.build_footer()
        if footer is not None:
            self.content_layout.addWidget(footer)

        self._install_tab_shortcuts()
        self.tab_list.setCurrentRow(0)
        self.tab_list.setFocus()

    # --- Subclass hooks ------------------------------------------------
    def build_pages(self):
        raise NotImplementedError

    def build_footer(self):
        return None

    # --- Keyboard: tab-switching from anywhere in the dialog ------------
    def _install_tab_shortcuts(self):
        def bind(sequence, slot):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
            return shortcut

        self._sc_next_tab = bind("Ctrl+Tab", lambda: self._step_tab(1))
        self._sc_prev_tab = bind("Ctrl+Shift+Tab", lambda: self._step_tab(-1))
        self._sc_next_tab_pg = bind("Ctrl+PgDown", lambda: self._step_tab(1))
        self._sc_prev_tab_pg = bind("Ctrl+PgUp", lambda: self._step_tab(-1))

    def _step_tab(self, direction):
        count = self.tab_list.count()
        self.tab_list.setCurrentRow((self.tab_list.currentRow() + direction) % count)
