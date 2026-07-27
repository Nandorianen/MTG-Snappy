"""
card_table.py
-------------
The central spreadsheet: a QAbstractTableModel (data) + QTableView (display)
pair, plus custom machinery layered on top:

1. SplitDropdownHeader (QHeaderView subclass) -- draws the "Edition / Rarity"
   column as two independently-sortable halves; draws a dropdown arrow on
   Price/Type/Mana Cost that opens a menu instead of sorting (price source,
   or "group by" for Type/Mana); and handles RIGHT-click for a per-column
   value filter plus a "Show Columns" visibility picker.

2. ActionButtonDelegate (QStyledItemDelegate subclass) -- draws a small
   button-looking cell in the rightmost column and reacts to clicks, WITHOUT
   creating a real QPushButton per row.

3. Grouping with sub-headers: when "Group by Type" or "Group by Color" is
   active, the model inserts synthetic full-width HEADER ROWS between
   groups of cards (e.g. a "Creature" bar, then all creatures, then an
   "Instant" bar, etc. -- the Deckbox-style layout). These header rows live
   only in the MODEL's presentation layer (self._display_rows) -- the real
   card data (self._cards) is never contaminated with fake rows.

WHY A DELEGATE INSTEAD OF setCellWidget()?
Qt lets you put a real widget in a cell via QTableWidget.setCellWidget(), which
is simpler to write. But that instantiates an actual QWidget object PER ROW,
PER INTERACTIVE COLUMN. With ~8 mock rows that's free; with tens of thousands
of real cards and several interactive columns, it becomes thousands of live
widgets the app has to keep in memory and repaint, which directly fights your
"snappy, lightweight, don't slow down on large datasets" goal. A delegate instead
just PAINTS the appearance of a button/checkbox/dropdown on demand (only for
rows currently visible on screen) and handles the click manually -- no widget
object exists per row at all.
"""

from PySide6.QtWidgets import (
    QTableView, QHeaderView, QStyledItemDelegate, QStyle, QAbstractItemView,
    QApplication, QMenu,
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, QTimer, QRect, QEvent
from PySide6.QtGui import QKeySequence, QPainter, QColor, QBrush

from mock_data import RARITY_ORDER, PRICE_SOURCES
from card_popover import CardPopover
from card_detail_popup import CardDetailDialog


# --- Column definitions -----------------------------------------------------
# Each entry: (key, header_label, kind)
#   kind "checkbox" -> column 0, native Qt checkbox via CheckStateRole.
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

# Columns whose header has a dropdown-arrow zone (as opposed to just sorting
# on click). Price opens a price-source picker; Type/Mana open a "group by"
# toggle. Clicking anywhere else in these headers still sorts, same as before.
DROPDOWN_COLUMNS = {COL_TYPE, COL_MANA, COL_PRICE}

# Columns offered in the right-click "Filter by..." value checklist. Skipped
# for the checkbox/actions utility columns (nothing meaningful to filter by)
# and for Price (continuous numeric data -- range filtering is a job for the
# future Search feature, not a same-value checklist).
FILTERABLE_COLUMNS = {COL_QTY, COL_NAME, COL_EDITION_RARITY, COL_TYPE, COL_MANA, COL_PT}

# Menu labels for columns whose header label is blank (checkbox/actions).
MENU_COLUMN_LABELS = {COL_SELECTED: "Checkbox", COL_ACTIONS: "Actions"}

# --- Grouping helpers --------------------------------------------------------
# Deckbox-style type ordering: creatures first (the "meat" of a deck), then
# spells, then permanents, lands last. Anything not matching becomes "Other".
TYPE_ORDER = ["Creature", "Planeswalker", "Instant", "Sorcery",
              "Artifact", "Enchantment", "Battle", "Kindred", "Land"]

# Supertypes stripped before category matching -- "Legendary Creature —
# Human Soldier" must group under "Creature", not get treated as some
# separate "Legendary" bucket. Substring matching against TYPE_ORDER would
# happen to work for most of these by luck (none of them collide with a
# TYPE_ORDER word), but stripping them explicitly makes that guarantee
# instead of an accident, and protects against a future edge case (e.g. a
# hypothetical supertype whose name happened to contain one of the words above).
SUPERTYPES_TO_STRIP = ["Legendary", "Basic", "Snow", "World", "Ongoing", "Elite"]

# WUBRG canonical order, used both for mono-color ordering and for naming
# multicolor combinations consistently (e.g. always "U/B", never "B/U").
COLOR_ORDER = ["W", "U", "B", "R", "G"]
COLOR_NAMES = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}


def _type_category(type_line):
    stripped = type_line
    for supertype in SUPERTYPES_TO_STRIP:
        stripped = stripped.replace(supertype, "")
    for category in TYPE_ORDER:
        if category in stripped:
            return category
    return "Other"


def _type_rank(card):
    category = _type_category(card["type_line"])
    return TYPE_ORDER.index(category) if category in TYPE_ORDER else len(TYPE_ORDER)


def _color_category(colors):
    if not colors:
        return "Colorless"
    if len(colors) == 1:
        return COLOR_NAMES[colors[0]]
    ordered = [c for c in COLOR_ORDER if c in colors]
    return "/".join(ordered)


def _color_rank(card):
    """
    Sort key for grouping: colorless first (rank 0), then each mono color in
    WUBRG order (ranks 1-5), then multicolor combos grouped by how many
    colors they use and ordered consistently within that (rank 10+, tie-
    broken by the WUBRG-ordered tuple of colors). The two branches never
    compare their second element against each other because their first
    elements (0-5 vs 10+) always differ first.
    """
    colors = card.get("colors", [])
    if not colors:
        return (0, "")
    if len(colors) == 1:
        return (1 + COLOR_ORDER.index(colors[0]), "")
    ordered = tuple(c for c in COLOR_ORDER if c in colors)
    return (10 + len(colors), ordered)


class CardTableModel(QAbstractTableModel):
    """
    Holds the card data plus everything needed to PRESENT it: sorting,
    grouping, per-column filters, and the resulting flat list of display
    rows (self._display_rows) that mixes real card rows with synthetic
    group-header rows. The view only ever asks this model "what's in row N,
    column M" -- it never needs to know about groups or filters itself.
    """

    def __init__(self, cards):
        super().__init__()
        self._source_cards = cards       # the master, unfiltered pool
        self._cards = list(cards)         # currently filtered + sorted + grouped working set
        self.price_source = PRICE_SOURCES[0][0]
        self._sort_key = None
        self._sort_reverse = False
        self.group_by = None              # None | "type" | "color"
        self._column_filters = {}         # {column: set(excluded_value_strings)}
        self._display_rows = [{"type": "card", "card": c} for c in self._cards]

    # --- Required QAbstractTableModel overrides ---
    def rowCount(self, parent=QModelIndex()):
        return len(self._display_rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section][1]
        return super().headerData(section, orientation, role)

    def flags(self, index):
        entry = self._display_rows[index.row()]
        if entry["type"] == "header":
            return Qt.NoItemFlags  # inert: not selectable, not clickable, not checkable
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == COL_SELECTED:
            base |= Qt.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        entry = self._display_rows[index.row()]
        col = index.column()

        if entry["type"] == "header":
            if role == Qt.DisplayRole and col == 0:
                return entry["label"]
            if role == Qt.BackgroundRole:
                return QBrush(QColor("#26282c"))
            return None

        card = entry["card"]

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
            return ""
        return None

    def setData(self, index, value, role=Qt.EditRole):
        entry = self._display_rows[index.row()]
        if entry["type"] == "header":
            return False
        if role == Qt.CheckStateRole and index.column() == COL_SELECTED:
            entry["card"]["selected"] = (value == Qt.Checked)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False

    # --- Custom helpers -----------------------------------------------------
    def card_at(self, row):
        """Returns the card dict for a row, or None if it's a group-header row."""
        entry = self._display_rows[row]
        return entry["card"] if entry["type"] == "card" else None

    def is_group_header(self, row):
        return self._display_rows[row]["type"] == "header"

    def set_price_source(self, source_key):
        self.price_source = source_key
        top_left = self.index(0, COL_PRICE)
        bottom_right = self.index(self.rowCount() - 1, COL_PRICE)
        self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole])

    def sort_by_key(self, sort_key):
        """
        Dispatches a sort by KEY NAME rather than by column index -- needed
        because the Edition/Rarity column can request a sort on either "set"
        or "rarity" from the SAME physical column. Clicking the same key
        again reverses direction.
        """
        if sort_key not in self._key_funcs():
            return
        if self._sort_key == sort_key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_key = sort_key
            self._sort_reverse = False
        self._commit_reorder()

    def set_group_by(self, mode):
        """Toggles grouping: clicking the same mode again turns it off."""
        self.group_by = None if self.group_by == mode else mode
        self._commit_reorder()

    def set_column_filter(self, column, excluded_values):
        self._column_filters[column] = set(excluded_values)
        self._commit_reorder()

    def distinct_values_for_column(self, column):
        values = set()
        for card in self._source_cards:
            value = self._raw_filter_value(card, column)
            if value is not None:
                values.add(value)
        return sorted(values)

    def _key_funcs(self):
        return {
            "qty": lambda c: c.get("qty", 0),
            "name": lambda c: c["name"].lower(),
            "set": lambda c: c["set"],
            "rarity": lambda c: RARITY_ORDER.get(c["rarity"], 0),
            "type_line": lambda c: c["type_line"],
            "mana_cost": lambda c: c.get("cmc", 0),
            "power_toughness": lambda c: (c.get("power") if c.get("power") is not None else -1),
            "price": lambda c: c.get(self.price_source, 0),
        }

    def _raw_filter_value(self, card, column):
        if column == COL_QTY:
            return str(card.get("qty", ""))
        if column == COL_NAME:
            return card["name"]
        if column == COL_EDITION_RARITY:
            return card["set"].upper()  # filters by SET only -- see class docstring / README gap note
        if column == COL_TYPE:
            return card["type_line"]
        if column == COL_MANA:
            return card["mana_cost"]
        if column == COL_PT:
            p, t = card.get("power"), card.get("toughness")
            return f"{p}/{t}" if p is not None else None
        return None

    def _passes_filters(self, card):
        for column, excluded in self._column_filters.items():
            if not excluded:
                continue
            if self._raw_filter_value(card, column) in excluded:
                return False
        return True

    def _commit_reorder(self):
        """
        The one place that actually re-derives self._cards (filtered subset
        of self._source_cards, sorted, then grouped) and rebuilds
        self._display_rows (cards + synthetic group headers). Wrapped in
        beginResetModel()/endResetModel() because grouping can change the
        ROW COUNT (headers are extra rows), which a plain layoutChanged
        signal doesn't account for.
        """
        self.beginResetModel()

        self._cards = [c for c in self._source_cards if self._passes_filters(c)]

        key_funcs = self._key_funcs()
        func = key_funcs.get(self._sort_key, key_funcs["name"])
        self._cards.sort(key=func, reverse=self._sort_reverse)
        # A second, separate stable sort by group rank -- Python's sort is
        # guaranteed stable, so this regroups the list WITHOUT disturbing
        # the within-group order the line above just established.
        if self.group_by == "type":
            self._cards.sort(key=_type_rank)
        elif self.group_by == "color":
            self._cards.sort(key=_color_rank)

        rows = []
        last_label = object()  # sentinel -- guarantees the first card always starts a group
        for card in self._cards:
            if self.group_by:
                label = _type_category(card["type_line"]) if self.group_by == "type" else _color_category(card.get("colors", []))
                if label != last_label:
                    rows.append({"type": "header", "label": label})
                    last_label = label
            rows.append({"type": "card", "card": card})
        self._display_rows = rows

        self.endResetModel()


class _StayOpenMenu(QMenu):
    """
    A QMenu where clicking a checkable action toggles it WITHOUT closing the
    menu -- the standard Qt idiom for a checklist-style dropdown (used for
    both the column visibility picker and the per-column value filter,
    where you want to check/uncheck several items in one go).
    """
    def mouseReleaseEvent(self, event):
        action = self.activeAction()
        if action is not None and action.isCheckable():
            action.trigger()
            return
        super().mouseReleaseEvent(event)


class SplitDropdownHeader(QHeaderView):
    """
    Custom header handling:
      - Edition/Rarity: painted as two halves, each independently sortable.
      - Price/Type/Mana Cost: a dropdown-arrow zone on the right edge opens
        a menu (price source, or group-by) instead of sorting; clicking
        elsewhere in these headers still sorts normally.
      - RIGHT-click anywhere: a context menu with a per-column value
        checklist filter (where applicable) and a "Show Columns" submenu
        for toggling column visibility live.
      - A few pixels at each section border are reserved EXCLUSIVELY for
        drag-to-resize, checked first, before any of the above.

    Reads/writes model state directly via self.model() (Qt wires this up
    automatically once the header is attached to a view via
    setHorizontalHeader()) rather than round-tripping through signals --
    reasonable here since this header is only ever used with CardTableModel.

    WHY RESIZE IS HANDLED MANUALLY RATHER THAN VIA super().mousePressEvent():
    Qt's own QHeaderView normally detects "click near a border" internally
    and starts a resize drag on its own. But since this header already
    intercepts every mousePressEvent to decide between sort / split-sort /
    dropdown-menu / right-click-filter, and those decisions were being made
    using OUR OWN idea of where the section boundary is, a click near an
    edge kept getting swallowed as "sort this column" before Qt's internal
    resize detection ever got a chance to see it -- which is exactly the bug
    reported ("clicking the border is read as sort"). Rather than hope our
    margin and Qt's internal margin happen to agree, RESIZE_MARGIN below is
    checked FIRST and, when it matches, this class does the entire
    press/move/release resize sequence itself (see mouseMoveEvent /
    mouseReleaseEvent) -- deterministic, and directly testable without
    depending on Qt's internal fuzzy hit-testing.
    """

    sort_requested = Signal(str)
    price_menu_requested = Signal(object)

    RESIZE_MARGIN = 6      # pixels at each section edge reserved purely for resizing
    ARROW_WIDTH = 18       # width reserved for the dropdown arrow glyph
    MIN_SECTION_WIDTH = 24

    def __init__(self, column_keys):
        super().__init__(Qt.Horizontal)
        self.setSectionsClickable(True)
        self._column_keys = column_keys
        self._active_sort_key = None
        self._resizing_column = None
        self._resize_start_x = None
        self._resize_start_width = None

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int):
        if logical_index == COL_EDITION_RARITY:
            self._paint_split_section(painter, rect)
            return
        if logical_index in DROPDOWN_COLUMNS:
            self._paint_section_with_arrow(painter, rect, logical_index)
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

    def _paint_section_with_arrow(self, painter, rect, logical_index):
        """
        Draws the label ELIDED TO A RECT THAT EXCLUDES THE ARROW ZONE, rather
        than drawing the full-width centered label (via super().paintSection)
        and then drawing the arrow on top of it -- the previous approach,
        which is exactly what let a long label run underneath the arrow
        glyph. Reserving the space up front means the two can never overlap.
        """
        painter.save()
        painter.fillRect(rect, self.palette().button().color())

        text_rect = rect.adjusted(6, 0, -(self.ARROW_WIDTH + 4), 0)
        label = COLUMNS[logical_index][1]
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(label, Qt.ElideRight, max(text_rect.width(), 0))
        painter.setPen(self.palette().text().color())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

        arrow_rect = QRect(rect.right() - self.ARROW_WIDTH, rect.top(), self.ARROW_WIDTH, rect.height())
        painter.drawText(arrow_rect, Qt.AlignCenter, "▾")
        painter.restore()

    # --- Manual resize: press near a border, drag, release -------------------
    def _resize_target_at(self, pos):
        """
        Returns the logical column index that a press at `pos` should
        resize, or None if `pos` isn't within RESIZE_MARGIN of any border.
        Pressing near the LEFT edge of section N resizes section N-1 (its
        RIGHT edge) -- the same convention every spreadsheet/table UI uses,
        since visually there's one shared border between two columns, not
        two independent ones.
        """
        logical_index = self.logicalIndexAt(pos)
        if logical_index < 0:
            return None
        section_x = self.sectionViewportPosition(logical_index)
        section_width = self.sectionSize(logical_index)
        rel_x = pos.x() - section_x

        if rel_x >= section_width - self.RESIZE_MARGIN:
            return logical_index
        if rel_x <= self.RESIZE_MARGIN:
            visual = self.visualIndex(logical_index)
            if visual > 0:
                return self.logicalIndex(visual - 1)
            return logical_index
        return None

    def mousePressEvent(self, event):
        pos = event.position().toPoint()

        if event.button() == Qt.LeftButton:
            target = self._resize_target_at(pos)
            if target is not None:
                self._resizing_column = target
                self._resize_start_x = pos.x()
                self._resize_start_width = self.sectionSize(target)
                event.accept()
                return

        logical_index = self.logicalIndexAt(pos)

        if event.button() == Qt.RightButton:
            self._show_context_menu(logical_index, self.mapToGlobal(pos))
            event.accept()
            return

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

        if logical_index in DROPDOWN_COLUMNS:
            if rel_x > section_width - 20:
                self._show_dropdown_menu(logical_index, self.mapToGlobal(pos))
            else:
                key = self._column_keys.get(logical_index)
                if key:
                    self._active_sort_key = key
                    self.sort_requested.emit(key)
                    self.update()
            event.accept()
            return

        key = self._column_keys.get(logical_index)
        if key:
            self._active_sort_key = key
            self.sort_requested.emit(key)
            self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._resizing_column is not None:
            delta = event.position().toPoint().x() - self._resize_start_x
            new_width = max(self.MIN_SECTION_WIDTH, self._resize_start_width + delta)
            self.resizeSection(self._resizing_column, new_width)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing_column is not None:
            self._resizing_column = None
            self._resize_start_x = None
            self._resize_start_width = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # --- Dropdown-arrow menus (Price source / Group by) ---------------------
    def _show_dropdown_menu(self, column, global_pos):
        if column == COL_PRICE:
            self.price_menu_requested.emit(global_pos)
            return
        menu = self._build_dropdown_menu(column)
        if menu is not None:
            menu.exec(global_pos)

    def _build_dropdown_menu(self, column):
        mode = "type" if column == COL_TYPE else "color"
        label = "Type" if mode == "type" else "Color"
        menu = QMenu(self)
        action = menu.addAction(f"Group by {label}")
        action.setCheckable(True)
        action.setChecked(self.model().group_by == mode)
        action.triggered.connect(lambda checked=False, m=mode: self.model().set_group_by(m))
        return menu

    # --- Right-click: per-column filter + column visibility ------------------
    def _show_context_menu(self, column, global_pos):
        self._build_context_menu(column).exec(global_pos)

    def _build_context_menu(self, column):
        menu = _StayOpenMenu(self)

        if column in FILTERABLE_COLUMNS:
            label = COLUMNS[column][1] or "this column"
            header_action = menu.addAction(f"Filter by {label}")
            header_action.setEnabled(False)  # acts as a section label, not clickable
            menu.addSeparator()
            excluded = self.model()._column_filters.get(column, set())
            for value in self.model().distinct_values_for_column(column):
                action = menu.addAction(value)
                action.setCheckable(True)
                action.setChecked(value not in excluded)
                action.toggled.connect(
                    lambda checked, v=value, col=column: self._on_filter_toggled(col, v, checked)
                )
            menu.addSeparator()

        columns_menu = menu.addMenu("Show Columns")
        for index, (_key, label, _kind) in enumerate(COLUMNS):
            display_label = label or MENU_COLUMN_LABELS.get(index, f"Column {index}")
            action = columns_menu.addAction(display_label)
            action.setCheckable(True)
            action.setChecked(not self.isSectionHidden(index))
            action.toggled.connect(lambda checked, i=index: self.setSectionHidden(i, not checked))

        return menu

    def _on_filter_toggled(self, column, value, checked):
        excluded = set(self.model()._column_filters.get(column, set()))
        if checked:
            excluded.discard(value)
        else:
            excluded.add(value)
        self.model().set_column_filter(column, excluded)


class ActionButtonDelegate(QStyledItemDelegate):
    """
    Paints a small "..." button in the actions column and opens a stub menu
    on click. Skips group-header rows entirely (nothing to act on there).
    """

    BUTTON_MARGIN = 6

    def paint(self, painter, option, index):
        if index.model().card_at(index.row()) is None:
            return  # a group-header row -- nothing to draw here
        painter.save()
        rect = option.rect.adjusted(self.BUTTON_MARGIN, self.BUTTON_MARGIN,
                                     -self.BUTTON_MARGIN, -self.BUTTON_MARGIN)
        hovered = bool(option.state & QStyle.State_MouseOver)
        painter.setBrush(QColor("#3d6a8f") if hovered else QColor("#3a3c41"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor("#e3e3e3"))
        painter.drawText(rect, Qt.AlignCenter, "\u22EF")
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if model.card_at(index.row()) is None:
            return False
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
    spreadsheet, adds Ctrl+C clipboard export, drives the hover popover, and
    keeps the group-header full-width row spans in sync with the model.
    """

    def __init__(self, cards):
        super().__init__()
        self.card_model = CardTableModel(cards)
        self.setModel(self.card_model)

        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

        column_keys = {COL_QTY: "qty", COL_NAME: "name", COL_TYPE: "type_line",
                       COL_MANA: "mana_cost", COL_PT: "power_toughness", COL_PRICE: "price"}
        self.header = SplitDropdownHeader(column_keys)
        self.setHorizontalHeader(self.header)
        self.header.sort_requested.connect(self.card_model.sort_by_key)
        self.header.price_menu_requested.connect(self._show_price_menu)
        # The header is a separate sibling widget from the viewport, not a
        # region within it -- moving the mouse from the viewport up onto the
        # header doesn't fire the VIEW's mouseMoveEvent/leaveEvent at all
        # (that's why the hover popover was sticking around). An event
        # filter on the header itself is the reliable way to notice "the
        # cursor just entered a completely different widget."
        self.header.installEventFilter(self)

        # Whenever the model resets (sort/group/filter change), row 0..N
        # shift around and any previously-spanned header rows need to be
        # recomputed from scratch.
        self.card_model.modelReset.connect(self._reapply_group_spans)

        self.setItemDelegateForColumn(COL_ACTIONS, ActionButtonDelegate(self))

        self.horizontalHeader().setStretchLastSection(False)
        self.setColumnWidth(COL_SELECTED, 28)
        self.setColumnWidth(COL_ACTIONS, 36)
        self.verticalHeader().setVisible(False)

        self.viewport().setMouseTracking(True)
        self._popover = CardPopover()
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._show_popover)
        self._hover_index = QModelIndex()

        self._detail_dialog = None
        self.doubleClicked.connect(self._open_card_detail)

    def eventFilter(self, watched, event):
        if watched is self.header and event.type() == QEvent.Enter:
            self._hover_timer.stop()
            self._popover.hide()
            self._hover_index = QModelIndex()
        return super().eventFilter(watched, event)

    def _reapply_group_spans(self):
        """
        Merges each group-header row's cells into one full-width bar via
        QTableView.setSpan(). Has to be redone from scratch on every reset
        since the row positions of headers move whenever sort/group/filter
        state changes.
        """
        self.clearSpans()
        column_count = self.card_model.columnCount()
        for row in range(self.card_model.rowCount()):
            if self.card_model.is_group_header(row):
                self.setSpan(row, 0, 1, column_count)

    def _open_card_detail(self, index):
        card = self.card_model.card_at(index.row())
        if card is None:
            return  # double-clicked a group-header row -- nothing to open
        self._detail_dialog = CardDetailDialog(card["name"], parent=self)
        self._detail_dialog.show()

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

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if (index.isValid() and index.column() == COL_NAME
                and self.card_model.card_at(index.row()) is not None):
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
        if card is None:
            return
        anchor = self.visualRect(self._hover_index).bottomLeft()
        global_pos = self.viewport().mapToGlobal(anchor)
        self._popover.show_card(card, global_pos)
