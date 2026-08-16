"""
options_dialog.py
------------------
The Options/Settings window parked in NOTES.md ("Options menu + externalized/
translatable strings"). This is the UI SHELL ONLY -- every control shows a
sensible default and looks/behaves correctly, but nothing here reads from or
writes to a real settings store yet.

Built on VerticalTabDialog (dialog_common.py) -- see that module's docstring
for the shared tab-list/stack/keyboard-shortcut plumbing. This file only
owns what's actually Options-specific: which tabs/pages exist, and what's
on each one.

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
import scaling
from scaling import scale_manager, sp

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

def _swatch_style(color):
    """Function taking the swatch's own color -- see main.py's
    build_stylesheet comment for why pixel metrics in QSS need to be
    evaluated fresh against the current ui_scale rather than frozen."""
    return f"""
QRadioButton {{
    background-color: {color};
    border: {sp(2)}px solid transparent;
    border-radius: {sp(5)}px;
}}
QRadioButton::indicator {{ width: 0px; height: 0px; }}
QRadioButton:checked {{ border: {sp(2)}px solid #e3e3e3; }}
QRadioButton:focus {{ border: {sp(2)}px solid #ffffff; }}
"""

class OptionsDialog(VerticalTabDialog):
    def __init__(self, parent=None):
        super().__init__("Options", OPTION_TABS, parent)
        # Base size scales with ui_scale (sp()) -- still not truly
        # resizable by the user (frameless windows lose native edge-drag
        # resize; see NOTES.md's DPI/scaling entry), but at least a
        # deliberate Ctrl+wheel/Options-slider zoom now grows the window
        # to match instead of leaving it locked at one physical size
        # while everything drawn inside it gets larger/smaller.
        self.resize(sp(760), sp(500))
        scale_manager.scale_changed.connect(self._apply_dialog_scale)

    def _apply_dialog_scale(self):
        self.resize(sp(760), sp(500))

    def page_factories(self):
        return [
            self._build_language_page,
            self._build_themes_page,
            self._build_online_page,
            self._build_ui_page,
            self._build_input_page,
            self._build_advanced_page,
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
        # APPLY_BUTTON_STYLE is now a FUNCTION (see dialog_common.py --
        # it has to be, for live rescaling), so this can no longer treat
        # its return value as a cacheable string to string-replace once;
        # call it fresh, and do the same two substitutions on the result.
        apply_button.setStyleSheet(
            APPLY_BUTTON_STYLE().replace("#3d6a8f", "#2b2d31").replace("font-weight: 600;", "")
        )
        apply_button.clicked.connect(self._on_apply)

        ok_button = QPushButton("OK")
        ok_button.setDefault(True)  # Enter/Return anywhere in the dialog activates this
        ok_button.setStyleSheet(APPLY_BUTTON_STYLE())
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

    # --- Interface/text scale sliders (Interface page) --------------------
    def _on_ui_scale_slider_changed(self, value):
        # The percent LABEL updates immediately, directly, on every single
        # slider tick -- cheap (just text), so it stays perfectly live
        # while dragging. The actual expensive app-wide rescale is
        # deferred via queue_ui_scale (scaling.py) instead of calling
        # set_ui_scale() here directly -- QSlider fires valueChanged
        # continuously during a drag, and applying the full rescale pass
        # on every one of those ticks is what used to make dragging this
        # slider feel like it froze the app for several seconds. See
        # scaling.py's own docstring ("RAPID INPUT IS COALESCED...").
        self._ui_scale_value_label.setText(f"{value}%")
        scale_manager.queue_ui_scale(value / 100.0)

    def _on_text_scale_slider_changed(self, value):
        self._text_scale_value_label.setText(f"{value}%")
        scale_manager.queue_text_scale(value / 100.0)

    def _sync_scale_sliders(self):
        """
        Re-reads scale_manager's current values into both sliders/labels
        -- called whenever EITHER scale changes, from ANY source
        (Ctrl+wheel being the main one this page didn't itself cause).
        blockSignals is required, not just tidy: setValue() fires
        valueChanged, which is connected to the _on_..._changed methods
        above that call BACK into scale_manager.set_*_scale -- without
        blocking, an external Ctrl+wheel change would recurse through
        this sync a second time (harmlessly idempotent, but wasteful --
        same reasoning CardDatabaseView._sync_toggle_buttons already
        documents for its own blockSignals use).
        """
        if not hasattr(self, "_ui_scale_slider"):
            return  # this page hasn't been built yet -- nothing to sync
        for slider, label, value in (
            (self._ui_scale_slider, self._ui_scale_value_label, scale_manager.ui_scale),
            (self._text_scale_slider, self._text_scale_value_label, scale_manager.text_scale),
        ):
            percent = round(value * 100)
            slider.blockSignals(True)
            slider.setValue(percent)
            slider.blockSignals(False)
            label.setText(f"{percent}%")

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
            swatch.setFixedSize(sp(28), sp(24))
            swatch.setStyleSheet(_swatch_style(color))
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
            "Interface density and behavior. Interface scale and text "
            "scale are independent (see below) and take effect "
            "immediately -- Ctrl+scroll-wheel anywhere in the app moves "
            "both together as one combined zoom; the two sliders here "
            "split them apart. Neither is saved between sessions yet "
            "(see NOTES.md's 'Scaling infrastructure' entry)."
        )

        form = QFormLayout()
        form.setSpacing(10)

        # --- Interface scale: drives scale_manager.ui_scale (icon sizes,
        # fixed widget widths, padding/margins baked into QSS -- see
        # scaling.py). REAL and LIVE, not a mock control like the rest of
        # this page's still-cosmetic settings -- moving this slider
        # visibly resizes the app immediately, the same as Ctrl+wheel.
        self._ui_scale_slider = QSlider(Qt.Horizontal)
        self._ui_scale_slider.setRange(int(scaling.MIN_SCALE * 100), int(scaling.MAX_SCALE * 100))
        self._ui_scale_slider.setValue(round(scale_manager.ui_scale * 100))
        self._ui_scale_slider.setTickPosition(QSlider.TicksBelow)
        self._ui_scale_slider.setTickInterval(10)
        # Qt's own QSlider default singleStep is 1 -- i.e. arrow-keying a
        # focused slider (or clicking its groove) would move it a bare 1%
        # at a time, far finer than this setting is ever usefully tuned
        # by hand, and inconsistent with Ctrl+wheel's own 10% notch
        # (scaling.WHEEL_STEP). Matching both to 10% here is what makes
        # every way of adjusting this setting move in the same-sized,
        # predictable jumps.
        self._ui_scale_slider.setSingleStep(10)
        self._ui_scale_slider.setPageStep(10)
        self._ui_scale_value_label = QLabel(f"{round(scale_manager.ui_scale * 100)}%")
        self._ui_scale_slider.valueChanged.connect(self._on_ui_scale_slider_changed)
        ui_scale_row = QHBoxLayout()
        ui_scale_row.addWidget(self._ui_scale_slider, stretch=1)
        ui_scale_row.addWidget(self._ui_scale_value_label)
        form.addRow("Interface scale:", ui_scale_row)

        # --- Text scale: drives scale_manager.text_scale (the app's
        # default font point size -- see scaling.py). Independent of the
        # slider above by design (goal #4 -- "maximum customizability").
        self._text_scale_slider = QSlider(Qt.Horizontal)
        self._text_scale_slider.setRange(int(scaling.MIN_SCALE * 100), int(scaling.MAX_SCALE * 100))
        self._text_scale_slider.setValue(round(scale_manager.text_scale * 100))
        self._text_scale_slider.setTickPosition(QSlider.TicksBelow)
        self._text_scale_slider.setTickInterval(10)
        # Same reasoning as the Interface-scale slider above.
        self._text_scale_slider.setSingleStep(10)
        self._text_scale_slider.setPageStep(10)
        self._text_scale_value_label = QLabel(f"{round(scale_manager.text_scale * 100)}%")
        self._text_scale_slider.valueChanged.connect(self._on_text_scale_slider_changed)
        text_scale_row = QHBoxLayout()
        text_scale_row.addWidget(self._text_scale_slider, stretch=1)
        text_scale_row.addWidget(self._text_scale_value_label)
        form.addRow("Text scale:", text_scale_row)

        reset_scale_button = QPushButton("Reset to 100% / 100%")
        reset_scale_button.clicked.connect(scale_manager.reset)
        form.addRow("", reset_scale_button)

        # Keeps both sliders honest if the scale changes from OUTSIDE
        # this page -- Ctrl+wheel anywhere in the app, or (once this page
        # exists) the other slider's own combined-zoom side effects don't
        # apply here since the two axes are independent, but Ctrl+wheel
        # moves both at once and this page needs to reflect that too.
        scale_manager.scale_changed.connect(self._sync_scale_sliders)

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
        reset_button.setStyleSheet(DANGER_BUTTON_STYLE())
        layout.addWidget(reset_button)

        return page
