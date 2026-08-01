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
    QApplication, QMenu, QLineEdit, QWidgetAction,
)
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, Signal, QTimer, QRect, QEvent,
    QItemSelection, QItemSelectionModel,
)
from PySide6.QtGui import QKeySequence, QPainter, QColor, QBrush

from mock_data import RARITY_ORDER, PRICE_SOURCES
from card_popover import CardPopover
from card_detail_popup import CardDetailDialog
from tag_apply_dialog import TagApplyDialog


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
    ("cross_qty", "", "text"),  # label is set per-instance -- see CardTableModel.headerData
    ("name", "Name", "text"),
    ("edition_rarity", "Edition / Rarity", "split"),
    ("type_line", "Type", "text"),
    ("mana_cost", "Mana Cost", "text"),
    ("power", "Power", "text"),
    ("toughness", "Toughness", "text"),
    ("price", "Price", "price"),
    ("actions", "", "actions"),
]
COL_SELECTED = 0
COL_QTY = 1
COL_CROSS_QTY = 2
COL_NAME = 3
COL_EDITION_RARITY = 4
COL_TYPE = 5
COL_MANA = 6
COL_POWER = 7
COL_TOUGHNESS = 8
COL_PRICE = 9
COL_ACTIONS = 10

# Columns whose header has a dropdown-arrow zone (as opposed to just sorting
# on click). Price opens a price-source picker; Type/Mana open a "group by"
# toggle. Clicking anywhere else in these headers still sorts, same as before.
DROPDOWN_COLUMNS = {COL_TYPE, COL_MANA, COL_PRICE}

# Custom-painted header sections (the split Edition/Rarity column, and any
# DROPDOWN_COLUMNS section) can't rely on self.palette().button().color()
# for their background -- that reads the widget's base QPalette, which the
# app's QSS stylesheet (main.py's STYLE_SHEET, `QHeaderView::section {
# background-color: ... }`) does NOT update; QSS and QPalette are separate
# systems in Qt, and only Qt's OWN default section painting (used by every
# OTHER column) actually goes through the style sheet. Without this shared
# constant, custom-painted headers visibly mismatched the plain ones.
#
# Color choice: deliberately darker than the row background (#2b2d31) --
# this used to happen by accident (palette().button() rendering near-black)
# and reads better than matching the rows exactly, since a header that's
# visually distinct from its own rows is easier to spot at a glance. Keep
# this in sync with QHeaderView::section's background-color in main.py's
# STYLE_SHEET.
HEADER_BG = "#141517"

# Columns offered in the right-click "Filter by..." value checklist. Skipped
# for the checkbox/actions utility columns (nothing meaningful to filter by)
# and for Price (continuous numeric data -- range filtering is a job for the
# future Search feature, not a same-value checklist).
FILTERABLE_COLUMNS = {COL_QTY, COL_CROSS_QTY, COL_NAME, COL_EDITION_RARITY, COL_TYPE, COL_MANA, COL_POWER, COL_TOUGHNESS, COL_PRICE}

# How a missing Power/Toughness (non-creatures have none) is represented in
# the filter checklist. Without this, distinct_values_for_column would just
# never offer a way to filter "show only creatures" / "show only
# non-creatures" at all, since None values would need special-casing
# everywhere they're compared/displayed instead of being a normal string.
EMPTY_VALUE_LABEL = "(none)"

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
NAME_TO_COLOR_LETTER = {name: letter for letter, name in COLOR_NAMES.items()}


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


def _numeric_sort_value(value):
    """
    Power/toughness sort key helper. Real MTG data isn't always a plain
    number -- Scryfall itself stores power/toughness as STRINGS because
    cards like Tarmogoyf-style "*/*+1" or "1+*" creatures exist -- so this
    can't just assume int(value) works. Non-numeric values sort alongside
    non-creatures (-1) rather than crashing the sort.
    """
    if value is None:
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


class CardTableModel(QAbstractTableModel):
    """
    Holds the card data plus everything needed to PRESENT it: sorting,
    grouping, per-column filters, and the resulting flat list of display
    rows (self._display_rows) that mixes real card rows with synthetic
    group-header rows. The view only ever asks this model "what's in row N,
    column M" -- it never needs to know about groups or filters itself.
    """

    def __init__(self, cards, qty_label="Qty", cross_qty_label="Cross"):
        super().__init__()
        self._source_cards = cards       # the master, unfiltered pool
        self._cards = list(cards)         # currently filtered + sorted + grouped working set
        self.price_source = PRICE_SOURCES[0][0]
        self.qty_label = qty_label              # e.g. "Have" on both All Card Database and Inventory
        self.cross_qty_label = cross_qty_label  # e.g. "Want" alongside it
        self._sort_key = None
        self._sort_reverse = False
        self.group_by = None              # None | "type" | "color"
        self._column_filters = {}         # {column: set(excluded_value_strings)}
        # A SEPARATE boolean flag, not expressed via the checklist exclusion
        # mechanism: "only cards with exactly one color" (excludes both
        # colorless AND multicolor). Kept independent of the per-color
        # checkboxes below so the two combine naturally -- turn this on to
        # restrict to single-color cards, then still use the individual
        # White/Blue/.../Green checkboxes to narrow WHICH mono colors show.
        self.mana_mono_only = False
        # Per-COLOR-LETTER exclusion (e.g. {"B", "U"}), NOT tied to the
        # generic _column_filters exact-value-match mechanism. That
        # distinction matters: unchecking "Black" needs to hide EVERY card
        # containing black -- mono-black AND multicolor black-inclusive
        # cards like a U/B card -- not just cards whose color category is
        # the exact string "Black". A value-exclusion-set keyed on
        # _color_category() strings could never express that, since a U/B
        # card's category is "U/B", never "Black" or "Blue" individually.
        self.mana_excluded_colors = set()
        self._display_rows = [{"type": "card", "card": c} for c in self._cards]

    # --- Required QAbstractTableModel overrides ---
    def rowCount(self, parent=QModelIndex()):
        return len(self._display_rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if section == COL_QTY:
                return self.qty_label
            if section == COL_CROSS_QTY:
                return self.cross_qty_label
            return COLUMNS[section][1]
        return super().headerData(section, orientation, role)

    def flags(self, index):
        entry = self._display_rows[index.row()]
        if entry["type"] == "header":
            return Qt.NoItemFlags  # inert: not selectable, not clickable, not checkable
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == COL_SELECTED:
            base |= Qt.ItemIsUserCheckable
        if index.column() == COL_QTY:
            base |= Qt.ItemIsEditable
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

        if role == Qt.TextAlignmentRole and col in (COL_QTY, COL_CROSS_QTY, COL_MANA, COL_POWER, COL_TOUGHNESS, COL_PRICE):
            return Qt.AlignCenter

        if role == Qt.DisplayRole:
            if col == COL_QTY:
                return str(card.get("qty", ""))
            if col == COL_CROSS_QTY:
                return str(card.get("cross_qty", ""))
            if col == COL_NAME:
                return card["name"]
            if col == COL_EDITION_RARITY:
                return f'{card["set"].upper()}  /  {card["rarity"][0].upper()}'
            if col == COL_TYPE:
                return card["type_line"]
            if col == COL_MANA:
                return card["mana_cost"]
            if col == COL_POWER:
                power = card.get("power")
                return "" if power is None else str(power)
            if col == COL_TOUGHNESS:
                toughness = card.get("toughness")
                return "" if toughness is None else str(toughness)
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
        if role == Qt.EditRole and index.column() == COL_QTY:
            try:
                new_qty = max(0, int(value))
            except (TypeError, ValueError):
                return False  # reject non-numeric input rather than corrupting the count
            entry["card"]["qty"] = new_qty
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
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

    def is_value_excluded(self, column, value):
        """
        Whether a single value is currently excluded from `column`'s filter
        -- e.g. is_value_excluded(COL_QTY, "0") answers "is the Inventory
        preset currently active." Read by anything that needs to REFLECT
        filter state (the header checklist's checkboxes, and
        CardDatabaseView's Inventory/Wishlist toggle buttons) rather than
        just set it, so both stay honest about what's actually applied
        instead of tracking their own separate assumption of it.
        """
        return value in self._column_filters.get(column, set())

    def set_value_excluded(self, column, value, excluded):
        """
        Adds or removes exactly ONE value from a column's exclusion set,
        leaving every other manually-set exclusion on that same column
        untouched. This is the single code path both the header checklist
        (_on_filter_toggled) and the Inventory/Wishlist preset buttons
        route through -- one add/discard-from-set implementation instead of
        two copies that could quietly drift apart.
        """
        current = set(self._column_filters.get(column, set()))
        if excluded:
            current.add(value)
        else:
            current.discard(value)
        self.set_column_filter(column, current)  # already calls _commit_reorder()

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
            "cross_qty": lambda c: c.get("cross_qty", 0),
            "name": lambda c: c["name"].lower(),
            "set": lambda c: c["set"],
            "rarity": lambda c: RARITY_ORDER.get(c["rarity"], 0),
            "type_line": lambda c: c["type_line"],
            "mana_cost": lambda c: c.get("cmc", 0),
            "power": lambda c: _numeric_sort_value(c.get("power")),
            "toughness": lambda c: _numeric_sort_value(c.get("toughness")),
            "price": lambda c: c.get(self.price_source, 0),
        }

    def _raw_filter_value(self, card, column):
        if column == COL_QTY:
            return str(card.get("qty", ""))
        if column == COL_CROSS_QTY:
            return str(card.get("cross_qty", ""))
        if column == COL_NAME:
            return card["name"]
        if column == COL_EDITION_RARITY:
            return card["set"].upper()  # filters by SET only -- see class docstring / README gap note
        if column == COL_TYPE:
            # Broad category, same as grouping uses -- NOT the literal full
            # type line. A checklist of every distinct full type_line string
            # ("Legendary Creature — Human Soldier", "Creature — Angel", ...)
            # would be nearly as long as the card list itself and useless as
            # a filter; "Creature" / "Instant" / etc. is what's actually
            # useful to filter by.
            return _type_category(card["type_line"])
        if column == COL_MANA:
            # Filters by COLOR CATEGORY (same buckets Group-by-Color uses:
            # Colorless / White / Blue / .../ multicolor combos like "U/B"),
            # not the literal mana cost string -- this is what makes "show
            # me mono-white cards only" possible, which a checklist of raw
            # mana-cost strings like "{1}{W}" vs "{W}{W}" never could.
            return _color_category(card.get("colors", []))
        if column == COL_POWER:
            power = card.get("power")
            return EMPTY_VALUE_LABEL if power is None else str(power)
        if column == COL_TOUGHNESS:
            toughness = card.get("toughness")
            return EMPTY_VALUE_LABEL if toughness is None else str(toughness)
        if column == COL_PRICE:
            # Formatted the same way it's DISPLAYED (respecting whichever
            # price source is currently active) -- a checklist of raw
            # floats would show duplicates like 3.5 vs "3.50" side by side.
            return f"${card.get(self.price_source, 0):.2f}"
        return None

    def _passes_filters(self, card):
        for column, excluded in self._column_filters.items():
            if not excluded:
                continue
            if self._raw_filter_value(card, column) in excluded:
                return False
        card_colors = card.get("colors", [])
        # Colorless cards (card_colors == []) never intersect ANY excluded
        # set, so they're structurally exempt here too -- same principle as
        # the checklist never offering a "Colorless" checkbox in the first
        # place: colorless just isn't part of this filtering dimension at all.
        if self.mana_excluded_colors and any(c in self.mana_excluded_colors for c in card_colors):
            return False
        if self.mana_mono_only and len(card_colors) != 1:
            return False
        return True

    def set_mana_mono_only(self, value):
        self.mana_mono_only = value
        self._commit_reorder()

    def set_mana_color_excluded(self, color_letter, excluded):
        if excluded:
            self.mana_excluded_colors.add(color_letter)
        else:
            self.mana_excluded_colors.discard(color_letter)
        self._commit_reorder()

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


class _MenuSearchBox(QLineEdit):
    """
    The Excel-style "narrow the checklist" search box embedded in a filter
    menu. Three behaviors plain QLineEdit doesn't have:

    1. Up/Down arrow keys move QMenu's visual "active action" highlight
       WITHOUT ever transferring real Qt keyboard focus away from this
       search box. CAUGHT VIA AN APPLICATION-LEVEL eventFilter, not
       keyPressEvent -- QMenu has its own internal arrow-key handling for
       navigating actions (including ones hosted via QWidgetAction), and
       that handling runs as part of Qt's event-filter/notify chain BEFORE
       a focused child widget's own keyPressEvent override ever sees the
       key (Qt delivers to installed event filters first, target's own
       event handling last). A keyPressEvent override here was therefore
       never actually reached -- QMenu's own navigation ate the key first,
       and its own idea of "next item" doesn't account for our
       search-narrowed HIDDEN actions, which is why it looked like nothing
       moved at all. Same root cause, same fix shape, as the Tab-key
       interception documented in collapsible_pane.py's module docstring:
       install the filter at the APPLICATION level so it runs ahead of
       Qt's own internal handling, rather than trying to out-prioritize it
       from inside the widget's own event methods.
       setActiveAction() is a direct, supported API for "highlight exactly
       this action" that doesn't depend on who technically has keyboard
       focus, so keeping focus right here on the search box the entire
       time and driving the highlight manually sidesteps that whole class
       of bug. Only VISIBLE, checkable actions are ever targeted, and
       Up/Down are clamped at the top/bottom (Up when nothing is
       highlighted yet does nothing; Down past the last item does nothing
       further).
    2. Enter applies the typed text as a real filter (excluding every
       offered value that doesn't contain it) and closes the menu --
       a fast path for "I know what I'm looking for" that doesn't require
       manually finding and clicking the matching checkbox.
    3. Distinct focused/unfocused border colors and left-padded
       placeholder text.
    """

    def __init__(self, menu, on_enter=None):
        super().__init__()
        self._menu = menu
        self._on_enter = on_enter
        self.setPlaceholderText("Search values...")
        self.setStyleSheet(
            "QLineEdit { border: 1px solid #6b6f76; border-radius: 3px; "
            "padding: 3px 6px; background-color: #2b2d31; color: #e3e3e3; } "
            "QLineEdit:focus { border: 1px solid #4f8fc0; }"
        )
        # Installed on the APPLICATION, not on self -- this is what makes
        # our handling run before QMenu's own internal arrow-key navigation
        # gets a chance to consume Up/Down first (see class docstring point
        # 1). A fresh _MenuSearchBox is created every time a filter menu is
        # right-clicked into existence (see SplitDropdownHeader._build_
        # context_menu), so the filter is torn down via aboutToHide below --
        # without that, every right-click would leak one more permanent
        # global filter that outlives the menu it was built for.
        QApplication.instance().installEventFilter(self)
        menu.aboutToHide.connect(self._remove_app_filter)

    def _remove_app_filter(self):
        QApplication.instance().removeEventFilter(self)

    def _visible_checkable_actions(self):
        return [a for a in self._menu.actions() if a.isVisible() and a.isCheckable()]

    def _move_highlight(self, direction):
        actions = self._visible_checkable_actions()
        if not actions:
            return
        current = self._menu.activeAction()
        if current in actions:
            index = actions.index(current) + direction
        else:
            # Nothing highlighted yet: Down starts at the first item; Up
            # stays clamped (there's nothing "above" the search box).
            index = 0 if direction > 0 else -1
        if index < 0:
            self._menu.setActiveAction(None)  # back to "nothing highlighted" / clamped top
            return
        index = min(index, len(actions) - 1)  # clamp bottom
        self._menu.setActiveAction(actions[index])
        self._menu.update()  # belt-and-suspenders repaint if setActiveAction doesn't force one

    def eventFilter(self, watched, event):
        # Only ever act on key presses targeted at THIS search box -- the
        # filter is global, so every keypress in the whole application
        # passes through here while this menu is open, and we only care
        # about the tiny slice that's actually ours.
        if watched is self and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Up:
                self._move_highlight(-1)
                return True   # consumed: stop it reaching QMenu's own handling
            if event.key() == Qt.Key_Down:
                self._move_highlight(1)
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if self._on_enter is not None:
                    self._on_enter(self.text())
                self._menu.close()
                return True
        return super().eventFilter(watched, event)



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
        painter.fillRect(rect, QColor(HEADER_BG))
        mid_x = rect.left() + rect.width() // 2

        left_rect = QRect(rect.left(), rect.top(), rect.width() // 2, rect.height())
        right_rect = QRect(mid_x, rect.top(), rect.width() - rect.width() // 2, rect.height())

        # "Ed"/"Rar" are drawn as FIXED strings, always centered in their
        # half regardless of sort state -- appending "▲" directly into the
        # label (the previous approach) changed the string's rendered
        # width, which shifted the CENTERED text sideways every time sort
        # state changed. The arrow is now a separate glyph pinned to a
        # fixed position within each half, so "Ed"/"Rar" never move.
        painter.drawText(left_rect, Qt.AlignCenter, "Ed")
        painter.drawText(right_rect, Qt.AlignCenter, "Rar")
        if self._active_sort_key == "set":
            painter.drawText(left_rect.adjusted(0, 0, -4, 0), Qt.AlignRight | Qt.AlignVCenter, "▲")
        elif self._active_sort_key == "rarity":
            painter.drawText(right_rect.adjusted(0, 0, -4, 0), Qt.AlignRight | Qt.AlignVCenter, "▲")

        painter.setPen(self.palette().mid().color())
        painter.drawLine(mid_x, rect.top() + 4, mid_x, rect.bottom() - 4)
        painter.restore()

    def _paint_section_with_arrow(self, painter, rect, logical_index):
        """
        Centers the label within the FULL section width -- consistent with
        how every other (non-dropdown) header is centered -- rather than
        reserving arrow space and left-aligning within what's left, which
        made the label's position depend on the arrow's presence (and read
        inconsistently against plain headers). The dropdown arrow is drawn
        as a fixed overlay pinned to the right edge; it doesn't factor into
        where the label sits at all. These are short, fixed, known label
        strings ("Type," "Mana Cost," "Price") that never grow at runtime,
        so there's no real risk of the centered text colliding with the
        arrow in practice -- unlike arbitrary user data, eliding isn't
        needed here either.
        """
        painter.save()
        painter.fillRect(rect, QColor(HEADER_BG))

        label = COLUMNS[logical_index][1]
        painter.setPen(self.palette().text().color())
        painter.drawText(rect, Qt.AlignCenter, label)

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
            if column == COL_QTY:
                label = self.model().qty_label
            elif column == COL_CROSS_QTY:
                label = self.model().cross_qty_label
            else:
                label = COLUMNS[column][1] or "this column"
            header_action = menu.addAction(f"Filter by {label}")
            header_action.setEnabled(False)  # acts as a section label, not clickable

            # Mana Cost is special-cased: its checklist ONLY offers the 5
            # mono colors, never "Colorless" or a multicolor combo like
            # "U/B". Colorless and multicolor cards are simply never
            # excludable via these checkboxes at all -- colorless in
            # particular isn't "filtered one way or another," by
            # construction. "Monocolored only" is a SEPARATE, persistent,
            # real toggle (model.mana_mono_only) -- checking it additionally
            # excludes colorless AND multicolor outright; the checkboxes
            # below still narrow WHICH mono colors show, whether or not the
            # toggle is on.
            if column == COL_MANA:
                offered_values = [COLOR_NAMES[c] for c in COLOR_ORDER]  # White, Blue, Black, Red, Green -- WUBRG order
            else:
                offered_values = self.model().distinct_values_for_column(column)

            # Excel-style search box: narrows which checkboxes are VISIBLE
            # as you type (case-insensitive substring match), and Enter
            # applies the typed text as a real filter (see
            # _apply_enter_filter) and closes the menu -- a fast path when
            # you already know what you're looking for.
            search_box = _MenuSearchBox(
                menu, on_enter=lambda text: self._apply_enter_filter(column, offered_values, text)
            )
            search_action = QWidgetAction(menu)
            search_action.setDefaultWidget(search_box)
            menu.addAction(search_action)
            # Auto-focus the search box the instant the menu appears, so
            # you can start typing immediately on right-click without an
            # extra click into the box first.
            menu.aboutToShow.connect(search_box.setFocus)

            mono_action = None
            if column == COL_MANA:
                mono_action = menu.addAction("Monocolored only")
                mono_action.setCheckable(True)
                mono_action.setChecked(self.model().mana_mono_only)
                mono_action.toggled.connect(self.model().set_mana_mono_only)
                menu.addSeparator()

            excluded = self.model()._column_filters.get(column, set())
            excluded_colors = self.model().mana_excluded_colors if column == COL_MANA else None

            value_actions = []
            for value in offered_values:
                action = menu.addAction(value)
                action.setCheckable(True)
                if column == COL_MANA:
                    letter = NAME_TO_COLOR_LETTER[value]
                    action.setChecked(letter not in excluded_colors)
                    action.toggled.connect(
                        lambda checked, l=letter: self.model().set_mana_color_excluded(l, not checked)
                    )
                else:
                    action.setChecked(value not in excluded)
                    action.toggled.connect(
                        lambda checked, v=value, col=column: self._on_filter_toggled(col, v, checked)
                    )
                value_actions.append((value, action))

            def _narrow_checklist(text):
                needle = text.strip().lower()
                for value, action in value_actions:
                    action.setVisible(needle in value.lower())
            search_box.textChanged.connect(_narrow_checklist)

            menu.addSeparator()

        columns_menu = menu.addMenu("Show Columns")
        for index, (_key, label, _kind) in enumerate(COLUMNS):
            if index == COL_QTY:
                display_label = self.model().qty_label
            elif index == COL_CROSS_QTY:
                display_label = self.model().cross_qty_label
            else:
                display_label = label or MENU_COLUMN_LABELS.get(index, f"Column {index}")
            action = columns_menu.addAction(display_label)
            action.setCheckable(True)
            action.setChecked(not self.isSectionHidden(index))
            action.toggled.connect(lambda checked, i=index: self.setSectionHidden(i, not checked))

        return menu

    def _on_filter_toggled(self, column, value, checked):
        # checked=True means "keep this value visible" -- i.e. NOT excluded
        # -- so the boolean passed to set_value_excluded is the inverse of
        # the checkbox's own checked state.
        self.model().set_value_excluded(column, value, excluded=not checked)

    def _apply_enter_filter(self, column, offered_values, text):
        """
        Pressing Enter in a filter menu's search box applies the typed text
        directly as a filter -- every offered value that DOESN'T contain it
        gets excluded -- rather than requiring the user to find and click
        the matching checkbox by hand. Empty text clears the filter entirely.
        """
        text = text.strip().lower()
        if column == COL_MANA:
            for value in offered_values:
                letter = NAME_TO_COLOR_LETTER[value]
                exclude_this = bool(text) and text not in value.lower()
                self.model().set_mana_color_excluded(letter, exclude_this)
        else:
            if not text:
                self.model().set_column_filter(column, set())
            else:
                non_matching = {v for v in offered_values if text not in v.lower()}
                self.model().set_column_filter(column, non_matching)


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

    def __init__(self, cards, qty_label="Qty", cross_qty_label="Cross"):
        super().__init__()
        self.card_model = CardTableModel(cards, qty_label=qty_label, cross_qty_label=cross_qty_label)
        self.setModel(self.card_model)

        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # F2 (EditKeyPressed) only -- NOT DoubleClicked, since double-click
        # already opens the detail popup; making DoubleClicked ALSO an edit
        # trigger would race the two behaviors against each other on the
        # editable Qty column.
        self.setEditTriggers(QAbstractItemView.EditKeyPressed)

        column_keys = {COL_QTY: "qty", COL_CROSS_QTY: "cross_qty", COL_NAME: "name",
                       COL_TYPE: "type_line", COL_MANA: "mana_cost",
                       COL_POWER: "power", COL_TOUGHNESS: "toughness",
                       COL_PRICE: "price"}
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

        # Set by main.py after construction (main.py builds the Tag
        # Database before the tables, but wiring it as a late-bound
        # attribute rather than a constructor arg keeps CardTableView usable
        # in contexts that don't need tagging at all, without an awkward
        # required-but-often-None parameter).
        self.tag_source = None
        self._tag_dialog = None

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            # Deliberately swallowed rather than passed to the default
            # QAbstractItemView handling. Right-clicking a cell that's part
            # of an existing multi-column selection (e.g. Ctrl+clicked
            # across several rows' "Have" cells) was inconsistently
            # dropping that selection depending on which column the
            # right-click landed in -- Qt's own default click handling can
            # still touch the current index / selection state for a
            # right-button press in some configurations. Selection changes
            # on right-click are handled ENTIRELY and deliberately in
            # contextMenuEvent below (Explorer-style: keep the whole
            # selection if the click landed on any already-selected row),
            # so nothing else should be allowed to touch selection first.
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        if not index.isValid() or self.card_model.card_at(index.row()) is None:
            return  # empty area or a group-header row -- nothing to tag
        if self.tag_source is None:
            return  # no Tag Database wired up -- safe no-op

        # Explorer-style selection rule: right-clicking a row that's
        # already part of the current selection keeps the WHOLE selection
        # (so a multi-row selection can be bulk-tagged); right-clicking a
        # row outside the current selection replaces it with just that row.
        selected_rows = {idx.row() for idx in self.selectionModel().selectedIndexes()}
        if index.row() not in selected_rows:
            self.selectionModel().clearSelection()
            self.selectRow(index.row())

        cards = self._get_selected_cards()
        if not cards:
            return
        self._tag_dialog = TagApplyDialog(cards, self.tag_source, parent=self)
        self._tag_dialog.exec()

    def _get_selected_cards(self):
        """Unique card dicts for every row that currently has at least one
        selected cell, skipping group-header rows entirely."""
        rows = sorted({idx.row() for idx in self.selectionModel().selectedIndexes()})
        cards, seen_ids = [], set()
        for row in rows:
            card = self.card_model.card_at(row)
            if card is not None and id(card) not in seen_ids:
                cards.append(card)
                seen_ids.add(id(card))
        return cards

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
        # Opening the detail view should immediately supersede any hover
        # popover that's currently showing OR still waiting out its delay
        # timer -- otherwise the popover can appear moments later, floating
        # on top of the just-opened dialog.
        self._hover_timer.stop()
        self._popover.hide()
        self._hover_index = QModelIndex()
        self._detail_dialog = CardDetailDialog(
            card["name"], collection_card=card, on_applied=self._on_card_applied, parent=self
        )
        self._detail_dialog.show()

    def _on_card_applied(self):
        """
        Called after the detail popup's Apply button writes changes
        (edition/language/condition/foil) directly into the card dict the
        table already holds a reference to. The mutation itself is already
        done by the time this runs -- this just re-runs the sort/group/
        filter pipeline so the table visually reflects it (e.g. a changed
        Edition/Rarity should re-sort if that's the active sort column).
        """
        self.card_model._commit_reorder()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            self._copy_selection_to_clipboard()
            return

        modifiers = event.modifiers()
        key = event.key()

        if key == Qt.Key_Space and modifiers == Qt.ShiftModifier:
            # Excel: Shift+Space selects the entire current row.
            current = self.currentIndex()
            if current.isValid():
                self.selectRow(current.row())
            return

        if key == Qt.Key_Space and modifiers == Qt.ControlModifier:
            # Excel: Ctrl+Space selects the entire current column.
            current = self.currentIndex()
            if current.isValid():
                self.selectColumn(current.column())
            return

        if modifiers == Qt.ControlModifier and key == Qt.Key_Home:
            self.setCurrentIndex(self.card_model.index(0, 0))
            return

        if modifiers == Qt.ControlModifier and key == Qt.Key_End:
            last_row = self.card_model.rowCount() - 1
            last_col = self.card_model.columnCount() - 1
            if last_row >= 0:
                self.setCurrentIndex(self.card_model.index(last_row, last_col))
            return

        if modifiers == (Qt.ControlModifier | Qt.ShiftModifier) and key in (
            Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right
        ):
            self._extend_selection_to_edge(key)
            return

        super().keyPressEvent(event)

    def _extend_selection_to_edge(self, key):
        """
        Excel-familiar Ctrl+Shift+Arrow: extends the selection from the
        current cell toward an edge. SIMPLIFIED compared to real Excel,
        which jumps to the edge of the current contiguous block of
        non-empty cells (requires scanning for the nearest "gap" in the
        data, not implemented here) -- this always jumps straight to the
        table's actual edge (first/last row or column), which is still a
        genuinely useful "select to the end" action even if it doesn't
        replicate Excel's contiguous-block-aware jump precisely.
        """
        current = self.currentIndex()
        if not current.isValid():
            return
        row, col = current.row(), current.column()
        if key == Qt.Key_Up:
            target = self.card_model.index(0, col)
        elif key == Qt.Key_Down:
            target = self.card_model.index(self.card_model.rowCount() - 1, col)
        elif key == Qt.Key_Left:
            target = self.card_model.index(row, 0)
        else:  # Key_Right
            target = self.card_model.index(row, self.card_model.columnCount() - 1)
        self.selectionModel().select(QItemSelection(current, target), QItemSelectionModel.Select)
        # NOT self.setCurrentIndex(target) -- that routes through the
        # view's own selectionCommand() logic, which for a plain
        # setCurrentIndex() call effectively clears and replaces the
        # selection with just the new cell, wiping out the range we just
        # selected above. Moving the current-cell cursor via the selection
        # model directly, with an explicit NoUpdate command, repositions it
        # without touching the selection at all.
        self.selectionModel().setCurrentIndex(target, QItemSelectionModel.NoUpdate)

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
