"""
data_management_dialog.py
--------------------------
The window for goal #1/#3/#7's real data layer: pointing the app at local
JSON files, seeing their state, and (eventually) re-syncing them against
Scryfall's bulk-data API. Reachable via File > Data Management... or
Ctrl+M. Same UI-SHOWCASE status as options_dialog.py: every control looks
and behaves correctly, but no actual download/parse/persistence pipeline
exists yet -- see each page's own docstring-level notes below for exactly
which bits are real and which are mocked.

Built on VerticalTabDialog (dialog_common.py) -- same tab-list/stack/
Ctrl+Tab chrome OptionsDialog uses, extracted there specifically so this
dialog wouldn't need to reimplement it. See that module's docstring for
why these two dialogs share a base rather than one inheriting the other.

THREE TABS:
  1. Metadata     -- Scryfall's bulk-data JSON exports (Oracle Cards,
                      Unique Artwork, Default Cards, All Cards, Rulings,
                      plus the separate Tagger-project exports Art Tags
                      and Oracle Tags).
  2. Card Images  -- a target folder, per-size/crop checkboxes, a print
                      language, and a set-selection menu, plus a Download
                      action.
  3. Decks & Tags -- this app's OWN local save data (not from Scryfall at
                      all) -- structurally identical to the Metadata tab's
                      rows, per your request, just pointed at two different
                      files with a different action-button label (see
                      DataFileRow's docstring for why "Update" doesn't make
                      sense here and "Locate..." does).

WHAT'S ACTUALLY REAL vs. MOCKED:
  - Browse buttons (file AND folder) open genuine QFileDialogs, and if you
    pick a REAL file/folder, the filename/size/date fields update from a
    REAL os.stat()/os.walk() read. There's no reason to fake a harmless
    local filesystem read.
  - Everything else -- the placeholder filenames/sizes/dates shown before
    you browse, the Update/Locate/Download buttons' actions, the format
    checkboxes' effect -- is cosmetic. Clicking Update/Locate/Download just
    gives brief "working" feedback (matching CardDetailDialog's Apply
    button and OptionsDialog's Apply button), not a real operation.

WHY THE EDITION-PICKER MENU NEEDS NONE OF card_table.py's SPECIAL
KEYBOARD-HANDLING CODE: card_table.py's _MenuSearchBox exists because a
QLineEdit search box embedded in that menu competes for keyboard focus with
QMenu's own arrow-key navigation, which is what forced all that custom
eventFilter routing. The edition menu here has no such embedded widget --
it's a plain QMenu of checkable actions -- so Up/Down/Space/Enter already
work correctly with ZERO extra code. Worth calling out explicitly so this
isn't "fixed" later by copying machinery it was never going to need.
"""

import os
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QPushButton, QCheckBox, QComboBox, QToolButton, QMenu, QFileDialog,
)
from PySide6.QtCore import Qt, QTimer

from dialog_common import VerticalTabDialog, APPLY_BUTTON_STYLE, section_label
from mock_data import LANGUAGES

DATA_TABS = [
    ("metadata", "Metadata"),
    ("images", "Card Images"),
    ("userdata", "Decks & Tags"),
]

# --- Metadata tab: Scryfall's bulk-data exports, plus the two separate
# Tagger-project exports (Art Tags / Oracle Tags aren't part of Scryfall's
# core bulk-data API -- flagged in their own descriptions below). Every
# filename/size/date here is a plausible-looking PLACEHOLDER, overwritten
# with real values the moment someone actually Browses to a real file.
METADATA_SECTIONS = [
    dict(title="Oracle Cards", filename="oracle-cards-20260730.json", size_bytes=184_500_000, date="2026-07-30",
         description="One card object per Oracle ID -- each unique card name appears exactly once, regardless of "
                     "how many times it's been reprinted. The realistic source for the Type/Mana Cost/oracle text "
                     "the card detail popup already shows from mock_data.py."),
    dict(title="Unique Artwork", filename="unique-artwork-20260730.json", size_bytes=246_800_000, date="2026-07-30",
         description="One card object per unique illustration -- every printing that got its own distinct piece of "
                     "art appears once, regardless of how many sets reused the same rules text. Useful for a future "
                     "'browse by art' view; not needed for the current card table."),
    dict(title="Default Cards", filename="default-cards-20260730.json", size_bytes=612_100_000, date="2026-07-30",
         description="Every printing of every card, in English (or its only available language). The realistic "
                     "source for the real per-print Edition/Rarity/Price data the card detail popup's edition "
                     "switcher currently mocks via CARD_PRINTS."),
    dict(title="All Cards", filename="all-cards-20260730.json", size_bytes=1_380_000_000, date="2026-07-30",
         description="Every printing of every card, in every language it was ever printed in -- the largest file "
                     "by far. Only worth it if the Language dropdown here and in the card detail popup needs to "
                     "resolve real non-English prints, not just relabel a field."),
    dict(title="Rulings", filename="rulings-20260728.json", size_bytes=9_200_000, date="2026-07-28",
         description="Official rulings, keyed by Oracle ID -- the realistic source for the card detail popup's "
                     "Rulings pane, currently filled with hand-written mock rulings in mock_data.py."),
    dict(title="Art Tags", filename="art-tags-20260601.json", size_bytes=4_100_000, date="2026-06-01",
         description="Community-curated illustration tags (what's depicted in the art, independent of gameplay "
                     "function), exported from Scryfall's separate Tagger project -- not part of Scryfall's core "
                     "bulk-data API."),
    dict(title="Oracle Tags", filename="oracle-tags-20260601.json", size_bytes=3_600_000, date="2026-06-01",
         description="Community-curated functional/gameplay tags (e.g. 'removal', 'ramp'), also from Scryfall's "
                     "Tagger project. Related to, but distinct from, this app's OWN user-defined Tag Database -- "
                     "one is Scryfall's community data, the other is yours."),
]

# --- Decks & Tags tab: this app's OWN local save data. Same DataFileRow
# shape as Metadata, above, but nothing here comes from Scryfall.
USER_DATA_SECTIONS = [
    dict(title="User Decks", filename="decks.json", size_bytes=42_000, date="2026-08-01",
         description="Local save file for every folder/deck built in the Deck Viewer tab (tree_pane.py's TreePane "
                     "structure), plus each deck's actual card contents once that's built -- see NOTES.md's "
                     "'Deck contents' entry."),
    dict(title="User Tags", filename="tags.json", size_bytes=18_500, date="2026-08-01",
         description="Local save file for the Tag Database's tree (tag_tree.py) and every card-to-tag assignment "
                     "(tag_assignments.py's in-memory dict, once persisted here for real)."),
]

# Mirrors Scryfall's real per-print image_uris sizes/crops. Exact
# availability may need reconciling against real API responses once this
# is wired up -- descriptions here are illustrative, not a spec.
IMAGE_FORMATS = [
    ("png", "PNG", "Transparent, rounded-corner artwork -- best for overlays or custom card-image compositing.", False),
    ("large", "Large", "High-resolution scan, good for zoom/inspection (e.g. the detail popup's art viewer).", True),
    ("normal", "Normal", "Balanced resolution -- the default choice for most table/grid displays.", True),
    ("small", "Small", "Low-resolution thumbnail, useful for dense lists.", False),
    ("border_crop", "Border Crop", "Full card art with the outer white border trimmed off.", False),
    ("art_crop", "Art Crop", "Just the illustration, cropped to the art box only -- no frame or text.", False),
    ("thumb", "Thumbnail", "A very small preview, useful for compact hover popovers.", False),
]

# Placeholder set list -- deliberately reuses the same set codes already
# scattered through mock_data.py's MOCK_CARDS/CARD_PRINTS (LEA, FUT, DGM,
# ZEN, AVR, ISD, NPH, 2XM, DMR) rather than inventing a new arbitrary list,
# so the dummy data in this dialog and the dummy data already in the rest
# of the app stay internally consistent. Will be replaced by a real
# Scryfall sets list once this is wired up.
EDITION_OPTIONS = ["LEA", "FUT", "DGM", "ZEN", "AVR", "ISD", "NPH", "2XM", "DMR"]


def _format_size(num_bytes):
    """Human-readable byte count -- B/KB/MB/GB/TB, one decimal place past B."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def _folder_size(path):
    """
    Recursively sums real on-disk file sizes under `path`. Fine for a
    demo-sized folder; a genuinely large image cache (hundreds of
    thousands of files) would want this computed off the UI thread, or
    cached and only recomputed after a real download rather than on every
    Browse click -- worth revisiting once real downloads make this folder
    non-trivial in size.
    """
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


class _StayOpenMenu(QMenu):
    """Checking an item here doesn't close the menu -- same stay-open
    checklist idiom card_table.py's own _StayOpenMenu already uses for its
    filter menus. Duplicated here rather than imported: that class is
    private to card_table.py by name and by design, scoped to that
    module's own filter-menu context -- a six-line override is cheap
    enough to have twice rather than reach into another module's private
    implementation detail."""
    def mouseReleaseEvent(self, event):
        action = self.activeAction()
        if action is not None and action.isCheckable():
            action.trigger()
            return
        super().mouseReleaseEvent(event)


class DataFileRow(QWidget):
    """
    One "point at a local file" row: a header, then Browse/filename/size/
    date/action-button on one line (where the dialog is wide enough),
    then a wrapped description underneath. Shared by the Metadata tab (7
    Scryfall bulk-data files) and the Decks & Tags tab (2 local save
    files) -- structurally identical, per your request, with the action
    button's label as the one thing that differs between them: "Update"
    implies redownloading from Scryfall, which makes no sense for the
    user's own local save data, so that tab passes action_label="Locate..."
    instead.

    See the module docstring for why Browse is real (genuine QFileDialog +
    real os.stat()) while the action button is not (nothing to actually
    update/locate/sync against yet).
    """

    def __init__(self, title, filename, size_bytes, date_text, description,
                 action_label="Update", file_filter="All files (*)"):
        super().__init__()
        self._file_filter = file_filter
        self._title = title
        self.path = None  # set for real once Browse actually picks a file

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(4)

        header = QLabel(title)
        header.setStyleSheet(
            "color: #e3e3e3; font-size: 13px; font-weight: 700; "
            "padding-bottom: 2px; border-bottom: 1px solid #3a3c41;"
        )
        layout.addWidget(header)

        info_row = QHBoxLayout()
        info_row.setSpacing(10)

        browse_button = QPushButton("Browse\u2026")
        browse_button.clicked.connect(self._on_browse)
        info_row.addWidget(browse_button)

        self.filename_label = QLabel(filename)
        self.filename_label.setStyleSheet("font-weight: 600;")
        self.filename_label.setToolTip("Placeholder -- not yet linked to a real file. Click Browse.")
        info_row.addWidget(self.filename_label, stretch=1)

        self.size_label = QLabel(_format_size(size_bytes))
        self.size_label.setMinimumWidth(70)
        self.size_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info_row.addWidget(self.size_label)

        self.date_label = QLabel(date_text)
        self.date_label.setMinimumWidth(100)
        self.date_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info_row.addWidget(self.date_label)

        self.action_button = QPushButton(action_label)
        self.action_button.setStyleSheet(APPLY_BUTTON_STYLE)
        self.action_button.clicked.connect(self._on_action)
        info_row.addWidget(self.action_button)

        layout.addLayout(info_row)

        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #a8adb5;")
        layout.addWidget(desc_label)

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(self, f"Locate {self._title} file", "", self._file_filter)
        if not path:
            return
        self.path = path
        try:
            stat = os.stat(path)
        except OSError:
            return  # file vanished between the picker closing and this read -- leave the display as-is
        self.filename_label.setText(os.path.basename(path))
        self.filename_label.setToolTip(path)
        self.size_label.setText(_format_size(stat.st_size))
        self.date_label.setText(datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"))

    def _on_action(self):
        # Nothing real to do yet -- see module docstring. Brief "working"
        # feedback so the click doesn't feel inert, same choice
        # OptionsDialog's Apply button already makes.
        original = self.action_button.text()
        self.action_button.setEnabled(False)
        self.action_button.setText("Working\u2026")
        QTimer.singleShot(900, lambda: self._reset_action_button(original))

    def _reset_action_button(self, original_text):
        self.action_button.setText(original_text)
        self.action_button.setEnabled(True)


class DataManagementDialog(VerticalTabDialog):
    def __init__(self, parent=None):
        super().__init__("Data Management", DATA_TABS, parent)
        self.resize(880, 620)

    def build_pages(self):
        return [
            self._build_metadata_page(),
            self._build_images_page(),
            self._build_userdata_page(),
        ]

    def build_footer(self):
        # No Apply/Cancel/OK concept here -- every real action already
        # lives inline (each row's own Update/Locate button, the Download
        # button on the Images tab), so the dialog-level footer is just a
        # single way out.
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 8, 0, 0)
        row.addStretch()
        close_button = QPushButton("Close")
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        row.addWidget(close_button)
        return row_widget

    # --- Shared page shape: Metadata and Decks & Tags are the same layout
    # (a scrollable list of DataFileRows) over a different section list and
    # action-button label -- see DataFileRow's docstring for why the label
    # differs.
    def _build_file_section_page(self, sections, intro_text, action_label, file_filter):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        intro = QLabel(intro_text)
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #a8adb5;")
        outer.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # NoFrame -- the default sunken QScrollArea frame reads as a stray
        # light bezel against this app's flat dark theme; every other
        # bordered container in the app (QTableView, QTreeWidget, QMenu)
        # gets its border from main.py's own QSS instead, not Qt's default.
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 8, 12, 8)
        content_layout.setSpacing(4)
        for section in sections:
            row = DataFileRow(
                section["title"], section["filename"], section["size_bytes"],
                section["date"], section["description"],
                action_label=action_label, file_filter=file_filter,
            )
            content_layout.addWidget(row)
        content_layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)
        return page

    def _build_metadata_page(self):
        return self._build_file_section_page(
            METADATA_SECTIONS,
            "Scryfall's bulk-data exports -- each one a single JSON file covering every card at once, refreshed "
            "roughly daily on Scryfall's end. Bigger files (All Cards especially) trade completeness for real "
            "disk space and download time.",
            action_label="Update",
            file_filter="JSON files (*.json);;All files (*)",
        )

    def _build_userdata_page(self):
        return self._build_file_section_page(
            USER_DATA_SECTIONS,
            "Your own local save data -- decks and tags you've created. Unlike the Metadata tab, none of this "
            "comes from Scryfall, so there's nothing to \u2018redownload\u2019: Locate just re-links the app to a "
            "file if it's been moved.",
            action_label="Locate\u2026",
            file_filter="JSON files (*.json);;All files (*)",
        )

    # --- Card Images tab -----------------------------------------------
    def _build_images_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        intro = QLabel(
            "Where card images live locally, and which sizes/crops to keep. Real card images aren't wired up yet "
            "(see PROJECT_CONTEXT.md) -- this is the interface that'll drive that download once they are."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #a8adb5;")
        outer.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(14)

        content_layout.addWidget(section_label("Image Folder"))
        folder_row = QHBoxLayout()
        browse_folder_button = QPushButton("Browse Folder\u2026")
        browse_folder_button.clicked.connect(self._on_browse_image_folder)
        self.folder_path_label = QLabel("~/MTGLocalDB/images/")
        self.folder_path_label.setStyleSheet("font-weight: 600;")
        self.folder_path_label.setToolTip("Placeholder -- not yet linked to a real folder. Click Browse Folder.")
        self.folder_size_label = QLabel("0 B")
        self.folder_size_label.setMinimumWidth(90)
        self.folder_size_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        folder_row.addWidget(browse_folder_button)
        folder_row.addWidget(self.folder_path_label, stretch=1)
        folder_row.addWidget(self.folder_size_label)
        content_layout.addLayout(folder_row)

        content_layout.addWidget(section_label("Image Formats"))
        self.format_checks = {}
        for key, label, description, default_checked in IMAGE_FORMATS:
            row = QHBoxLayout()
            checkbox = QCheckBox(label)
            checkbox.setChecked(default_checked)
            checkbox.setMinimumWidth(110)
            desc = QLabel(description)
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #a8adb5;")
            row.addWidget(checkbox)
            row.addWidget(desc, stretch=1)
            content_layout.addLayout(row)
            self.format_checks[key] = checkbox

        content_layout.addWidget(section_label("Language & Editions"))
        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Image language:"))
        self.language_combo = QComboBox()
        self.language_combo.addItems(LANGUAGES)
        options_row.addWidget(self.language_combo)
        options_row.addSpacing(24)
        options_row.addWidget(QLabel("Editions:"))
        self.edition_button = self._build_edition_button()
        options_row.addWidget(self.edition_button)
        options_row.addStretch()
        content_layout.addLayout(options_row)

        content_layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        download_row = QHBoxLayout()
        self.download_feedback_label = QLabel("")
        self.download_feedback_label.setStyleSheet("color: #4caf50;")
        download_row.addWidget(self.download_feedback_label)
        download_row.addStretch()
        download_button = QPushButton("Download")
        download_button.setStyleSheet(APPLY_BUTTON_STYLE)
        download_button.clicked.connect(self._on_download_images)
        download_row.addWidget(download_button)
        outer.addLayout(download_row)

        return page

    def _on_browse_image_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose image folder")
        if not folder:
            return
        self.folder_path_label.setText(folder)
        self.folder_path_label.setToolTip(folder)
        self.folder_size_label.setText(_format_size(_folder_size(folder)))

    def _on_download_images(self):
        # No real download pipeline yet -- see module docstring.
        self.download_feedback_label.setText("Queued \u2713")
        QTimer.singleShot(1800, lambda: self.download_feedback_label.setText(""))

    def _build_edition_button(self):
        """
        A QToolButton whose popup is a checklist of placeholder editions --
        "All Editions" as a master toggle (checked by default, which is
        why the individual set actions start disabled: they're moot while
        it covers everything), or uncheck it to pick specific sets. See
        the module docstring for why this menu needs none of
        card_table.py's search-box-aware keyboard machinery -- there's no
        embedded search widget here for arrow-key navigation to compete
        with, so plain QMenu handles Up/Down/Space/Enter correctly with no
        extra code.
        """
        button = QToolButton()
        button.setPopupMode(QToolButton.InstantPopup)
        button.setText("All Editions")

        menu = _StayOpenMenu(button)
        all_action = menu.addAction("All Editions")
        all_action.setCheckable(True)
        all_action.setChecked(True)
        menu.addSeparator()

        set_actions = []
        for code in EDITION_OPTIONS:
            action = menu.addAction(code)
            action.setCheckable(True)
            action.setChecked(True)
            action.setEnabled(False)  # moot while "All Editions" covers everything
            set_actions.append(action)

        def refresh_button_text():
            if all_action.isChecked():
                button.setText("All Editions")
                return
            chosen = [a.text() for a in set_actions if a.isChecked()]
            if not chosen:
                button.setText("No Editions")
            else:
                button.setText(f"{len(chosen)} Edition{'s' if len(chosen) != 1 else ''}")

        def on_all_toggled(checked):
            for action in set_actions:
                action.setEnabled(not checked)
            refresh_button_text()

        all_action.toggled.connect(on_all_toggled)
        for action in set_actions:
            action.toggled.connect(lambda _checked: refresh_button_text())

        button.setMenu(menu)
        return button
