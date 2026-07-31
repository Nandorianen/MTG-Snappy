"""
tag_apply_dialog.py
--------------------
Right-click a card row (or a multi-selection of rows) in any card table to
open this: a checkbox tree mirroring the Tag Database, showing which tags
already apply, letting the user check/uncheck, and applying the result to
every selected card at once on "Apply."

BOTH FOLDERS AND LEAVES ARE CHECKABLE. This matches the original spec's
example directly: a card can be tagged "Removal" (the group) AND/OR
"Destroy" or "Exile" (the specific subtags) independently -- a folder in
the Tag Database is simultaneously an organizational container AND a
taggable category in its own right, not just a grouping label.

TRI-STATE LOGIC: if ALL selected cards already carry a tag, it starts
Checked. If NONE do, Unchecked. If SOME do, PartiallyChecked. Left
untouched, a PartiallyChecked tag is skipped entirely on Apply -- we only
ever act on tags the user explicitly resolved to fully Checked or fully
Unchecked, so leaving a mixed tag alone doesn't accidentally force it onto
every selected card (or strip it from the ones that had it). This needs no
"did the user click this" tracking: reading each item's final checkState()
at Apply time already tells us everything we need, since Qt's own
non-tristate click handling naturally moves a PartiallyChecked item to
Checked on the first click, then behaves as an ordinary two-state box.

Builds on the shared FramelessDialog (no OS title bar, custom draggable
title bar with a close button, closes on a genuine click in the main app
window) -- same treatment as the card detail popup.
"""

from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QPushButton
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from frameless_dialog import FramelessDialog
from tree_pane import _make_icon
import tag_assignments

CHECKED_COLOR = "#e6c15c"    # matches the "Foil: Yes" gold accent used elsewhere for an "active" state
UNCHECKED_COLOR = "#e3e3e3"  # the app's normal text color


class TagApplyDialog(FramelessDialog):
    def __init__(self, cards, tag_source, parent=None):
        super().__init__("Apply Tags", parent)
        self.cards = cards
        self.resize(340, 420)

        if len(cards) == 1:
            subtitle = f'Applying tags to: {cards[0]["name"]}'
        else:
            subtitle = f"Applying tags to {len(cards)} selected cards"
        subtitle_label = QLabel(subtitle)
        subtitle_label.setWordWrap(True)
        subtitle_label.setStyleSheet("color: #a8adb5;")
        self.content_layout.addWidget(subtitle_label)

        tag_nodes = tag_source.export_tree() if tag_source is not None else []

        if not tag_nodes:
            empty_label = QLabel(
                "No tags exist yet. Create some in the Tag Database tab, "
                "then right-click a card again to apply them."
            )
            empty_label.setWordWrap(True)
            self.content_layout.addWidget(empty_label)
            self.content_layout.addStretch()
            close_button = QPushButton("Close")
            close_button.clicked.connect(self.reject)
            self.content_layout.addWidget(close_button)
            return

        self.tag_tree = QTreeWidget()
        self.tag_tree.setHeaderHidden(True)
        self.tag_tree.itemChanged.connect(self._restyle_for_state)
        # The app-wide stylesheet sets `outline: 0` on QTreeWidget globally
        # (removing the native dashed focus rectangle elsewhere, which was
        # wanted there) -- but here we DO want a visible "this is the
        # keyboard cursor position" indicator, distinct from the bold/gold
        # CHECKED-state highlighting, so arrow-key navigation has visible
        # feedback. An instance-level style targeting the :focus pseudo-
        # state directly (rather than fighting `outline`) restores that.
        self.tag_tree.setStyleSheet(
            "QTreeWidget::item:focus { border: 1px solid #4f8fc0; border-radius: 2px; }"
        )
        self._build_checkbox_tree(tag_nodes)
        self.content_layout.addWidget(self.tag_tree)

        # Keyboard navigation works immediately on open, without requiring
        # a click into the tree first.
        self.tag_tree.setFocus()
        if self.tag_tree.topLevelItemCount() > 0:
            self.tag_tree.setCurrentItem(self.tag_tree.topLevelItem(0))

        button_row = QHBoxLayout()
        button_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        apply_button = QPushButton("Apply")
        apply_button.setDefault(True)
        apply_button.clicked.connect(self._apply)
        button_row.addWidget(cancel_button)
        button_row.addWidget(apply_button)
        self.content_layout.addLayout(button_row)

    def _build_checkbox_tree(self, nodes, parent_item=None):
        for node in nodes:
            item = QTreeWidgetItem([node["name"]])
            item.setData(0, Qt.UserRole, node["id"])
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            shape = "folder" if node["is_folder"] else "leaf"
            color = node.get("icon_color") or ("#c9a227" if node["is_folder"] else "#4f8fc0")
            item.setIcon(0, _make_icon(color, shape))
            item.setCheckState(0, self._initial_state_for_tag(node["id"]))
            # itemChanged only fires on SUBSEQUENT changes, not this initial
            # setCheckState call -- so apply the highlight once directly here too.
            self._restyle_for_state(item, 0)

            if parent_item is None:
                self.tag_tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)

            if node.get("children"):
                self._build_checkbox_tree(node["children"], item)

        if parent_item is None:
            self.tag_tree.expandAll()

    def _initial_state_for_tag(self, tag_id):
        have_count = sum(1 for card in self.cards if tag_id in tag_assignments.tags_for_card(card["name"]))
        if have_count == 0:
            return Qt.Unchecked
        if have_count == len(self.cards):
            return Qt.Checked
        return Qt.PartiallyChecked

    def _restyle_for_state(self, item, column):
        """
        Visually distinguishes a fully-CHECKED tag (bold + accent color)
        from unchecked/partial, so it's obvious at a glance which tags are
        actively selected in a tree that can get long.
        """
        checked = item.checkState(0) == Qt.Checked
        font = item.font(0)
        font.setBold(checked)
        item.setFont(0, font)
        item.setForeground(0, QColor(CHECKED_COLOR if checked else UNCHECKED_COLOR))

    def _apply(self):
        def walk(item):
            tag_id = item.data(0, Qt.UserRole)
            state = item.checkState(0)
            if state == Qt.Checked:
                for card in self.cards:
                    tag_assignments.add_tag(card["name"], tag_id)
            elif state == Qt.Unchecked:
                for card in self.cards:
                    tag_assignments.remove_tag(card["name"], tag_id)
            # PartiallyChecked: left untouched by the user -- skip, don't
            # force a mixed tag to either extreme.
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tag_tree.topLevelItemCount()):
            walk(self.tag_tree.topLevelItem(i))

        self.accept()
