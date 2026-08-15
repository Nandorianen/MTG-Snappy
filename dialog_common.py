"""
dialog_common.py
-----------------
Shared chrome for every "vertical tab list + stacked pages" modal window in
this app (OptionsDialog, DataManagementDialog, and any future one).

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
from scaling import scale_manager, sp


def _tab_list_style():
    """Function, not a static string -- see main.py's build_stylesheet
    comment for why every QSS string with a pixel metric in it has to be
    rebuilt fresh on each scale change rather than computed once."""
    return f"""
QListWidget {{
    background-color: transparent;
    border: none;
    outline: 0;
}}
QListWidget::item {{
    padding: {sp(10)}px {sp(14)}px;
    border-radius: {sp(4)}px;
    margin: {sp(2)}px {sp(6)}px;
}}
QListWidget::item:selected {{
    background-color: #3d6a8f;
    color: #ffffff;
}}
QListWidget::item:hover:!selected {{
    background-color: #2b2d31;
}}
"""


# Same accent-fill "this is the primary action" button reused by
# CardDatabaseView's Inventory/Wishlist toggles, CardDetailDialog's Apply
# button, and every settings-style dialog since -- one visual language for
# "the button that actually does the thing," app-wide. Functions, not
# static strings, for the same live-rescaling reason as _tab_list_style
# above -- every module that imports these now calls them (with `()`)
# rather than referencing a bare string constant. A module wanting to
# rebuild its own inline style on scale_changed should call the function
# again rather than caching its return value.
def APPLY_BUTTON_STYLE():
    return f"""
QPushButton {{
    padding: {sp(5)}px {sp(16)}px;
    border: 1px solid #4f8fc0;
    border-radius: {sp(4)}px;
    background-color: #3d6a8f;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: #4f8fc0;
}}
"""


def DANGER_BUTTON_STYLE():
    return f"""
QPushButton {{
    padding: {sp(5)}px {sp(14)}px;
    border: 1px solid #a83a3a;
    border-radius: {sp(4)}px;
    background-color: transparent;
    color: #d3898f;
}}
QPushButton:hover {{
    background-color: #a83a3a;
    color: white;
}}
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
    so every settings-style page reads as the same visual family.

    No hardcoded px font-size in the QSS (there used to be one, fixed at
    11px) -- same reasoning as main.py's old QWidget rule: a literal
    font-size would override the app's scaled default font and pin this
    caption at one size regardless of text_scale. Instead the point size
    is set in CODE, relative to whatever the current default font
    reports, so "a bit smaller than body text" stays true at any scale.
    Not re-applied on scale_changed -- unlike a fixed style STRING, this
    reads the live font at CREATION time, and every page that calls this
    is itself rebuilt fresh on tab-switch/dialog-reopen rather than kept
    around indefinitely (see VerticalTabDialog's lazy per-tab
    construction), so a stale point size here is a non-issue in
    practice.
    """
    label = QLabel(text)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 0.85)
    font.setBold(True)
    label.setFont(font)
    label.setStyleSheet("color: #a8adb5;")
    return label


class VerticalTabDialog(FramelessDialog):
    """
    Base for a modal window shaped like: a vertical list of tabs on the
    left, a stack of pages on the right, an optional footer row along the
    bottom. Subclasses provide the tabs and pages; this class builds and
    wires the tab list and stack, and handles all the keyboard plumbing.

    Subclasses MUST implement `page_factories()` (returns a list of
    zero-arg callables, same order as the `tab_specs` passed to __init__ --
    each one builds and returns that tab's page QWidget, called only once,
    the first time that tab is actually selected) and MAY override
    `build_footer()` (returns a QWidget for the bottom row, or None for no
    footer -- the default).

    PAGES ARE BUILT LAZILY, NOT ALL AT ONCE: only the currently-viewed
    tab's widgets actually get constructed; every other tab starts as an
    empty placeholder until the user first clicks over to it. Building
    every page eagerly would pay the FULL construction cost of every
    single tab before the window could even appear, most of which might
    never get looked at in a given session (Options alone has six) --
    real, avoidable work standing between a click and a window showing
    up, which conflicts directly with this app's snappiness priority. See
    `_show_tab()`.

    KEYBOARD SUPPORT (shared by every dialog built on this base):
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
        self.tab_list.setFixedWidth(sp(180))
        self.tab_list.setStyleSheet(_tab_list_style())
        self.tab_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tab_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for _key, label in tab_specs:
            self.tab_list.addItem(QListWidgetItem(label))

        # LAZY PAGE CONSTRUCTION: only the page for whichever tab is
        # actually being looked at gets built. Building every page eagerly
        # would pay the FULL construction cost of every tab before the
        # window could even appear -- for a 6-tab dialog like Options,
        # most of those tabs might never get visited in a given session.
        # Each tab starts as an empty placeholder widget in the stack;
        # _show_tab() swaps in the REAL page (built by calling the
        # subclass-provided factory function, exactly once per tab) the
        # first time that tab is actually selected. Subsequent visits to
        # an already-built tab are free -- _built_pages just tracks which
        # indices have already been swapped in, so a tab is never rebuilt
        # from scratch on every revisit.
        self._page_factories = self.page_factories()
        self._built_pages = set()
        self.stack = QStackedWidget()
        for _ in self._page_factories:
            self.stack.addWidget(QWidget())  # placeholder, replaced on first visit
        self.tab_list.currentRowChanged.connect(self._show_tab)

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
        self.tab_list.setCurrentRow(0)  # fires currentRowChanged -> builds tab 0's real page
        self.tab_list.setFocus()

        # Live rescaling: the tab list's fixed width + its own QSS
        # (padding/margins/border-radius) both need reapplying on a
        # ui_scale change. Page CONTENT built by subclasses (form rows,
        # buttons, etc.) is covered separately per-widget where it
        # matters -- this class only owns the shared chrome.
        scale_manager.scale_changed.connect(self._apply_scale)

    def _apply_scale(self):
        self.tab_list.setFixedWidth(sp(180))
        self.tab_list.setStyleSheet(_tab_list_style())

    # --- Subclass hooks ------------------------------------------------
    def page_factories(self):
        """
        Returns a list of zero-argument callables, same order as the
        tab_specs passed to __init__ -- each one builds and returns that
        tab's page QWidget WHEN CALLED. Callables, not already-built
        widgets: that's what makes deferring the actual construction
        possible. Subclasses typically just return a list of their own
        page-builder method references, e.g. `[self._build_language_page,
        self._build_themes_page, ...]` -- note the lack of `()`, since
        these must stay uncalled until _show_tab() decides a tab is
        actually being visited.
        """
        raise NotImplementedError

    def build_footer(self):
        return None

    def _show_tab(self, index):
        if index not in self._built_pages:
            page = self._page_factories[index]()
            placeholder = self.stack.widget(index)
            self.stack.removeWidget(placeholder)
            placeholder.deleteLater()
            self.stack.insertWidget(index, page)
            self._built_pages.add(index)
        self.stack.setCurrentIndex(index)

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
