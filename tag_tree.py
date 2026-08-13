"""
tag_tree.py
-----------
The Tag Database tab. Built on the SAME TreePane + CollapsibleSplitter
as deck_viewer.py -- this is the payoff of building TreePane generically:
this file is almost entirely just configuration (labels + seed data), not
new logic. That directly satisfies goal #7 ("Tag Database pane should
support all the Deck view UI functions").
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Qt

from tree_pane import TreePane
from collapsible_pane import CollapsibleSplitter

# Same tag hierarchy example as before, now living in a fully editable tree
# instead of a static QTreeWidget -- rename/delete/drag/hotkeys all work on
# it already, with no tag-specific code required.
SEED_TAGS = [
    {"name": "Removal", "is_folder": True, "children": [
        {"name": "Destroy", "is_folder": False},
        {"name": "Exile", "is_folder": False},
    ]},
    {"name": "Removal (Creature)", "is_folder": False},
    {"name": "Removal (Enchantment)", "is_folder": False},
]


class TagTreePanel(QWidget):
    def __init__(self):
        super().__init__()
        self.tree_pane = TreePane(leaf_label="Tag", folder_label="Tag Group",
                                   initial_tree=SEED_TAGS)
        self.tree_pane.item_selected.connect(self._on_selection_changed)

        self.content_area = QLabel("Select a tag to view cards with that tag.")
        self.content_area.setAlignment(Qt.AlignCenter)

        self.splitter = CollapsibleSplitter(self.tree_pane, self.content_area)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

    def _on_selection_changed(self, node):
        if node and not node["is_folder"]:
            self.content_area.setText(
                f'Cards tagged "{node["name"]}" would render here.\n\n'
                "(Tag-based card filtering is a later feature -- goal #5.)"
            )
        else:
            self.content_area.setText("Select a tag to view cards with that tag.")
