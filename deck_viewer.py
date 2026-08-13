"""
deck_viewer.py
--------------
The Deck Viewer tab: a folder/deck tree (via the generic TreePane) on the
left, wrapped in a CollapsibleSplitter, with a placeholder right-hand area
standing in for "the selected deck's actual card list" -- that's a real
CardTableView-shaped feature for a later pass, once decks can hold actual
card entries.
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Qt

from tree_pane import TreePane
from collapsible_pane import CollapsibleSplitter

# Placeholder seed data -- stands in for a real decks/folders database
# query, same pattern as mock_data.py's get_all_cards().
SEED_DECKS = [
    {"name": "Standard", "is_folder": True, "children": [
        {"name": "Mono Red Aggro", "is_folder": False},
        {"name": "Azorius Control", "is_folder": False},
    ]},
    {"name": "Commander", "is_folder": True, "children": [
        {"name": "Atraxa Superfriends", "is_folder": False},
    ]},
    {"name": "Unsorted Deck", "is_folder": False},
]


class DeckViewerView(QWidget):
    def __init__(self):
        super().__init__()
        self.tree_pane = TreePane(leaf_label="Deck", folder_label="Folder",
                                   initial_tree=SEED_DECKS)
        self.tree_pane.item_selected.connect(self._on_selection_changed)

        self.content_area = QLabel("Select a deck to view its contents.")
        self.content_area.setAlignment(Qt.AlignCenter)

        self.splitter = CollapsibleSplitter(self.tree_pane, self.content_area)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

    def _on_selection_changed(self, node):
        if node and not node["is_folder"]:
            self.content_area.setText(
                f'Deck contents for "{node["name"]}" would render here.\n\n'
                "(Deck contents view — a real card table per deck — is a later feature.)"
            )
        else:
            self.content_area.setText("Select a deck to view its contents.")
