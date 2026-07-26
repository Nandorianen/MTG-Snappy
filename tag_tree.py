"""
tag_tree.py
-----------
The tag database browsing view (goal #5) -- still a visual stub, not wired
to real filtering logic, since that needs the tag database we haven't built.
Pulled out of main.py into its own module now that it's one of several
top-level views switched via the side nav, rather than a permanently-docked
side panel.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem


class TagTreePanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Tag hierarchy (not yet wired to card filtering)"))

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        layout.addWidget(self.tree)

        # A small hardcoded hierarchy just to prove the tree-with-subtags
        # concept from goal #5 -- "Removal" has children "Destroy"/"Exile",
        # while "Removal (Creature)" exists as its own separate branch, so a
        # card can be filed under a subtag without necessarily rolling up to
        # one single shared parent.
        removal = QTreeWidgetItem(self.tree, ["Removal"])
        QTreeWidgetItem(removal, ["Destroy"])
        QTreeWidgetItem(removal, ["Exile"])
        QTreeWidgetItem(self.tree, ["Removal (Creature)"])
        QTreeWidgetItem(self.tree, ["Removal (Enchantment)"])
        self.tree.expandAll()
