"""
main.py
-------
Prototype PySide6 shell for the local MTG database app.

WHAT THIS IS (and isn't) right now:
- Real, working PySide6 widgets, laid out in the three-panel structure the whole
  app will eventually use: [tag tree] | [card list + search] | [card detail].
- Fed by mock_data.py instead of SQLite -- so search/select/filter are fully
  functional, just against a hardcoded list of 8 cards instead of ~30,000.
- No real card images yet -- the "art box" in the detail panel is a colored
  QFrame standing in for where a QPixmap will eventually go.
- The tag tree is visually real but not wired to anything (selecting a tag
  doesn't filter yet) -- that requires the tag database from goal #5, which
  we haven't built.

PySide6 CONCEPTS USED BELOW (flagged inline where they appear too):
- QMainWindow: a window that natively supports a menu bar, status bar, and a
  central widget -- as opposed to plain QWidget, which is just a blank canvas.
- Signals & Slots: Qt's event system. A "signal" is emitted when something
  happens (e.g. text changed, item clicked); a "slot" is any function you
  connect to that signal to react to it. `widget.signalName.connect(some_function)`
  is the core pattern you'll see everywhere below.
- Layouts (QVBoxLayout/QHBoxLayout): Qt does NOT use pixel-perfect manual
  positioning by default -- you nest layout objects, and Qt computes actual
  positions/sizes at runtime (and re-computes on window resize). This is what
  makes the UI responsive to resizing without extra code.
- QSplitter: like a layout, but the panels it holds can be resized by the user
  dragging the divider between them -- directly serves the "configurability"
  goal from your requirements.
"""

import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QListWidget, QListWidgetItem, QLabel, QFrame, QSplitter,
    QTreeWidget, QTreeWidgetItem, QStatusBar, QMenuBar, QMessageBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShortcut, QKeySequence

from mock_data import get_all_cards, swatch_for_card


class CardListPanel(QWidget):
    """
    Center panel: a search box + the list of cards.

    This class defines its OWN signal, `card_selected`, which fires whenever
    the user picks a different card in the list. main_window.py listens for
    that signal and updates the detail panel in response. This is deliberate
    decoupling: CardListPanel doesn't need to know that a detail panel exists
    at all -- it just announces "something was selected" and anyone interested
    can listen. That separation is what makes it easy to add more listeners
    later (e.g. a "quick add to collection" button) without touching this class.
    """

    # Signal(dict) declares a signal that carries one argument, a dict (the
    # selected card). Signals must be declared as class attributes, not inside
    # __init__ -- this is a PySide6/Qt requirement tied to how Qt's meta-object
    # system wires signals up at the C++ level under the hood.
    card_selected = Signal(dict)

    def __init__(self):
        super().__init__()

        # self.all_cards holds the full unfiltered set (from mock_data for now,
        # from a SQLite query later). self.filtered_cards is what's currently
        # shown, after the search box narrows it down.
        self.all_cards = get_all_cards()
        self.filtered_cards = list(self.all_cards)

        layout = QVBoxLayout(self)

        # --- Search box ---
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search cards by name...  (Ctrl+F)")
        # textChanged fires on every keystroke -- fine for 8 mock cards.
        # NOTE for later: once this is backed by a real SQLite table with
        # thousands of rows, we'll want this to trigger an indexed SQL query
        # (`WHERE name LIKE ?`) rather than a Python-side linear scan like the
        # one below -- the UI code barely needs to change, just what
        # _apply_filter() does internally.
        self.search_box.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_box)

        # --- Card list ---
        self.list_widget = QListWidget()
        # itemSelectionChanged fires whenever the highlighted row changes --
        # including via arrow keys, which QListWidget supports natively with
        # zero extra code from us. That's "keyboard control" goal #2, free.
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget)

        self._populate_list(self.filtered_cards)

    def _populate_list(self, cards):
        """Rebuild the visible list widget from a given card list."""
        self.list_widget.clear()
        for card in cards:
            # QListWidgetItem is one row. We store the FULL card dict on the
            # item itself via setData(Qt.UserRole, ...) -- UserRole is a Qt
            # constant reserved for "app-defined data you want to attach to a
            # widget item." This means we don't need a separate lookup table
            # to go from "which row is selected" back to "which card is that."
            item = QListWidgetItem(f'{card["name"]}  ({card["set"].upper()})')
            item.setData(Qt.UserRole, card)
            self.list_widget.addItem(item)

    def _apply_filter(self, search_text):
        """Slot connected to search_box.textChanged."""
        search_text = search_text.strip().lower()
        if not search_text:
            self.filtered_cards = list(self.all_cards)
        else:
            self.filtered_cards = [
                c for c in self.all_cards if search_text in c["name"].lower()
            ]
        self._populate_list(self.filtered_cards)

    def _on_selection_changed(self):
        """Slot connected to list_widget.itemSelectionChanged."""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
        card = selected_items[0].data(Qt.UserRole)
        # Emitting our own signal -- this is what main_window.py listens for.
        self.card_selected.emit(card)

    def focus_search(self):
        """Called from main_window's Ctrl+F shortcut."""
        self.search_box.setFocus()
        self.search_box.selectAll()


class CardDetailPanel(QWidget):
    """
    Right panel: shows the currently-selected card's details.

    The `art_box` QFrame here is a deliberate placeholder for where a real
    QPixmap (loaded from a local file or fetched via the Scryfall API) will
    go later. Keeping it as its own small widget now means that later we can
    swap "colored rectangle" for "actual image" by changing what happens
    inside this one class, without touching CardListPanel or MainWindow at all.
    """

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # Placeholder "art" -- a plain QFrame whose background color we set
        # via a stylesheet. Fixed size for now; real art will need to handle
        # aspect ratio and the hover-to-enlarge / mouse-wheel-print-switching
        # behavior from your requirements -- that's future work, noted here
        # rather than guessed at.
        self.art_box = QFrame()
        self.art_box.setFixedSize(220, 306)  # roughly MTG card aspect ratio
        self.art_box.setFrameShape(QFrame.Box)
        layout.addWidget(self.art_box, alignment=Qt.AlignHCenter)

        self.name_label = QLabel("Select a card")
        self.name_label.setObjectName("cardName")  # used by the stylesheet below
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)

        self.mana_label = QLabel("")
        layout.addWidget(self.mana_label)

        self.type_label = QLabel("")
        self.type_label.setObjectName("cardType")
        layout.addWidget(self.type_label)

        self.text_label = QLabel("")
        self.text_label.setWordWrap(True)
        layout.addWidget(self.text_label)

        layout.addStretch()  # pushes everything above upward, no gaps mid-panel

    def show_card(self, card):
        """
        Public method other widgets call (via the card_selected signal) to
        update what this panel displays.
        """
        self.name_label.setText(card["name"])
        self.mana_label.setText(f'Mana cost: {card["mana_cost"]}')
        self.type_label.setText(card["type_line"])
        self.text_label.setText(card["oracle_text"])

        swatch = swatch_for_card(card)
        self.art_box.setStyleSheet(f"background-color: {swatch}; border-radius: 6px;")


class TagTreePanel(QWidget):
    """
    Left panel: placeholder tag hierarchy (goal #5).

    This is intentionally NOT wired to filtering yet -- there's no tag
    database behind it. It exists so the three-panel layout is real and you
    can see where tag-based filtering will live, and so the tree WIDGET
    itself (nesting, checkboxes) is already proven out before we attach
    real logic to it.
    """

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Tags (not yet functional)"))

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        layout.addWidget(self.tree)

        # A small hardcoded hierarchy just to prove the tree-with-subtags
        # concept from goal #5 -- e.g. "Removal" has children "Destroy" and
        # "Exile", while "Removal (Creature)" exists as its own separate
        # branch, matching your example of a card being filable under a
        # subtag without necessarily rolling up to one single parent.
        removal = QTreeWidgetItem(self.tree, ["Removal"])
        QTreeWidgetItem(removal, ["Destroy"])
        QTreeWidgetItem(removal, ["Exile"])
        QTreeWidgetItem(self.tree, ["Removal (Creature)"])
        QTreeWidgetItem(self.tree, ["Removal (Enchantment)"])
        self.tree.expandAll()


class MainWindow(QMainWindow):
    """
    Top-level window. Assembles the three panels into a QSplitter (so the
    user can drag to resize them -- configurability goal), sets up the menu
    bar, status bar, and keyboard shortcuts.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MTG Local Database — Prototype")
        self.resize(1200, 750)

        # --- Build the three panels ---
        self.tag_panel = TagTreePanel()
        self.card_list_panel = CardListPanel()
        self.detail_panel = CardDetailPanel()

        # Wire the card list's custom signal to the detail panel's update
        # method. This one line is the entire connection between "user picked
        # a card" and "detail panel updates" -- everything else is decoupled.
        self.card_list_panel.card_selected.connect(self.detail_panel.show_card)

        # --- Splitter layout ---
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.tag_panel)
        splitter.addWidget(self.card_list_panel)
        splitter.addWidget(self.detail_panel)
        # Initial relative widths (in pixels, but Qt treats these as ratios
        # when the window resizes): narrow tag tree, wide list, medium detail.
        splitter.setSizes([200, 600, 350])

        self.setCentralWidget(splitter)

        self._build_menu_bar()
        self._build_status_bar()
        self._build_shortcuts()

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

        view_menu = menu_bar.addMenu("&View")
        toggle_tags = view_menu.addAction("Toggle Tag Panel")
        toggle_tags.setShortcut(QKeySequence("Ctrl+T"))
        toggle_tags.triggered.connect(
            lambda: self.tag_panel.setVisible(not self.tag_panel.isVisible())
        )

    def _stub_action(self, name):
        """Returns a function that shows a 'not implemented yet' dialog.
        Placeholder so the menu is real and clickable, without pretending
        we've built import/export logic that doesn't exist yet."""
        def handler():
            QMessageBox.information(self, name, f"{name} isn't implemented yet.")
        return handler

    def _build_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        total = len(self.card_list_panel.all_cards)
        self.status_bar.showMessage(f"{total} cards loaded (mock data)")

    def _build_shortcuts(self):
        """
        QShortcut binds a key sequence to a callback anywhere in the window,
        independent of which widget currently has focus -- useful for global
        hotkeys like "jump to search" that should work no matter what you
        were just clicking on.
        """
        ctrl_f = QShortcut(QKeySequence("Ctrl+F"), self)
        ctrl_f.activated.connect(self.card_list_panel.focus_search)


# A minimal, restrained dark stylesheet (QSS -- Qt's CSS-like styling
# language). Kept deliberately simple for a prototype: readable contrast,
# one accent color for selection/focus, no decoration beyond that.
STYLE_SHEET = """
QWidget {
    background-color: #1e1f22;
    color: #e3e3e3;
    font-size: 13px;
}
QLineEdit, QListWidget, QTreeWidget {
    background-color: #2b2d31;
    border: 1px solid #3a3c41;
    border-radius: 4px;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background-color: #3d6a8f;
}
#cardName {
    font-size: 18px;
    font-weight: 600;
}
#cardType {
    color: #a8adb5;
    font-style: italic;
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
