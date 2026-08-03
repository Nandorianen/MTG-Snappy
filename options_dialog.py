"""
options_dialog.py
------------------
The Options/Settings window parked in NOTES.md ("Options menu + externalized/
translatable strings"). This is the UI SHELL ONLY -- every control shows a
sensible default and looks/behaves correctly, but nothing here reads from or
writes to a real settings store yet.

Built on VerticalTabDialog (dialog_common.py) -- see that module's docstring
for the shared tab-list/stack/keyboard-shortcut plumbing, which used to live
directly in this file until DataManagementDialog needed the identical
chrome. This file now only owns what's actually Options-specific: which
tabs/pages exist, and what's on each one.

WHY THE ACCENT-COLOR SWATCHES (Themes page) ARE QRadioButton, NOT
QToolButton: an exclusive group of QRadioButtons sharing one parent layout
gets arrow-key cycling between them as a NATIVE Qt behavior (the same real
accessibility behavior any radio-button group gets) -- a row of checkable
QToolButtons would not, and reimplementing that navigation by hand here
would be exactly the kind of custom-key-handling crutch this app tries to
avoid when Qt already has an answer. The indicator dot is hidden via QSS
and the button itself is styled as a flat color square instead -- the
CLICK TARGET and KEYBOARD GROUP are still real QRadioButtons, only the
paint is different.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QComboBox, QCheckBox, QRadioButton, QButtonGroup, QLineEdit, QSlider,
    QSpinBox, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView,
)
from PySide6.QtCore import Qt, QTimer

from dialog_common import VerticalTabDialog, APPLY_BUTTON_STYLE, DANGER_BUTTON_STYLE, section_label
from tree_pane import ICON_PALETTE  # shared color palette -- see Themes page

# --- Tab definitions ---------------------------------------------------
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
# Japanese-printed card is still browsable with an English UI).
UI_LANGUAGES = ["English", "Japanese", "German", "French", "Spanish", "Portuguese"]
DATE_FORMATS = ["YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY"]
DATA_SOURCES = ["Local database only", "Scryfall API (full)", "Scryfall API (images only)"]
ROW_DENSITIES = ["Compact", "Comfortable", "Spacious"]
MODIFIER_KEYS = ["Ctrl", "Alt", "Shift"]

# Same accent blue used everywhere else in the app -- offered as the
# default-selected swatch below so "current theme" reads as genuinely
# current rather than an arbitrary first item.
CURRENT_ACCENT = "#4f8fc0"

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


class OptionsDialog(VerticalTabDialog):
    def __init__(self, parent=None):
        super().__init__("Options", OPTION_TABS, parent)
        # Fixed size, same known limitation as CardDetailDialog (frameless
        # windows lose native edge-drag resize -- see NOTES.md's DPI/
        # scaling entry, which already flags this dialog as one of the
        # places that'll need real resize/reflow support before that
        # work is done).
        self.resize(760, 500)

    def build_pages(self):
        return [
            self._build_language_page(),
            self._build_themes_page(),
            self._build_online_page(),
            self._build_ui_page(),
            self._build_input_page(),
            self._build_advanced_page(),
        ]

    def build_footer(self):
        return self._build_button_row()

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
        wiring is still pending.
        """
        self.apply_feedback_label.setText("Applied ✓")
        QTimer.singleShot(1800, lambda: self.apply_feedback_label.setText(""))

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
        layout.addWidget(section_label(
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

        layout.addWidget(section_label("Preset"))
        preset_row = QHBoxLayout()
        preset_group = QButtonGroup(self)
        for label, checked in (("Dark", True), ("Light", False), ("Follow System", False)):
            radio = QRadioButton(label)
            radio.setChecked(checked)
            preset_group.addButton(radio)
            preset_row.addWidget(radio)
        preset_row.addStretch()
        layout.addLayout(preset_row)

        layout.addWidget(section_label("Accent color"))
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
