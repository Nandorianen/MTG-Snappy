"""
options_dialog.py
------------------
The Options/Settings window parked in NOTES.md ("Options menu + externalized/
translatable strings"). This is the UI SHELL ONLY -- every control shows a
sensible default and looks/behaves correctly, but nothing here reads from or
writes to a real settings store yet (there isn't one -- see NOTES.md's
Undo/redo + save model entry for the related "explicit save vs. autosave"
question that a real settings persistence layer will also need to answer).

LAYOUT: a vertical tab strip on the left (Language / Themes / Online /
Interface / Input / Advanced), a QStackedWidget of pages on the right, Apply/
Cancel/OK along the bottom. Built on the shared FramelessDialog base (same
frameless-window-plus-custom-title-bar treatment as CardDetailDialog and
TagApplyDialog), opened modally via .exec() -- same pattern TagApplyDialog
already uses, which is also what makes FramelessDialog's "click outside
closes" eventFilter harmless here: a modal dialog blocks input to everything
else anyway, so that check simply never fires.

WHY THE TAB STRIP IS A QListWidget, NOT QPushButton+QButtonGroup (unlike
side_nav.py's SideNav): SideNav is a small, always-visible, few-item strip
where direct Ctrl+1/2/3 jumps already cover fast access, so plain checkable
buttons are enough. This dialog has more tabs and is a modal settings panel
-- the idiomatic pattern here (matching how virtually every OS settings app
behaves) is a navigable LIST, and QListWidget already implements everything
that needs: Up/Down moves the highlight, Home/End jumps to the first/last
tab, and typing a letter jumps straight to the next tab starting with it
(QAbstractItemView's built-in keyboardSearch) -- all free, none of it
reimplemented here. This is the same "use the native widget for what Qt
already does correctly" reasoning tree_pane.py's docstring makes for
QTreeWidget over a from-scratch tree.

WHY THE ACCENT-COLOR SWATCHES ARE QRadioButton, NOT QToolButton: an
exclusive group of QRadioButtons sharing one parent layout gets arrow-key
cycling between them as a NATIVE Qt behavior (the same real accessibility
behavior any radio-button group gets) -- a row of checkable QToolButtons
would not, and reimplementing that navigation by hand here would be exactly
the kind of custom-key-handling crutch this app tries to avoid when Qt
already has an answer. The indicator dot is hidden via QSS and the button
itself is styled as a flat color square instead -- the CLICK TARGET and
KEYBOARD GROUP are still real QRadioButtons, only the paint is different.

KEYBOARD SUPPORT SUMMARY (the point of this whole file):
  - Up/Down/Home/End/type-ahead in the tab list -- free, from QListWidget.
  - Tab/Shift+Tab moves focus through a page's controls in the order they
    were added to that page's layout -- free, from Qt's normal focus chain.
  - Ctrl+Tab / Ctrl+Shift+Tab (also Ctrl+PageDown / Ctrl+PageUp) switch tabs
    from ANYWHERE in the dialog, not just while the tab list has focus --
    bound at the dialog level via WidgetWithChildrenShortcut, the same
    pattern tree_pane.py already uses for Ctrl+N/Ctrl+X/etc, so a shortcut
    fires regardless of which specific child widget currently holds focus.
  - Escape closes (Cancel) and Enter/Return activates the default button
    (OK) -- both are QDialog's own native behavior, not reimplemented here.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QFrame,
    QListWidget, QListWidgetItem, QStackedWidget, QAbstractItemView,
    QComboBox, QCheckBox, QRadioButton, QButtonGroup, QLineEdit, QSlider,
    QSpinBox, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut

from frameless_dialog import FramelessDialog
from tree_pane import ICON_PALETTE  # shared color palette -- see Themes page

# --- Tab definitions ---------------------------------------------------
# (key, label) -- mirrors side_nav.TABS's shape; key isn't read anywhere
# yet (no settings store to key into) but kept alongside the label now so
# wiring real persistence later doesn't mean threading a second parallel
# list through this file's page-builder methods.
OPTION_TABS = [
    ("language", "Language"),
    ("themes", "Themes"),
    ("online", "Online"),
    ("ui", "Interface"),
    ("input", "Input"),
    ("advanced", "Advanced"),
]

# UI display language -- deliberately its OWN list, not mock_data.LANGUAGES
# (which models a CARD PRINT's language, a different concept entirely: a
# Japanese-printed card is still browsable with an English UI). Keeping
# these decoupled means a real per-language string file system (see
# NOTES.md) never has to reconcile two unrelated "language" lists that
# happen to look similar.
UI_LANGUAGES = ["English", "Japanese", "German", "French", "Spanish", "Portuguese"]
DATE_FORMATS = ["YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY"]
DATA_SOURCES = ["Local database only", "Scryfall API (full)", "Scryfall API (images only)"]
ROW_DENSITIES = ["Compact", "Comfortable", "Spacious"]
MODIFIER_KEYS = ["Ctrl", "Alt", "Shift"]

# Same accent blue used everywhere else in the app (CardDatabaseView's
# toggle buttons, table row selection, QMenu::item:selected) -- offered as
# the default-selected swatch below so "current theme" reads as genuinely
# current rather than an arbitrary first item.
CURRENT_ACCENT = "#4f8fc0"

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

SWATCH_STYLE = """
QRadioButton {{
    background-color: {color};
    border: 2px solid transparent;
    border-radius: 5px;
}}
QRadioButton::indicator {{ width: 0px; height: 0px; }}
QRadioButton:checked {{ border: 2px solid #e3e3e3; }}
QRadioButton:focus {{ border: 2px solid #ffffff; }}
"""


def _vline():
    """Thin vertical rule, separating the tab list from the page area --
    same helper card_detail_popup.py defines for its own pane separators.
    Kept as a local duplicate rather than imported from that module: this
    dialog has no other reason to depend on card_detail_popup, and a
    four-line function isn't worth coupling two otherwise-unrelated
    dialogs together over."""
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setStyleSheet("color: #3a3c41;")
    return line


def _section_label(text):
    """Small caps-style gray section caption, matching StatField's caption
    styling in card_detail_popup.py -- reused here (as a style choice, not
    a code import) so a settings page's sub-headings read as the same kind
    of label the rest of the app already uses for one."""
    label = QLabel(text)
    label.setStyleSheet("color: #a8adb5; font-size: 11px; font-weight: 600;")
    return label


class OptionsDialog(FramelessDialog):
    def __init__(self, parent=None):
        super().__init__("Options", parent)
        # Fixed size, same known limitation as CardDetailDialog (frameless
        # windows lose native edge-drag resize -- see NOTES.md's DPI/
        # scaling entry, which already flags this exact dialog as one of
        # the places that'll need real resize/reflow support before that
        # work is done). Not a regression here -- it's the same tradeoff,
        # made for the same reason, in a second place.
        self.resize(760, 500)

        body = QHBoxLayout()
        body.setSpacing(0)

        self.tab_list = QListWidget()
        self.tab_list.setFixedWidth(180)
        self.tab_list.setStyleSheet(TAB_LIST_STYLE)
        self.tab_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tab_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for _key, label in OPTION_TABS:
            self.tab_list.addItem(QListWidgetItem(label))

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_language_page())
        self.stack.addWidget(self._build_themes_page())
        self.stack.addWidget(self._build_online_page())
        self.stack.addWidget(self._build_ui_page())
        self.stack.addWidget(self._build_input_page())
        self.stack.addWidget(self._build_advanced_page())

        # Selecting a row and showing its page are the SAME action here --
        # unlike CardDatabaseView's Inventory/Wishlist buttons (which sync
        # two independent UIs over one shared model), there's only one
        # source of truth for "which tab is active," so a direct signal
        # connection is enough; no round-trip sync is needed.
        self.tab_list.currentRowChanged.connect(self.stack.setCurrentIndex)

        page_container = QWidget()
        page_layout = QVBoxLayout(page_container)
        page_layout.setContentsMargins(18, 10, 10, 10)
        page_layout.addWidget(self.stack)

        body.addWidget(self.tab_list)
        body.addWidget(_vline())
        body.addWidget(page_container, stretch=1)
        self.content_layout.addLayout(body)

        self.content_layout.addWidget(self._build_button_row())

        self._install_shortcuts()

        self.tab_list.setCurrentRow(0)
        self.tab_list.setFocus()

    # --- Bottom button row --------------------------------------------------
    def _build_button_row(self):
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 8, 0, 0)

        self.apply_feedback_label = QLabel("")
        self.apply_feedback_label.setStyleSheet("color: #4caf50;")
        row.addWidget(self.apply_feedback_label)
        row.addStretch()

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)

        apply_button = QPushButton("Apply")
        apply_button.setStyleSheet(APPLY_BUTTON_STYLE.replace("#3d6a8f", "#2b2d31").replace("font-weight: 600;", ""))
        apply_button.clicked.connect(self._on_apply)

        ok_button = QPushButton("OK")
        ok_button.setDefault(True)  # Enter/Return anywhere in the dialog activates this
        ok_button.setStyleSheet(APPLY_BUTTON_STYLE)
        ok_button.clicked.connect(self.accept)

        row.addWidget(cancel_button)
        row.addWidget(apply_button)
        row.addWidget(ok_button)
        return row_widget

    def _on_apply(self):
        """
        No real settings store exists yet -- this just gives the same
        transient "Applied" confirmation CardDetailDialog's Apply button
        already uses, so the button doesn't feel inert while the real
        wiring is still pending. Deliberately doesn't close the dialog,
        same reasoning as CardDetailDialog's Apply: "commit, keep
        adjusting" rather than a one-shot action.
        """
        self.apply_feedback_label.setText("Applied ✓")
        QTimer.singleShot(1800, lambda: self.apply_feedback_label.setText(""))

    # --- Keyboard: tab-switching from anywhere in the dialog ---------------
    def _install_shortcuts(self):
        def bind(sequence, slot):
            shortcut = QShortcut(QKeySequence(sequence), self)
            # Same reasoning as tree_pane.py's own bind() helper: scoped to
            # this dialog and its children so the shortcut fires no matter
            # which control inside a page currently has focus, without
            # leaking into a global application-wide shortcut.
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
            return shortcut

        self._sc_next_tab = bind("Ctrl+Tab", lambda: self._step_tab(1))
        self._sc_prev_tab = bind("Ctrl+Shift+Tab", lambda: self._step_tab(-1))
        # Same two actions, alternate keys -- some platforms/muscle memory
        # reach for PageDown/PageUp over Tab for this.
        self._sc_next_tab_pg = bind("Ctrl+PgDown", lambda: self._step_tab(1))
        self._sc_prev_tab_pg = bind("Ctrl+PgUp", lambda: self._step_tab(-1))

    def _step_tab(self, direction):
        count = self.tab_list.count()
        self.tab_list.setCurrentRow((self.tab_list.currentRow() + direction) % count)

    # --- Page builders -------------------------------------------------------
    def _new_page(self, description):
        """Shared page skeleton: a short description line, then callers add
        a QFormLayout (or section) beneath it, then a trailing stretch."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(14)
        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a8adb5;")
        layout.addWidget(desc)
        return page, layout

    def _build_language_page(self):
        page, layout = self._new_page(
            "Controls the app's own interface language -- independent of a "
            "card's printed language, which is set per-copy in the card "
            "detail popup."
        )

        form = QFormLayout()
        form.setSpacing(10)

        language_combo = QComboBox()
        language_combo.addItems(UI_LANGUAGES)
        form.addRow("Display language:", language_combo)

        follow_system = QCheckBox("Follow system locale automatically")
        form.addRow("", follow_system)

        date_combo = QComboBox()
        date_combo.addItems(DATE_FORMATS)
        form.addRow("Date format:", date_combo)

        layout.addLayout(form)
        layout.addWidget(_section_label(
            "Strings load from per-language files, each falling back to "
            "English for any key it doesn't override (see NOTES.md)."
        ))
        layout.addStretch()
        return page

    def _build_themes_page(self):
        page, layout = self._new_page(
            "Dark/light presets and accent color -- see NOTES.md's theming "
            "entry for why this replaces hardcoded QSS hex colors with "
            "real QPalette-driven values once it's wired up."
        )

        layout.addWidget(_section_label("Preset"))
        preset_row = QHBoxLayout()
        preset_group = QButtonGroup(self)
        for label, checked in (("Dark", True), ("Light", False), ("Follow System", False)):
            radio = QRadioButton(label)
            radio.setChecked(checked)
            preset_group.addButton(radio)
            preset_row.addWidget(radio)
        preset_row.addStretch()
        layout.addLayout(preset_row)

        layout.addWidget(_section_label("Accent color"))
        swatch_row = QHBoxLayout()
        swatch_group = QButtonGroup(self)
        for color in ICON_PALETTE + [CURRENT_ACCENT]:
            swatch = QRadioButton()
            swatch.setFixedSize(28, 24)
            swatch.setStyleSheet(SWATCH_STYLE.format(color=color))
            swatch.setChecked(color == CURRENT_ACCENT)
            swatch_group.addButton(swatch)
            swatch_row.addWidget(swatch)
        swatch_row.addStretch()
        layout.addLayout(swatch_row)

        form = QFormLayout()
        form.setSpacing(10)
        custom_qss = QCheckBox("Use a custom stylesheet file")
        form.addRow("", custom_qss)
        qss_path_row = QHBoxLayout()
        qss_path_row.addWidget(QLineEdit(placeholderText="Path to a .qss file..."))
        browse_button = QPushButton("Browse...")
        qss_path_row.addWidget(browse_button)
        form.addRow("Stylesheet:", qss_path_row)
        layout.addLayout(form)

        layout.addStretch()
        return page

    def _build_online_page(self):
        page, layout = self._new_page(
            "Offline by default -- everything here is optional. See "
            "PROJECT_CONTEXT.md's goal #1: local JSON/SQLite is the "
            "primary path, live API fetching is an explicit opt-in."
        )

        form = QFormLayout()
        form.setSpacing(10)

        enable_online = QCheckBox("Enable online mode")
        form.addRow("", enable_online)

        source_combo = QComboBox()
        source_combo.addItems(DATA_SOURCES)
        form.addRow("Data source:", source_combo)

        api_key_field = QLineEdit()
        api_key_field.setEchoMode(QLineEdit.Password)
        api_key_field.setPlaceholderText("Only needed for live API access")
        form.addRow("API key:", api_key_field)

        cache_spin = QSpinBox()
        cache_spin.setRange(1, 90)
        cache_spin.setValue(14)
        cache_spin.setSuffix(" days")
        form.addRow("Image cache duration:", cache_spin)

        manual_only = QCheckBox("Only fetch on manual refresh, never automatically")
        form.addRow("", manual_only)

        layout.addLayout(form)
        layout.addStretch()
        return page

    def _build_ui_page(self):
        page, layout = self._new_page(
            "Interface density and behavior. UI scale is independent of "
            "the OS's own DPI/text-scaling setting -- see NOTES.md's "
            "'variable text scaling & DPI' entry for how the two relate."
        )

        form = QFormLayout()
        form.setSpacing(10)

        scale_slider = QSlider(Qt.Horizontal)
        scale_slider.setRange(80, 150)
        scale_slider.setValue(100)
        scale_slider.setTickPosition(QSlider.TicksBelow)
        scale_slider.setTickInterval(10)
        form.addRow("UI scale (%):", scale_slider)

        density_combo = QComboBox()
        density_combo.addItems(ROW_DENSITIES)
        density_combo.setCurrentText("Comfortable")
        form.addRow("Row density:", density_combo)

        hover_preview = QCheckBox("Show card preview on hover")
        hover_preview.setChecked(True)
        form.addRow("", hover_preview)

        hover_delay = QSpinBox()
        hover_delay.setRange(0, 2000)
        hover_delay.setSingleStep(50)
        hover_delay.setValue(350)
        hover_delay.setSuffix(" ms")
        form.addRow("Hover preview delay:", hover_delay)

        confirm_delete = QCheckBox("Confirm before deleting tags/decks")
        confirm_delete.setChecked(True)
        form.addRow("", confirm_delete)

        layout.addLayout(form)
        layout.addStretch()
        return page

    def _build_input_page(self):
        page, layout = self._new_page(
            "Keyboard shortcuts currently in use (read-only preview -- "
            "rebinding isn't wired up yet)."
        )

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        bindings = [
            ("Rename item", "F2"),
            ("Delete item(s)", "Delete"),
            ("Cut / Copy / Paste", "Ctrl+X / Ctrl+C / Ctrl+V"),
            ("New item / New folder", "Ctrl+N / Ctrl+Shift+N"),
            ("Copy cell selection", "Ctrl+C"),
            ("Edit Qty cell", "F2"),
            ("Extend selection to edge", "Ctrl+Shift+Arrow"),
        ]
        table.setRowCount(len(bindings))
        for row, (action, keys) in enumerate(bindings):
            table.setItem(row, 0, QTableWidgetItem(action))
            table.setItem(row, 1, QTableWidgetItem(keys))
        layout.addWidget(table)

        form = QFormLayout()
        form.setSpacing(10)
        wheel_switch = QCheckBox("Mouse-wheel switches print/edition on a hovered card")
        wheel_switch.setChecked(True)
        form.addRow("", wheel_switch)
        modifier_combo = QComboBox()
        modifier_combo.addItems(MODIFIER_KEYS)
        form.addRow("Reticle-zoom modifier:", modifier_combo)
        layout.addLayout(form)

        return page

    def _build_advanced_page(self):
        page, layout = self._new_page(
            "Data location and backups. See NOTES.md's undo/redo + save "
            "model entry -- explicit-save vs. autosave is still an open "
            "question this page will eventually need to reflect."
        )

        form = QFormLayout()
        form.setSpacing(10)

        data_path_row = QHBoxLayout()
        data_path_row.addWidget(QLineEdit(placeholderText="~/MTGLocalDB/"))
        data_browse = QPushButton("Browse...")
        data_path_row.addWidget(data_browse)
        form.addRow("Local data folder:", data_path_row)

        backup_spin = QSpinBox()
        backup_spin.setRange(1, 120)
        backup_spin.setValue(15)
        backup_spin.setSuffix(" minutes")
        form.addRow("Auto-backup interval:", backup_spin)

        autosave_check = QCheckBox("Enable autosave (in addition to backups)")
        form.addRow("", autosave_check)

        layout.addLayout(form)
        layout.addStretch()

        reset_button = QPushButton("Reset All Settings to Defaults")
        reset_button.setStyleSheet(DANGER_BUTTON_STYLE)
        layout.addWidget(reset_button)

        return page
