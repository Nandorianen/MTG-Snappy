"""
tree_pane.py
------------
A generic tree of folders + "leaf" items (a Deck, or a Tag -- the label is
configurable) supporting everything asked for: create/rename/delete, drag &
drop reordering via Qt's native internal-move support, Ctrl+C/X/V as an
alternative to dragging, right-click context menu, a chooseable color icon
per item, and a full set of hotkeys.

WHY QTreeWidget (not a from-scratch tree)?
QTreeWidget already implements: expand/collapse, in-place rename via a
line-edit editor, and internal drag-and-drop reparenting -- all natively,
once configured with the right flags. Writing those from scratch would mean
re-implementing things Qt already gets right (e.g. drag-and-drop visual
feedback, keyboard-driven expand/collapse with Left/Right arrows). We only
write the parts Qt has no opinion about: unique auto-naming, select-all-on-
create, the icon color picker, and the cut/copy/paste clipboard.

DATA MODEL NOTE:
Each QTreeWidgetItem carries a small dict via setData(0, Qt.UserRole, ...):
    {"id": int, "is_folder": bool, "icon_color": str}
"id" doesn't do anything yet -- it's there because when this gets backed by
a real decks/tags database, each node's "id" will be the actual database row
id, and everything else in this file stays the same.

KNOWN GAPS (deliberately not solved here, to keep this file's job focused):
- The cycle guard and same-name dedup only apply to the Ctrl+X/Ctrl+V path.
  Real mouse drag-and-drop already refuses parent-into-own-child moves
  natively (that's Qt's own drag validation), but a drag-and-drop that
  results in a name collision is NOT deduped the way paste is -- worth
  revisiting if that turns out to matter in practice.
- True cross-widget copy/paste (between two separate TreePane instances)
  isn't implemented -- the clipboard here is per-instance, in-memory.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QMenu, QStyledItemDelegate, QAbstractItemView, QLineEdit,
    QMessageBox, QApplication,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QKeySequence, QShortcut, QBrush

# Palette offered in the right-click "Change Icon Color" submenu. Reusing a
# spread of hues rather than anything MTG-specific, since this same palette
# serves both the Deck tree and the Tag tree.
ICON_PALETTE = ["#c9a227", "#4f8fc0", "#00733e", "#d3202a",
                "#8a8d8f", "#9b59b6", "#e67e22", "#1abc9c"]
FOLDER_DEFAULT_COLOR = "#c9a227"
LEAF_DEFAULT_COLOR = "#4f8fc0"


def _make_icon(color, shape):
    """
    Builds a small flat-colored icon -- a rounded square for folders, a
    circle for leaf items, so the SHAPE (not just color) tells folders and
    decks/tags apart at a glance even before you account for chosen color.
    This is the "just color fill, as with card images" stand-in you asked
    for; swapping in real icon artwork later only means changing this
    function's body.
    """
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    if shape == "folder":
        painter.drawRoundedRect(1, 2, 14, 12, 3, 3)
    else:
        painter.drawEllipse(2, 2, 12, 12)
    painter.end()
    return QIcon(pixmap)


class _SelectAllEditDelegate(QStyledItemDelegate):
    """
    Qt's default rename editor places the cursor in the text WITHOUT
    selecting it. We want "type immediately overrides the name" for both
    F2-rename and new-item-creation, so we select all text the instant the
    editor appears. This one override is what makes that behavior real.
    """
    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            editor.selectAll()
        return editor


class TreePane(QWidget):
    """
    leaf_label / folder_label control the wording used in menus, shortcuts,
    and auto-generated names ("New Deck (1)" vs "New Tag (1)") -- this is
    the ONE constructor difference between the Deck tree and the Tag tree;
    everything else about the two is identical code.
    """

    # Emits the currently-selected node's data dict (or None if nothing is
    # selected) -- the containing view (DeckViewerView, TagTreePanel) listens
    # for this to decide what to show on the right-hand side.
    item_selected = Signal(object)

    def __init__(self, leaf_label="Item", folder_label="Folder", initial_tree=None):
        super().__init__()
        self.leaf_label = leaf_label
        self.folder_label = folder_label
        self._next_id = 1
        self._clipboard = []          # list of QTreeWidgetItem
        self._clipboard_mode = None   # "cut" or "copy"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # No toolbar here (deliberately removed) -- it only ever covered
        # "new item" / "new folder," a fraction of what right-click and the
        # keyboard shortcuts already do, and its buttons were the first
        # thing to grab keyboard focus, which is what made the very first
        # Tab press move focus to a button instead of collapsing the pane.
        # Create/rename/delete/etc. all remain fully available via Ctrl+N,
        # Ctrl+Shift+N, F2, Delete, and the right-click menu.
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)

        # Native drag-and-drop reparenting. InternalMove means "drag within
        # this same tree to move items," as opposed to dragging in/out of
        # other widgets, which we don't need here.
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.setDefaultDropAction(Qt.MoveAction)

        # EditKeyPressed is Qt's name for "the platform rename key" -- F2 on
        # Windows/Linux, Enter on macOS Finder-style apps. Combined with
        # DoubleClicked so either works.
        self.tree.setEditTriggers(QAbstractItemView.EditKeyPressed | QAbstractItemView.DoubleClicked)
        self.tree.setItemDelegate(_SelectAllEditDelegate(self.tree))

        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

        layout.addWidget(self.tree)

        if initial_tree:
            self._seed(initial_tree)

        self._install_shortcuts()

    def focus_tree(self):
        """
        Gives the tree widget itself keyboard focus. Called whenever this
        pane's tab becomes active (see main.py's _focus_current_view) so
        that a KNOWN, SENSIBLE widget has focus before the user might press
        Tab -- rather than leaving it to Qt's own "first focusable widget in
        creation order" default, which is what let Tab's very first press
        behave inconsistently.
        """
        self.tree.setFocus()

    def export_tree(self):
        """
        Returns a plain nested list of dicts (id/name/is_folder/icon_color/
        children) mirroring the current tree structure -- a read-only
        snapshot for external code (the tag-apply dialog) to build its OWN
        checkbox tree from. Deliberately NOT sharing actual QTreeWidgetItem
        objects: a Qt item can only belong to one QTreeWidget at a time, so
        cloning into plain dicts is what lets a second, independent tree
        widget exist showing "the same" tags without any ownership conflict.
        """
        def walk(item):
            node = item.data(0, Qt.UserRole)
            entry = {
                "id": node["id"],
                "name": item.text(0),
                "is_folder": node["is_folder"],
                "icon_color": node.get("icon_color"),
            }
            if item.childCount():
                entry["children"] = [walk(item.child(i)) for i in range(item.childCount())]
            return entry

        root = self.tree.invisibleRootItem()
        return [walk(root.child(i)) for i in range(root.childCount())]

    # --- Seeding demo/initial content -----------------------------------
    def _seed(self, nodes, parent_item=None):
        for spec in nodes:
            item = self._new_tree_item(spec["name"], spec.get("is_folder", False),
                                        spec.get("icon_color"))
            if parent_item is None:
                self.tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            if spec.get("children"):
                self._seed(spec["children"], item)
        if parent_item is None:
            self.tree.expandAll()

    def _new_tree_item(self, name, is_folder, icon_color=None):
        item = QTreeWidgetItem([name])
        node = {"id": self._next_id, "is_folder": is_folder, "icon_color": icon_color}
        self._next_id += 1
        item.setData(0, Qt.UserRole, node)
        self._apply_item_flags(item, is_folder)
        self._apply_icon(item)
        return item

    def _apply_item_flags(self, item, is_folder):
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsDragEnabled
        # Only folders accept drops -- this is what stops a user from
        # accidentally dragging a card-holding Deck "into" another Deck
        # and turning it into a sub-item.
        if is_folder:
            flags |= Qt.ItemIsDropEnabled
        item.setFlags(flags)

    def _apply_icon(self, item, color=None):
        node = item.data(0, Qt.UserRole)
        color = color or node.get("icon_color") or (
            FOLDER_DEFAULT_COLOR if node["is_folder"] else LEAF_DEFAULT_COLOR
        )
        node["icon_color"] = color
        item.setData(0, Qt.UserRole, node)
        item.setIcon(0, _make_icon(color, "folder" if node["is_folder"] else "leaf"))

    # --- Create / rename / delete ----------------------------------------
    def create_item(self, is_folder):
        label = self.folder_label if is_folder else self.leaf_label
        name = self._generate_unique_name(f"New {label}")
        target = self._resolve_target_folder()

        item = self._new_tree_item(name, is_folder)
        if target is None:
            self.tree.addTopLevelItem(item)
        else:
            target.addChild(item)
            target.setExpanded(True)

        self.tree.setCurrentItem(item)
        # editItem() opens the rename editor immediately -- combined with
        # the select-all delegate above, this gives "type immediately
        # overrides the name" for free.
        self.tree.editItem(item, 0)

    def _generate_unique_name(self, base_label):
        """
        Always numbered, per your spec ("New Folder (1)" even for the very
        first one) -- scans the WHOLE tree (not just the current folder) for
        the highest existing "{base_label} (N)" and returns N+1.
        """
        import re
        pattern = re.compile(rf'^{re.escape(base_label)} \((\d+)\)$')
        highest = 0

        def walk(item):
            nonlocal highest
            for i in range(item.childCount()):
                child = item.child(i)
                match = pattern.match(child.text(0))
                if match:
                    highest = max(highest, int(match.group(1)))
                walk(child)

        walk(self.tree.invisibleRootItem())
        return f"{base_label} ({highest + 1})"

    def _resolve_target_folder(self):
        """
        Where should a new/pasted item land? If a folder is selected, INTO
        it. If a leaf item is selected, alongside it (i.e. into ITS parent).
        If nothing is selected, at the top level.
        """
        item = self.tree.currentItem()
        if item is None:
            return None
        node = item.data(0, Qt.UserRole)
        return item if node["is_folder"] else item.parent()

    def _delete_selected(self):
        items = self.tree.selectedItems()
        if not items:
            return
        # Simple confirmation -- deliberately plain (no "don't ask again"
        # checkbox, no distinction between an empty folder and one full of
        # decks) since that's a UX refinement for later, not a safety gap.
        names = ", ".join(item.text(0) for item in items[:5])
        if len(items) > 5:
            names += f", and {len(items) - 5} more"
        reply = QMessageBox.question(
            self, "Delete", f"Delete {names}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        for item in items:
            parent = item.parent()
            (parent or self.tree.invisibleRootItem()).removeChild(item)

    # --- Cut / copy / paste -------------------------------------------------
    def _cut_selected(self):
        self._clipboard = list(self.tree.selectedItems())
        self._clipboard_mode = "cut"

    def _copy_selected(self):
        self._clipboard = list(self.tree.selectedItems())
        self._clipboard_mode = "copy"

    def _paste(self):
        if not self._clipboard:
            return
        target = self._resolve_target_folder()
        moved_any = False
        for item in self._clipboard:
            if self._clipboard_mode == "cut":
                # A cut+paste bypasses Qt's own drag-and-drop validation
                # (which is what stops you from dragging a folder into its
                # own child) -- so we have to check for that cycle
                # ourselves. Pasting a folder into itself or one of its own
                # descendants would make the item its own ancestor, which
                # hangs the tree the moment anything tries to walk it.
                if self._would_create_cycle(item, target):
                    self._reject_paste(item)
                    continue
                (item.parent() or self.tree.invisibleRootItem()).removeChild(item)
                new_name = self._dedup_sibling_name(target, item.text(0))
                if new_name != item.text(0):
                    item.setText(0, new_name)
                (target.addChild if target else self.tree.addTopLevelItem)(item)
                moved_any = True
            else:  # "copy" -- clone with fresh ids, leave the originals in place
                clone = self._clone_item(item)
                new_name = self._dedup_sibling_name(target, clone.text(0))
                if new_name != clone.text(0):
                    clone.setText(0, new_name)
                (target.addChild if target else self.tree.addTopLevelItem)(clone)
                moved_any = True
        if self._clipboard_mode == "cut" and moved_any:
            self._clipboard = []  # a cut clipboard is consumed after one successful paste
        if target and moved_any:
            target.setExpanded(True)

    def _would_create_cycle(self, item, target):
        """True if `target` is `item` itself, or nested somewhere inside it --
        i.e. pasting `item` into `target` would make item its own ancestor."""
        node = target
        while node is not None:
            if node is item:
                return True
            node = node.parent()
        return False

    def _dedup_sibling_name(self, target, desired_name):
        """
        If `desired_name` collides with something already in the destination
        (folder `target`, or the top level if target is None), append
        " (n)" -- same convention as the "New X (n)" auto-naming, so a user
        can paste several same-named items (e.g. copied from different
        folders) into one place without silently overwriting/confusing them.
        """
        if target is None:
            siblings = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        else:
            siblings = [target.child(i) for i in range(target.childCount())]
        existing = {s.text(0) for s in siblings}
        if desired_name not in existing:
            return desired_name
        n = 1
        while f"{desired_name} ({n})" in existing:
            n += 1
        return f"{desired_name} ({n})"

    def _reject_paste(self, item):
        """
        Non-intrusive "that's not allowed" feedback: the OS alert sound
        (QApplication.beep() -- no bundled audio needed, it plays whatever
        the platform's own system alert sound is) plus a couple of brief
        background-color flashes on the offending item. No dialog to
        dismiss, no workflow interruption.
        """
        QApplication.beep()
        self._flash_item(item)

    def _flash_item(self, item, flashes=3, interval_ms=120):
        original_brush = item.background(0)
        warning_brush = QBrush(QColor("#8f3d3d"))
        state = {"tick": 0}
        total_ticks = flashes * 2

        def tick():
            item.setBackground(0, warning_brush if state["tick"] % 2 == 0 else original_brush)
            state["tick"] += 1
            if state["tick"] >= total_ticks:
                self._flash_timer.stop()
                item.setBackground(0, original_brush)

        # Stored on self so the timer isn't garbage-collected mid-flash, and
        # so a second flash (unlikely, but possible) reuses the same timer
        # rather than leaking a new one.
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(tick)
        tick()
        self._flash_timer.start(interval_ms)

    def _clone_item(self, item):
        node = dict(item.data(0, Qt.UserRole))
        node["id"] = self._next_id
        self._next_id += 1
        clone = QTreeWidgetItem([item.text(0)])
        clone.setData(0, Qt.UserRole, node)
        clone.setFlags(item.flags())
        clone.setIcon(0, item.icon(0))
        for i in range(item.childCount()):
            clone.addChild(self._clone_item(item.child(i)))
        return clone


    # --- Context menu -------------------------------------------------------
    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)

        new_leaf_action = menu.addAction(f"New {self.leaf_label}\tCtrl+N")
        new_folder_action = menu.addAction(f"New {self.folder_label}\tCtrl+Shift+N")
        menu.addSeparator()
        rename_action = menu.addAction("Rename\tF2")
        delete_action = menu.addAction("Delete\tDel")
        rename_action.setEnabled(item is not None)
        delete_action.setEnabled(item is not None)
        menu.addSeparator()
        cut_action = menu.addAction("Cut\tCtrl+X")
        copy_action = menu.addAction("Copy\tCtrl+C")
        paste_action = menu.addAction("Paste\tCtrl+V")
        cut_action.setEnabled(item is not None)
        copy_action.setEnabled(item is not None)
        paste_action.setEnabled(bool(self._clipboard))

        color_menu = None
        if item is not None:
            menu.addSeparator()
            color_menu = menu.addMenu("Change Icon Color")
            node = item.data(0, Qt.UserRole)
            shape = "folder" if node["is_folder"] else "leaf"
            for color in ICON_PALETTE:
                color_action = color_menu.addAction(_make_icon(color, shape), "")
                color_action.triggered.connect(
                    lambda checked=False, c=color, it=item: self._apply_icon(it, c)
                )

        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is new_leaf_action:
            self.create_item(is_folder=False)
        elif chosen is new_folder_action:
            self.create_item(is_folder=True)
        elif chosen is rename_action:
            self.tree.editItem(item, 0)
        elif chosen is delete_action:
            self._delete_selected()
        elif chosen is cut_action:
            self._cut_selected()
        elif chosen is copy_action:
            self._copy_selected()
        elif chosen is paste_action:
            self._paste()

    # --- Selection signal ----------------------------------------------------
    def _on_selection_changed(self):
        items = self.tree.selectedItems()
        if not items:
            self.item_selected.emit(None)
            return
        # Emit a COPY with "name" merged in, rather than mutating the node
        # dict stored on the item -- "name" is derived (it's just item.text())
        # so we don't want it living twice as a source of truth.
        node = dict(items[0].data(0, Qt.UserRole))
        node["name"] = items[0].text(0)
        self.item_selected.emit(node)

    # --- Hotkeys ---------------------------------------------------------
    def _install_shortcuts(self):
        # WidgetWithChildrenShortcut scopes each shortcut to fire only when
        # focus is inside THIS pane (the pane itself or the tree/buttons
        # inside it) -- important once there are multiple TreePane instances
        # (Decks and Tags) alive in the same window; without this, Ctrl+N in
        # the Deck tab could also fire while the Tag tab has focus.
        def bind(sequence, slot):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
            return shortcut

        self._sc_new_leaf = bind("Ctrl+N", lambda: self.create_item(is_folder=False))
        self._sc_new_folder = bind("Ctrl+Shift+N", lambda: self.create_item(is_folder=True))
        self._sc_delete = bind("Delete", self._delete_selected)
        self._sc_cut = bind("Ctrl+X", self._cut_selected)
        self._sc_copy = bind("Ctrl+C", self._copy_selected)
        self._sc_paste = bind("Ctrl+V", self._paste)
        # F2 rename isn't bound here -- it's handled natively by the
        # QAbstractItemView edit triggers set on self.tree above.
