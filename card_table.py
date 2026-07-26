"""
card_table.py
-------------
The central spreadsheet: a QAbstractTableModel (data) + QTableView (display)
pair, plus two pieces of custom machinery layered on top:

1. SplitDropdownHeader (QHeaderView subclass) -- draws the "Edition / Rarity"
   column as two independently-sortable halves, and a small dropdown arrow
   on the "Price" column that opens a source-picker menu instead of sorting.

2. ActionButtonDelegate (QStyledItemDelegate subclass) -- draws a small
   button-looking cell in the rightmost column and reacts to clicks, WITHOUT
   creating a real QPushButton per row.

WHY A DELEGATE INSTEAD OF setCellWidget()?
Qt lets you put a real widget in a cell via QTableWidget.setCellWidget(), which
is simpler to write. But that instantiates an actual QWidget object PER ROW,
PER INTERACTIVE COLUMN. With ~8 mock rows that's free; with tens of thousands
of real cards and several interactive columns, it becomes thousands of live
widgets the app has to keep in memory and repaint, which directly fights your
"snappy, lightweight, don't slow down on large datasets" goal. A delegate instead
just PAINTS the appearance of a button/checkbox/dropdown on demand (only for
rows currently visible on screen) and handles the click manually -- no widget
object exists per row at all. It's more code up front; it's the right call for
where this app is headed.
"""

from PySide6.QtWidgets import (
    QTableView, QHeaderView, QStyledItemDelegate, QStyle, QAbstractItemView,
    QApplication, QMenu,
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, QTimer, QRect, QEvent
from PySide6.QtGui import QKeySequence, QPainter, QColor

from mock_data import RARITY_ORDER
from card_popover import CardPopover


# --- Column definitions -----------------------------------------------------
# Each entry: (key, header_label, kind)
#   kind "checkbox" -> column 0, native Qt checkbox via CheckStateRole (no delegate needed --
#                      QTableView already knows how to draw and toggle a checkbox when a
#                      model reports Qt.ItemIsUserCheckable + returns CheckStateRole data).
#   kind "split"     -> the Edition/Rarity column, drawn/sorted specially by the header.
#   kind "price"     -> drawn normally in cells, but its HEADER has a dropdown menu.
#   kind "actions"   -> drawn specially by ActionButtonDelegate.
#   kind "text"      -> plain text, default rendering, default single-column sort.
COLUMNS = [
    ("selected", "", "checkbox"),
    ("qty", "Qty", "text"),
    ("name", "Name", "text"),
    ("edition_rarity", "Edition / Rarity", "split"),
    ("type_line", "Type", "text"),
    ("mana_cost", "Mana Cost", "text"),
    ("power_toughness", "P/T", "text"),
    ("price", "Price", "price"),
    ("actions", "", "actions"),
]
COL_SELECTED = 0
COL_QTY = 1
COL_NAME = 2
COL_EDITION_RARITY = 3
COL_TYPE = 4
COL_MANA = 5
COL_PT = 6
COL_PRICE = 7
COL_ACTIONS = 8

PRICE_SOURCES = [("price_tcg", "TCGplayer"), ("price_ck", "Card Kingdom"), ("price_cm", "Cardmarket")]


class CardTableModel(QAbstractTableModel):
    """
    Holds one list of card dicts (from mock_data for now, from a real
    inventory/wishlist DB query later) and answers Qt's questions about how
    to display and sort them. This is the ONLY class that knows what a
    "card dict" looks like internally -- the view and delegates just ask it
    for data by (row, column, role) and never touch self._cards directly.
    """

    def __init__(self, cards):
        super().__init__()
        self._cards = cards
        self.price_source = PRICE_SOURCES[0][0]  # which mock price field is currently shown
        self._sort_key = None
        self._sort_reverse = False

    # --- Required QAbstractTableModel overrides ---
    def rowCount(self, parent=QModelIndex()):
        return len(self._cards)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section][1]
        return super().headerData(section, orientation, role)

    def flags(self, index):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == COL_SELECTED:
            base |= Qt.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        card = self._cards[index.row()]
        col = index.column()

        if role == Qt.CheckStateRole and col == COL_SELECTED:
            return Qt.Checked if card.get("selected") else Qt.Unchecked

        if role == Qt.TextAlignmentRole and col in (COL_QTY, COL_MANA, COL_PT, COL_PRICE):
            return Qt.AlignCenter

        if role == Qt.DisplayRole:
            if col == COL_QTY:
                return str(card.get("qty", ""))
            if col == COL_NAME:
                return card["name"]
            if col == COL_EDITION_RARITY:
                return f'{card["set"].upper()}  /  {card["rarity"][0].upper()}'
            if col == COL_TYPE:
                return card["type_line"]
            if col == COL_MANA:
                return card["mana_cost"]
            if col == COL_PT:
                p, t = card.get("power"), card.get("toughness")
                return f"{p}/{t}" if p is not None else ""
            if col == COL_PRICE:
                return f"${card.get(self.price_source, 0):.2f}"
            # COL_SELECTED and COL_ACTIONS deliberately return no text --
            # they're drawn entirely by the checkbox mechanism / the delegate.
            return ""
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and index.column() == COL_SELECTED:
            self._cards[index.row()]["selected"] = (value == Qt.Checked)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False

    # --- Custom helpers (not part of the required QAbstractTableModel API) ---
    def card_at(self, row):
        return self._cards[row]

    def set_price_source(self, source_key):
        """Called when the user picks a source from the Price header's dropdown menu."""
        self.price_source = source_key
        top_left = self.index(0, COL_PRICE)
        bottom_right = self.index(self.rowCount() - 1, COL_PRICE)
        self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole])

    def sort_by_key(self, sort_key):
        """
        Dispatches a sort by KEY NAME (e.g. "name", "set", "rarity", "price")
        rather than by column index. We need this because our custom header
        can request a sort on "set" or "rarity" from the SAME physical column
        (Edition/Rarity) -- a plain column-index sort can't express that.
        Clicking the same key again reverses direction, like a normal table.
        """
        key_funcs = {
            "qty": lambda c: c.get("qty", 0),
            "name": lambda c: c["name"].lower(),
            "set": lambda c: c["set"],
            "rarity": lambda c: RARITY_ORDER.get(c["rarity"], 0),
            "type_line": lambda c: c["type_line"],
            "mana_cost": lambda c: c.get("cmc", 0),
            "power_toughness": lambda c: (c.get("power") if c.get("power") is not None else -1),
            "price": lambda c: c.get(self.price_source, 0),
        }
        func = key_funcs.get(sort_key)
        if func is None:
            return
        if self._sort_key == sort_key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_key = sort_key
            self._sort_reverse = False

        self.layoutAboutToBeChanged.emit()
        self._cards.sort(key=func, reverse=self._sort_reverse)
        self.layoutChanged.emit()


class SplitDropdownHeader(QHeaderView):
    """
    Custom header for two special columns:
      - Edition/Rarity: painted as two halves, each independently clickable
        to sort by that half's key.
      - Price: painted with a small dropdown arrow; clicking the arrow area
        emits a signal asking for a source-picker menu instead of sorting.

    KNOWN LIMITATION (documented rather than hidden): for these two special
    columns we fully handle the mouse press ourselves and don't call the
    parent implementation, which means drag-to-resize on those two specific
    header cells doesn't work yet. Every other column still resizes normally.
    Fixing that means detecting "click near the section border" vs "click in
    the middle" and only intercepting the latter -- straightforward, just not
    done in this first pass.
    """

    sort_requested = Signal(str)          # emits a sort key name, e.g. "rarity" or "price"
    price_menu_requested = Signal(object)  # emits a QPoint (global) to show the menu at

    def __init__(self, column_keys):
        super().__init__(Qt.Horizontal)
        self.setSectionsClickable(True)
        # Maps ordinary column indices -> the sort key name to request.
        # (Special columns are handled separately in mousePressEvent below.)
        self._column_keys = column_keys
        self._active_sort_key = None

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int):
        if logical_index == COL_EDITION_RARITY:
            self._paint_split_section(painter, rect)
            return
        if logical_index == COL_PRICE:
            super().paintSection(painter, rect, logical_index)
            self._paint_dropdown_arrow(painter, rect)
            return
        super().paintSection(painter, rect, logical_index)

    def _paint_split_section(self, painter, rect):
        painter.save()
        painter.fillRect(rect, self.palette().button().color())
        mid_x = rect.left() + rect.width() // 2

        left_rect = QRect(rect.left(), rect.top(), rect.width() // 2, rect.height())
        right_rect = QRect(mid_x, rect.top(), rect.width() - rect.width() // 2, rect.height())

        left_label = "Ed " + ("▲" if self._active_sort_key == "set" else "")
        right_label = "Rar " + ("▲" if self._active_sort_key == "rarity" else "")
        painter.drawText(left_rect, Qt.AlignCenter, left_label)
        painter.drawText(right_rect, Qt.AlignCenter, right_label)

        painter.setPen(self.palette().mid().color())
        painter.drawLine(mid_x, rect.top() + 4, mid_x, rect.bottom() - 4)
        painter.restore()

    def _paint_dropdown_arrow(self, painter, rect):
        painter.save()
        arrow_rect = QRect(rect.right() - 18, rect.top(), 18, rect.height())
        painter.setPen(self.palette().text().color())
        painter.drawText(arrow_rect, Qt.AlignCenter, "▾")
        painter.restore()

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        logical_index = self.logicalIndexAt(pos)
        section_x = self.sectionViewportPosition(logical_index)
        section_width = self.sectionSize(logical_index)
        rel_x = pos.x() - section_x

        if logical_index == COL_EDITION_RARITY:
            sort_key = "set" if rel_x < section_width / 2 else "rarity"
            self._active_sort_key = sort_key
            self.sort_requested.emit(sort_key)
            self.update()
            event.accept()
            return

        if logical_index == COL_PRICE:
            if rel_x > section_width - 20:
                global_pos = self.mapToGlobal(pos)
                self.price_menu_requested.emit(global_pos)
            else:
                self._active_sort_key = "price"
                self.sort_requested.emit("price")
                self.update()
            event.accept()
            return

        key = self._column_keys.get(logical_index)
        if key:
            self._active_sort_key = key
            self.sort_requested.emit(key)
            self.update()
        super().mousePressEvent(event)


class ActionButtonDelegate(QStyledItemDelegate):
    """
    Paints a small "..." button in the actions column and opens a stub menu
    on click. See the module docstring for why this is a delegate and not a
    real QPushButton placed in each row.
    """

    BUTTON_MARGIN = 6

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect.adjusted(self.BUTTON_MARGIN, self.BUTTON_MARGIN,
                                     -self.BUTTON_MARGIN, -self.BUTTON_MARGIN)
        hovered = bool(option.state & QStyle.State_MouseOver)
        painter.setBrush(QColor("#3d6a8f") if hovered else QColor("#3a3c41"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor("#e3e3e3"))
        painter.drawText(rect, Qt.AlignCenter, "\u22EF")  # a horizontal ellipsis, "⋯"
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease:
            menu = QMenu()
            menu.addAction("Add to deck")
            menu.addAction("Add to wishlist")
            menu.addAction("Remove")
            menu.exec(event.globalPosition().toPoint())
            return True
        return False


class CardTableView(QTableView):
    """
    The table widget itself. Configures selection to behave like a
    spreadsheet, adds Ctrl+C clipboard export, and drives the hover popover.
    """

    def __init__(self, cards):
        super().__init__()
        self.card_model = CardTableModel(cards)
        self.setModel(self.card_model)

        # --- Selection behavior: this is what gives us Ctrl+click / Shift+click /
        # arrow-key navigation "for free" -- Qt implements all of that natively
        # for any QTableView configured this way. Nothing below this comment
        # was written to make that part work; it already just works.
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

        # --- Custom header ---
        column_keys = {COL_QTY: "qty", COL_NAME: "name", COL_TYPE: "type_line",
                       COL_MANA: "mana_cost", COL_PT: "power_toughness"}
        self.header = SplitDropdownHeader(column_keys)
        self.setHorizontalHeader(self.header)
        self.header.sort_requested.connect(self.card_model.sort_by_key)
        self.header.price_menu_requested.connect(self._show_price_menu)

        # --- Actions column delegate ---
        self.setItemDelegateForColumn(COL_ACTIONS, ActionButtonDelegate(self))

        self.horizontalHeader().setStretchLastSection(False)
        self.setColumnWidth(COL_SELECTED, 28)
        self.setColumnWidth(COL_ACTIONS, 36)
        self.verticalHeader().setVisible(False)

        # --- Hover popover wiring ---
        self.viewport().setMouseTracking(True)
        self._popover = CardPopover()
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._show_popover)
        self._hover_index = QModelIndex()

    # --- Ctrl+C copy support: this is the one part of "Excel-like" behavior
    # Qt does NOT give us automatically. We gather selected cells, group them
    # by row, and join with tabs/newlines -- exactly the format spreadsheet
    # apps use, so pasting into Excel/Sheets/deckbox.org-style tools works.
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            self._copy_selection_to_clipboard()
            return
        super().keyPressEvent(event)

    def _copy_selection_to_clipboard(self):
        indexes = self.selectionModel().selectedIndexes()
        if not indexes:
            return
        indexes.sort(key=lambda idx: (idx.row(), idx.column()))
        lines, current_row, current_line = [], None, []
        for idx in indexes:
            if current_row is None:
                current_row = idx.row()
            if idx.row() != current_row:
                lines.append("\t".join(current_line))
                current_line = []
                current_row = idx.row()
            value = idx.data(Qt.DisplayRole)
            current_line.append("" if value is None else str(value))
        lines.append("\t".join(current_line))
        QApplication.clipboard().setText("\n".join(lines))

    def _show_price_menu(self, global_pos):
        menu = QMenu()
        for source_key, label in PRICE_SOURCES:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, k=source_key: self.card_model.set_price_source(k))
        menu.exec(global_pos)

    # --- Hover popover: mouse-move over the Name column starts a short
    # delay timer before showing the popover, so it doesn't flicker while
    # the cursor just passes through on its way somewhere else.
    def mouseMoveEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.column() == COL_NAME:
            if index != self._hover_index:
                self._hover_index = index
                self._hover_timer.start(350)
        else:
            self._hover_timer.stop()
            self._popover.hide()
            self._hover_index = QModelIndex()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_timer.stop()
        self._popover.hide()
        super().leaveEvent(event)

    def _show_popover(self):
        if not self._hover_index.isValid():
            return
        card = self.card_model.card_at(self._hover_index.row())
        anchor = self.visualRect(self._hover_index).bottomLeft()
        global_pos = self.viewport().mapToGlobal(anchor)
        self._popover.show_card(card, global_pos)
