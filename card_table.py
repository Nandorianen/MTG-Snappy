"""
card_table.py
-------------
The central spreadsheet: a QAbstractTableModel (data) + QTableView (display)
pair, plus custom machinery layered on top:

1. CardTableHeader (QHeaderView subclass) -- draws a small direction-aware
   sort arrow and filter-active dot on every column via paintSection; and
   handles RIGHT-click for a per-column filter, PLUS (for Type/Mana Cost/
   Price specifically) the "Group by Type," "Group by Color," and "Price
   Source" controls that used to live behind a separate dropdown-arrow zone
   in the header itself. Consolidating those into the same right-click menu
   the filter already lives in removed a second, visually near-identical
   arrow glyph that used to sit right next to the sort arrow (see the
   "Type/Mana/Price header cleanup" note below) -- one right-click menu per
   column is simpler to explain than "click here to sort, click 4px to the
   right of that to open a totally different menu." Also builds the "Show
   Columns" visibility-picker menu (build_show_columns_menu below), though
   that's no longer shown FROM the header itself -- see CardDatabaseView's
   standalone Columns button.

   EDITION AND RARITY ARE NOW TWO ORDINARY, INDEPENDENT COLUMNS, not a
   single custom-painted "Edition / Rarity" split column with two
   independently-sortable halves (that design is gone -- see NOTES.md for
   why and for the one thing worth remembering when touching either
   column: a print's rarity is a property OF a specific edition/printing,
   not of the card in the abstract, so any code that reads or changes
   rarity should always be doing so alongside -- and scoped to -- a
   specific edition, never rarity in isolation. card_detail_popup.py's
   edition switcher already gets this right by construction, since
   picking a print there updates edition and rarity together from the
   same print record).

   FILTERS ARE NOW TWO DIFFERENT SHAPES, DEPENDING ON THE COLUMN (see
   NOTES.md's "Filter overhaul" entry for the full reasoning): Type,
   Mana Cost (color), Edition, and Rarity are genuinely bounded, small
   categorical sets, so they keep the checklist-with-search-box UI.
   Have/Want, Power/Toughness, Price, and Name are NOT bounded (an
   unbounded quantity, continuous price, or a free-text name) -- listing
   "every distinct value that currently occurs" doesn't scale and isn't
   useful, so those four instead get a single typed EXPRESSION (see
   EXPRESSION_COLUMNS, CardTableModel._matches_expression): comparison
   operators (>, >=, <, <=, !=) against a number when the typed operand
   parses as one, otherwise a case-insensitive substring/contains match
   (wildcards at both ends, without the user typing them) -- the same
   typed box auto-detects which mode applies per keystroke, rather than
   asking the user to pick a mode or quote text specially.

2. Grouping with sub-headers: when "Group by Type" or "Group by Color" is
   active, the model inserts synthetic full-width HEADER ROWS between
   groups of cards (e.g. a "Creature" bar, then all creatures, then an
   "Instant" bar, etc. -- the Deckbox-style layout). These header rows live
   only in the MODEL's presentation layer (self._display_rows) -- the real
   card data (self._cards) is never contaminated with fake rows.

3. HEADERS ARE NOW FULLY KEYBOARD-FOCUSABLE (this round). A column can hold
   KEYBOARD focus independently of Qt's own real focus -- see
   CardTableHeader._focused_column, focus_column(), activate_column().
   Reachable via Alt+Shift+Up/Down from the table (CardTableView.
   keyPressEvent, jumping from the current cell's column) or Ctrl+Tab from
   CardDatabaseView's meta-button row (landing on the leftmost column).
   Once a column has keyboard focus: Left/Right cycles between columns
   (wrapping, same convention CardDatabaseView's own meta-button row
   arrow-keys already use), Down opens that column's filter/context menu
   (if it has one), Enter/Space sorts by it (the keyboard equivalent of a
   left-click), and Tab/Ctrl+Tab/Shift+Tab hand focus back to the table
   (SAME group-aware landing CardDatabaseView's meta-buttons already use --
   see table_focus_requested). While a menu is open, pressing Up at the
   very top of the checklist (nothing left to highlight) now COLLAPSES the
   menu back to just the header button instead of silently clamping -- see
   _MenuSearchBox._move_highlight's allow_collapse. This is scoped so it
   ONLY changes behavior for keyboard-opened menus; a mouse right-click
   still hands focus back to the TABLE when its menu closes, exactly as
   before -- see _run_context_menu's `keyboard` flag.

WHY THERE'S NO PER-ROW "..." ACTIONS COLUMN ANYMORE:
An earlier version had a rightmost "actions" column (ActionButtonDelegate)
painting a small "..." button per row and reacting to its own click.
Removed: every action behind it (Apply Tags, Add to Deck/Inventory/
Wishlist) is fundamentally a SELECTION-scoped operation -- "do this to
every card I currently have selected," not "do this to the one card I
happened to click a button on." A per-row button was the wrong shape for
that from the start. These now live in the row right-click menu instead
(see CardTableView._show_selection_menu), which already had to compute
"the current selection" for the tag-apply flow -- reused here rather than
adding a second, narrower "just this one row" pathway alongside it.
"""

from PySide6.QtWidgets import (
    QTableView, QHeaderView, QAbstractItemView,
    QApplication, QMenu, QLineEdit, QWidgetAction, QMessageBox,
)
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, Signal, QTimer, QRect, QEvent,
    QItemSelection, QItemSelectionModel,
)
from PySide6.QtGui import QKeySequence, QPainter, QColor, QBrush, QShortcut

from mock_data import RARITY_ORDER, PRICE_SOURCES
from card_popover import CardPopover
from card_detail_popup import CardDetailDialog
from tag_apply_dialog import TagApplyDialog


# --- Column definitions -----------------------------------------------------
# Each entry: (key, header_label, kind)
#   kind "checkbox" -> column 0, native Qt checkbox via CheckStateRole.
#   kind "price"     -> drawn normally in cells, but its HEADER has a dropdown menu.
#   kind "text"      -> plain text, default rendering, default single-column sort.
# Edition and Rarity used to be one custom-painted "split" column (two
# independently-sortable halves in one header section) -- now two ordinary
# columns, each sorted/filtered/resized exactly like any other ("text").
# See NOTES.md for why that design was dropped, and the one thing to
# remember when touching either: rarity is a property of a specific
# PRINTING, not the card in the abstract -- see this module's own
# docstring, "EDITION AND RARITY ARE NOW TWO ORDINARY COLUMNS."
COLUMNS = [
    ("selected", "", "checkbox"),
    ("qty", "Qty", "text"),
    ("cross_qty", "", "text"),  # label is set per-instance -- see CardTableModel.headerData
    ("name", "Name", "text"),
    ("edition", "Edition", "text"),
    ("rarity", "Rarity", "text"),
    ("type_line", "Type", "text"),
    ("mana_cost", "Mana Cost", "text"),
    ("power", "Power", "text"),
    ("toughness", "Toughness", "text"),
    ("price", "Price", "price"),
]
COL_SELECTED = 0
COL_QTY = 1
COL_CROSS_QTY = 2
COL_NAME = 3
COL_EDITION = 4
COL_RARITY = 5
COL_TYPE = 6
COL_MANA = 7
COL_POWER = 8
COL_TOUGHNESS = 9
COL_PRICE = 10

# Small header overlays -- a sort arrow (direction-aware) and a "this
# column has an active filter" dot, added so the header alone tells you
# what's currently sorted/filtered without having to right-click every
# column to check (Excel shows the same two things via its own header
# glyphs). SORT_ARROW_COLOR matches the app's normal text color; the
# filter dot reuses the same gold accent tag_apply_dialog.py already uses
# for "this is actively toggled on" (CHECKED_COLOR there) -- a different
# hue from the blue selection color, so the two kinds of "something is
# active here" don't read as the same signal.
SORT_ARROW_COLOR = "#e3e3e3"
FILTER_DOT_COLOR = "#e6c15c"
FILTER_DOT_SIZE = 6
SORT_ARROW_ZONE_WIDTH = 14

# Ring drawn around whichever column currently holds KEYBOARD focus (see
# CardTableHeader.focus_column/_paint_focus_ring) -- the same accent
# blue used for table-cell selection and every "primary action" button
# elsewhere in the app (CardDatabaseView's toggles, Apply buttons), so
# "this is the keyboard-active thing" reads as one consistent color
# language across the whole app rather than inventing a new hue here.
HEADER_FOCUS_RING_COLOR = "#4f8fc0"

# Every column that has SOME kind of filter control in its right-click
# menu -- both the checklist-style ones (see EXPRESSION_COLUMNS below for
# the other kind) and the expression-box ones. Skipped for the checkbox
# utility column (nothing meaningful to filter by).
FILTERABLE_COLUMNS = {COL_QTY, COL_CROSS_QTY, COL_NAME, COL_EDITION, COL_RARITY, COL_TYPE, COL_MANA, COL_POWER, COL_TOUGHNESS, COL_PRICE}

# Columns whose filter is a typed EXPRESSION (comparison operators against
# a number, or a substring/contains match against text) rather than a
# checklist of every distinct value that currently occurs. These are all
# columns where "every distinct value" is either unbounded (an arbitrary
# Have/Want count, a continuous Price) or just not a useful UI (thousands
# of card Names; Power/Toughness where a checklist of literal numbers
# -- plus "*" for variable P/T -- isn't something a user filters by
# picking from a list). See CardTableModel._matches_expression and
# NOTES.md's "Filter overhaul" entry for the full reasoning. Every OTHER
# filterable column (Type, Mana Cost's color, Edition, Rarity) is a
# genuinely small, bounded category set and keeps the checklist UI.
EXPRESSION_COLUMNS = {COL_QTY, COL_CROSS_QTY, COL_NAME, COL_POWER, COL_TOUGHNESS, COL_PRICE}

# How a missing Power/Toughness (non-creatures have none) is represented in
# the filter checklist. Without this, distinct_values_for_column would just
# never offer a way to filter "show only creatures" / "show only
# non-creatures" at all, since None values would need special-casing
# everywhere they're compared/displayed instead of being a normal string.
EMPTY_VALUE_LABEL = "(none)"

# Menu labels for columns whose header label is blank (currently just the
# checkbox column, since the old blank-labeled "actions" column is gone --
# see the module docstring's "no per-row actions column" note).
MENU_COLUMN_LABELS = {COL_SELECTED: "Checkbox"}

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


def _real_colors(colors):
    """
    Filters a card's raw `colors` list down to genuine WUBRG letters.
    Real Scryfall data never contains anything else, but this app is meant
    to tolerate whatever valid-ish data it's pointed at (see the app's
    offline-first "pick up whatever data the user supplies" priority) --
    a non-color symbol like "X" (generic/variable mana -- conceptually
    the same as any other numeric pip, e.g. the "1" in "{1}{G}") ending
    up in this list should be inert everywhere colors are used for
    categorizing, grouping, or filtering, exactly like a plain number
    already is, rather than crashing a COLOR_NAMES[...] lookup or
    silently counting toward "how many colors does this card have."
    Every call site that reads a card's raw colors for category/rank/
    filter purposes goes through this first.
    """
    return [c for c in colors if c in COLOR_NAMES]


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


def _type_words(type_line):
    """
    Every SUPERTYPE/TYPE word in a type line -- i.e. every word before the
    em dash that introduces subtypes (Scryfall's own convention: e.g.
    "Legendary Creature — Human Soldier" -> {"Legendary", "Creature"}).
    Used for FILTERING, deliberately kept separate from _type_category()
    above, which is used for GROUPING and collapses a type line down to
    ONE bucket (a group needs exactly one; "Artifact Creature" groups
    under "Creature" alone, and a supertype like "Legendary" is stripped
    out entirely so it never becomes its own group). Filtering has the
    opposite need: a card can legitimately match SEVERAL independent type
    words at once ("Legendary Artifact Creature" is truthfully all three),
    and a user filtering by "Artifact" should find "Artifact Creature"
    cards, not just cards whose SOLE category happens to be Artifact. This
    is why COL_TYPE's filter is a set-membership/intersection check
    (mirroring how Mana Cost's own color-exclusion filter already treats
    a multicolor card as matching EVERY color it contains -- see
    mana_excluded_colors) rather than routed through the single-value
    exclusion mechanism every other checklist column uses.

    Splitting on the em dash (rather than reusing TYPE_ORDER/
    SUPERTYPES_TO_STRIP's known-word lists) is deliberate: it makes every
    word Scryfall actually prints before the dash filterable, including
    supertypes (Legendary, Snow, ...) and any type this app doesn't
    already know the name of, rather than only the categories TYPE_ORDER
    happens to enumerate -- consistent with the app's offline-first "pick
    up whatever valid data it's given" priority.
    """
    main_part = type_line.split("\u2014")[0]  # "—", the em dash before subtypes
    return set(main_part.split())


def _color_category(colors):
    colors = _real_colors(colors)
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
    colors = _real_colors(card.get("colors", []))
    if not colors:
        return (0, "")
    if len(colors) == 1:
        return (1 + COLOR_ORDER.index(colors[0]), "")
    ordered = tuple(c for c in COLOR_ORDER if c in colors)
    return (10 + len(colors), ordered)


_COMPARISON_OPERATORS = (">=", "<=", "!=", ">", "<", "=")  # checked longest-first below


def _try_float(value):
    """
    Best-effort numeric parse -- returns None (never 0) for anything that
    isn't a real number, so a non-numeric field (Power/Toughness's "*", a
    blank/missing value) reads as "doesn't participate in a numeric
    comparison" rather than silently coercing to zero and matching things
    it shouldn't.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_filter_expression(text):
    """
    Splits a typed filter-box expression into (operator, operand). A
    leading >=, <=, !=, >, <, or = is recognized (checked longest-first so
    ">=" is never mis-split as ">" + "="); anything else is a bare
    substring/contains search with operator None. The operand's text is
    returned exactly as typed -- numeric-vs-text interpretation happens
    later (see CardTableModel._matches_expression), once the column (and
    therefore what KIND of value it holds) is known.
    """
    text = text.strip()
    if not text:
        return None, ""
    for op in _COMPARISON_OPERATORS:
        if text.startswith(op):
            return op, text[len(op):].strip()
    return None, text


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
        self._column_filters = {}         # {column: set(excluded_value_strings)} -- checklist columns
        self._column_expressions = {}     # {column: typed expression string} -- see EXPRESSION_COLUMNS
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
        # Per-TYPE-WORD exclusion (e.g. {"Artifact", "Legendary"}) -- the
        # exact same "a multi-value field needs set-membership exclusion,
        # not single-value exact-match" reasoning as mana_excluded_colors
        # just above, applied to Type instead of color. See _type_words()
        # for why this can't reuse the generic _column_filters mechanism:
        # "Artifact Creature" needs to match a filter on EITHER "Artifact"
        # OR "Creature" independently, not just whichever single category
        # _type_category() would have collapsed it to for grouping.
        self.type_excluded_words = set()
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

        if role == Qt.TextAlignmentRole and col in (COL_QTY, COL_CROSS_QTY, COL_EDITION, COL_RARITY, COL_MANA, COL_POWER, COL_TOUGHNESS, COL_PRICE):
            return Qt.AlignCenter

        if role == Qt.DisplayRole:
            if col == COL_QTY:
                return str(card.get("qty", ""))
            if col == COL_CROSS_QTY:
                return str(card.get("cross_qty", ""))
            if col == COL_NAME:
                return card["name"]
            if col == COL_EDITION:
                return card["set"].upper()
            if col == COL_RARITY:
                return card["rarity"].capitalize()
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

    def set_column_expression(self, column, text):
        """
        Sets (or, given blank/whitespace-only text, clears) the typed
        filter expression for an EXPRESSION_COLUMNS column -- see
        CardTableModel._matches_expression for how it's evaluated. This is
        a SEPARATE mechanism from the checklist-based set_column_filter/
        set_value_excluded above: a column can only ever be one or the
        other in the UI (see CardTableHeader._build_context_menu), but
        Qty/Cross Qty are a partial exception in the DATA model -- the
        Inventory/Wishlist toggle buttons still drive their own qty=="0"
        exclusion via set_value_excluded regardless, and an expression
        typed here applies ADDITIONALLY on top of that (see
        _passes_filters), not instead of it.
        """
        text = text.strip()
        if text:
            self._column_expressions[column] = text
        else:
            self._column_expressions.pop(column, None)
        self._commit_reorder()

    def get_column_expression(self, column):
        return self._column_expressions.get(column, "")

    def set_type_word_excluded(self, word, excluded):
        """Type's own version of set_mana_color_excluded -- see
        type_excluded_words' own comment in __init__ for why Type needs
        set-membership exclusion instead of the generic single-value
        mechanism."""
        if excluded:
            self.type_excluded_words.add(word)
        else:
            self.type_excluded_words.discard(word)
        self._commit_reorder()

    def distinct_type_words(self):
        """Every type/supertype WORD (see _type_words) that occurs across
        the whole card pool -- the checklist CardTableHeader offers for
        Type's filter menu, e.g. "Artifact", "Creature", "Legendary",
        "Instant", ... one entry per word, not per whole type line."""
        words = set()
        for card in self._source_cards:
            words |= _type_words(card["type_line"])
        return sorted(words)

    def clear_column_filter(self, column):
        """
        Clears every filter currently active on `column` SPECIFICALLY --
        whatever shape that filter happens to take (a checklist exclusion
        set, a typed expression, or Type/Mana's own dedicated word/color
        exclusion sets) -- leaving every OTHER column's filter state
        untouched. This is the single-column counterpart to
        clear_all_filters() below, and the one "Clear Filter" menu action
        (CardTableHeader._build_context_menu) routes through for every
        column uniformly, rather than each column's menu needing its own
        bespoke clear logic.
        """
        changed = False
        if column in self._column_filters:
            del self._column_filters[column]
            changed = True
        if column in self._column_expressions:
            del self._column_expressions[column]
            changed = True
        if column == COL_MANA and (self.mana_excluded_colors or self.mana_mono_only):
            self.mana_excluded_colors = set()
            self.mana_mono_only = False
            changed = True
        if column == COL_TYPE and self.type_excluded_words:
            self.type_excluded_words = set()
            changed = True
        if changed:
            self._commit_reorder()

    def clear_all_filters(self):
        """
        Resets every per-column value-exclusion filter, every typed filter
        EXPRESSION, AND Mana Cost's and Type's own dedicated exclusion-set
        state (mono-only/excluded-colors, excluded type words) back to
        "nothing filtered," in one action -- the single underlying
        operation both CardDatabaseView's "Clear Filters" button and
        CardTableView's Ctrl+Alt+F shortcut call, so the two can never
        drift on what "clear filters" actually resets. Sorting and
        grouping are left untouched -- this only clears FILTERS, matching
        what a "clear filters" action should do rather than also
        rearranging the table.
        """
        if (not self._column_filters and not self._column_expressions
                and not self.mana_mono_only and not self.mana_excluded_colors
                and not self.type_excluded_words):
            return  # already clear -- skip a pointless model reset
        self._column_filters = {}
        self._column_expressions = {}
        self.mana_mono_only = False
        self.mana_excluded_colors = set()
        self.type_excluded_words = set()
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
        if column == COL_EDITION:
            return card["set"].upper()
        if column == COL_RARITY:
            return card["rarity"].capitalize()
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

    def _numeric_value_for_column(self, card, column):
        """
        This card's value for `column` as a float, or None if the column
        isn't numeric for this card -- Power/Toughness's "*" (variable
        P/T), or a column that was never numeric to begin with. See
        _matches_expression, which treats None as "never matches a
        numeric comparison" rather than coercing to 0.
        """
        if column == COL_QTY:
            return _try_float(card.get("qty", 0))
        if column == COL_CROSS_QTY:
            return _try_float(card.get("cross_qty", 0))
        if column == COL_POWER:
            return _try_float(card.get("power"))
        if column == COL_TOUGHNESS:
            return _try_float(card.get("toughness"))
        if column == COL_PRICE:
            return _try_float(card.get(self.price_source, 0))
        return None

    def _matches_expression(self, card, column, expr_text):
        """
        Evaluates one typed EXPRESSION_COLUMNS filter box against a single
        card. Numeric vs. text is decided per-COMPARISON, not per-column:
        if the typed operand parses as a plain number, this compares
        against the column's own NUMERIC reading of the card (see
        _numeric_value_for_column) -- a card that isn't numeric for this
        column (Power's "*") never matches a numeric comparison, rather
        than crashing or silently coercing. Otherwise it falls back to a
        case-insensitive substring match against the column's normal
        filter text (via _raw_filter_value) -- "wildcards at both ends"
        by construction, since a substring check already ignores anything
        before/after the typed text; no quoting needed either way, since
        which mode applies is decided purely by whether the OPERAND
        parses as a number, not by any syntax the user has to remember.
        `!=` in text mode means "does not contain," not "isn't exactly
        equal to" -- exact-match exclusion isn't useful against free text
        like a card name.
        """
        op, operand = _parse_filter_expression(expr_text)
        if op is None and not operand:
            return True  # blank box -- no filter

        numeric_operand = _try_float(operand)
        if numeric_operand is not None:
            value = self._numeric_value_for_column(card, column)
            if value is None:
                return False
            if op in (None, "="):
                return value == numeric_operand
            if op == ">":
                return value > numeric_operand
            if op == ">=":
                return value >= numeric_operand
            if op == "<":
                return value < numeric_operand
            if op == "<=":
                return value <= numeric_operand
            if op == "!=":
                return value != numeric_operand

        # Text mode -- including a comparison operator (">foo") typed
        # against a non-numeric operand, which falls back to a contains
        # check rather than erroring, since there's no other sensible
        # reading of ">foo" against a name.
        text_value = (self._raw_filter_value(card, column) or "").lower()
        needle = operand.lower()
        if op == "!=":
            return needle not in text_value
        return needle in text_value

    def _passes_filters(self, card):
        for column, excluded in self._column_filters.items():
            if not excluded:
                continue
            if self._raw_filter_value(card, column) in excluded:
                return False
        for column, expr_text in self._column_expressions.items():
            if not self._matches_expression(card, column, expr_text):
                return False
        # _real_colors() strips anything that isn't a genuine WUBRG letter
        # (e.g. a stray "X" from generic/variable mana) before either check
        # below -- a card whose only "color" info is really just a generic/X
        # symbol is exactly as colorless as a card whose cost is all plain
        # numbers, and should be exempt from both checks the identical way.
        card_colors = _real_colors(card.get("colors", []))
        # Colorless cards (card_colors == []) never intersect ANY excluded
        # set, so they're structurally exempt here too -- same principle as
        # the checklist never offering a "Colorless" checkbox in the first
        # place: colorless just isn't part of this filtering dimension at all.
        if self.mana_excluded_colors and any(c in self.mana_excluded_colors for c in card_colors):
            return False
        # Colorless is also exempt from "Monocolored only" -- earlier this
        # excluded colorless cards (len == 0 != 1), which is the correct
        # reading of "monocolored" in the abstract, but conflicts with this
        # app's actual rule for colorless/X cards specifically: they're
        # meant to be untouched by ANY mana filter, this one included, not
        # just the per-color checkboxes above. `len(card_colors) not in
        # (0, 1)` -- i.e. still excludes genuine MULTICOLOR cards, just no
        # longer colorless ones.
        if self.mana_mono_only and len(card_colors) not in (0, 1):
            return False
        # Same set-membership exclusion as the mana-color check above,
        # applied to Type instead: a card is excluded if ANY of its own
        # type words (see _type_words) is in the excluded set -- so
        # unchecking "Artifact" hides "Artifact Creature" too, not just
        # cards whose sole category is Artifact.
        if self.type_excluded_words and (_type_words(card["type_line"]) & self.type_excluded_words):
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

        # Only sort if the user has actually picked a sort column. Falling
        # back to "sort by name" here used to be unconditional -- but the
        # table's INITIAL display (built directly in __init__, above) never
        # goes through this method at all, so the very first time
        # _commit_reorder() ran for ANY reason (a filter click, a group-by
        # toggle, or a selection-scoped bulk action like Add to Inventory)
        # would silently jump the table from its original order to
        # alphabetical -- a real, visible "why did that just resort itself"
        # surprise, not something the user asked for. Skipping the sort
        # entirely when _sort_key is None preserves self._source_cards'
        # original order instead, consistent with what's already on screen
        # before anything triggers a reorder.
        if self._sort_key is not None:
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
    The single text box embedded in every column's filter menu -- either
    the Excel-style "narrow the checklist" search box (Type, Mana Cost,
    Edition, Rarity), or the typed comparison/substring EXPRESSION box
    (EXPRESSION_COLUMNS -- Have/Want/Power/Toughness/Price/Name). Both
    shapes share the exact same keyboard-navigation problem (see point 1
    below), so both are built from this one class rather than two nearly-
    identical ones -- the only real difference between them is whether
    `on_enter` narrows/excludes checklist values or sets a typed
    expression, and whether there's a checklist to narrow at all (an
    expression box has no checkable actions, so _navigable_actions()
    naturally returns just whatever's in `extra_navigable_actions` --
    currently always exactly one: "Clear Filter").

    SIX behaviors plain QLineEdit doesn't have:

    1. Up/Down arrow keys move QMenu's visual "active action" highlight
       WITHOUT ever transferring real Qt keyboard focus away from this
       search box. CAUGHT VIA AN APPLICATION-LEVEL eventFilter, not
       keyPressEvent -- QMenu has its own internal arrow-key handling for
       navigating actions (including ones hosted via QWidgetAction), and
       that handling runs as part of Qt's event-filter/notify chain BEFORE
       a focused child widget's own keyPressEvent override ever sees the
       key (Qt delivers to installed event filters first, target's own
       event handling last). A keyPressEvent override here was therefore
       never actually reached -- QMenu's own navigation ate the key first.
       This is also what was BROKEN before this class covered the
       expression box too: a plain QLineEdit with no such interception
       left Down/Up to QMenu's own native handling, which (since nothing
       had ever been "the active action") would jump to the first
       navigable-looking thing it could find -- which could land back on
       the QWidgetAction wrapping the text box ITSELF, reported as
       "pressing Down goes back to the textbox." Routing every text box
       through this one class removes that whole failure mode by
       construction: setActiveAction() is a direct, supported API for
       "highlight exactly this action" that never targets the box itself.
       Install the filter at the APPLICATION level so it runs ahead of
       Qt's own internal handling, same shape as the Tab-key interception
       documented in collapsible_pane.py's module docstring. Only VISIBLE
       actions returned by _navigable_actions() are ever targeted. Up is
       clamped UNLESS `allow_collapse` (see point 4 below); Down past the
       last item does nothing further.
    2. Enter applies the typed text (`on_enter`, meaning differs by
       caller -- see CardTableHeader._build_context_menu and
       _add_expression_filter_controls) and closes the menu -- a fast
       path that doesn't require manually finding and clicking/typing a
       specific control first.
    3. Distinct focused/unfocused border colors and left-padded
       placeholder text (customizable per instance -- an expression box's
       placeholder describes its syntax, a checklist box's just says
       "Search values...").
    4. Pressing Up steps back through the navigable actions one at a
       time, same as always -- but once NOTHING is highlighted (either
       you started there, or a previous Up already stepped back to
       "nothing highlighted"), one MORE Up COLLAPSES the menu entirely --
       see _move_highlight's `allow_collapse` argument. This is what lets
       a keyboard-focused column header (CardTableHeader.focus_column)
       collapse an open menu back down to just itself, one Up press at a
       time from wherever the highlight currently is. Shift+Tab/Backtab
       share the exact same clamping arithmetic but do NOT get this
       treatment, since collapsing the whole menu would be a surprising
       side effect of what's otherwise just navigation there.
    5. Home/End jump straight to the first/last VISIBLE navigable action;
       PageUp/PageDown jump by PAGE_STEP rows at a time, clamped into
       range -- same underlying reason as point 1: QMenu's own native
       handling for these keys would hit the identical "changes state
       that's invisible because real focus never left this search box"
       problem.
    6. Gaining real Qt focus selects all existing text (focusInEvent) --
       so reopening a menu that already has a filter applied lets a
       single keystroke replace it outright, rather than requiring a
       manual select-all or backspacing through it first. Matches the
       same "type immediately overrides" convenience tree_pane.py already
       established for its own rename editor (_SelectAllEditDelegate).

    NAVIGABLE ACTIONS are, by default, every VISIBLE CHECKABLE action in
    the menu (the value checkboxes, plus "Group by Type"/"Monocolored
    only"/etc. where present) -- PLUS anything explicitly registered via
    add_navigable_action(), currently just "Clear Filter" (see
    CardTableHeader._build_context_menu). Clear Filter isn't checkable
    (it's a one-shot action, not a toggle), so it needed explicit
    registration to be reachable at all; Space now triggers WHATEVER
    action is currently highlighted regardless of checkable-ness (see the
    Key_Space handler below), which is what actually activates it once
    reached.
    """

    PAGE_STEP = 10  # rows moved per Page Up/Down press -- filter checklists have no fixed "visible row count" to derive this from, so this is a reasonable fixed jump rather than a computed one

    def __init__(self, menu, on_enter=None, placeholder="Search values...", initial_text=""):
        super().__init__()
        self._menu = menu
        self._on_enter = on_enter
        self._extra_navigable_actions = []  # see add_navigable_action()
        self.setPlaceholderText(placeholder)
        self.setStyleSheet(
            "QLineEdit { border: 1px solid #6b6f76; border-radius: 3px; "
            "padding: 3px 6px; background-color: #2b2d31; color: #e3e3e3; } "
            "QLineEdit:focus { border: 1px solid #4f8fc0; }"
        )
        if initial_text:
            self.setText(initial_text)  # no textChanged listeners yet at this point -- safe, doesn't trigger narrowing prematurely
        # Installed on the APPLICATION, not on self -- this is what makes
        # our handling run before QMenu's own internal arrow-key navigation
        # gets a chance to consume Up/Down first (see class docstring point
        # 1). A fresh _MenuSearchBox is created every time a filter menu is
        # right-clicked into existence (see CardTableHeader._build_
        # context_menu), so the filter is torn down via aboutToHide below --
        # without that, every right-click would leak one more permanent
        # global filter that outlives the menu it was built for.
        QApplication.instance().installEventFilter(self)
        menu.aboutToHide.connect(self._remove_app_filter)
        # Explicit, not left to Qt's own implicit focus-loss handling --
        # see NOTES.md's "menu search box focus leak" entry. Belt-and-
        # suspenders alongside _run_context_menu's new menu.deleteLater():
        # that fixes the underlying leak (old, hidden menus/search boxes
        # piling up forever, parented to the long-lived header); this
        # makes sure THIS box's own blinking caret stops the moment its
        # menu is actually going away, rather than depending on exactly
        # when Qt gets around to processing the deferred deletion.
        menu.aboutToHide.connect(self.clearFocus)

    def add_navigable_action(self, action):
        """Registers a non-checkable action (currently only ever "Clear
        Filter") as a valid Up/Down/Home/End/PageUp/PageDown stop, in
        addition to the menu's own checkable actions -- see class
        docstring's "NAVIGABLE ACTIONS" paragraph. Called once, right
        after the action is created, by whichever caller built it (order
        matters: registering it immediately after creating it is what
        puts it in the right position in _navigable_actions()'s menu-
        order-preserving scan, so it's reached on the very first Down
        press when placed right after the search box, per NOTES.md)."""
        self._extra_navigable_actions.append(action)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()

    def _remove_app_filter(self):
        QApplication.instance().removeEventFilter(self)

    def _navigable_actions(self):
        """Every visible action that arrow-key navigation should be able
        to land on: the menu's own checkable actions (in their real menu
        order), plus anything registered via add_navigable_action() --
        both tested together, in one pass over menu.actions(), so the
        combined list still reflects real menu order (Clear Filter sits
        wherever it was actually placed, not appended at the end)."""
        return [
            a for a in self._menu.actions()
            if a.isVisible() and (a.isCheckable() or a in self._extra_navigable_actions)
        ]

    def _jump_highlight(self, index):
        """
        Highlights the action at `index` DIRECTLY (clamped into
        [0, len-1]) -- shared by Home/End/PageUp/PageDown below, which
        each pick a literal destination rather than stepping one row at a
        time the way _move_highlight's Up/Down do. A no-op with nothing
        navigable (nothing to jump to).
        """
        actions = self._navigable_actions()
        if not actions:
            return
        index = max(0, min(index, len(actions) - 1))
        self._menu.setActiveAction(actions[index])
        self._menu.update()

    def _page_highlight(self, direction):
        """
        PageUp (direction=-1) / PageDown (direction=1): jumps PAGE_STEP
        rows at once from wherever the highlight currently is, clamped at
        both ends by _jump_highlight. Deliberately does NOT share Up's
        two-step "land on nothing-highlighted, then collapse on a second
        press" behavior (_move_highlight) -- Page Up/Down are a bulk-
        scrolling control, not the specific "step back to the search box"
        affordance a single Up press is, so overshooting the top just
        lands on the first item, same as Home would, rather than exiting
        toward the search box or the menu itself.
        """
        actions = self._navigable_actions()
        if not actions:
            return
        current = self._menu.activeAction()
        if current in actions:
            start = actions.index(current)
        elif direction > 0:
            # Nothing highlighted yet (fresh menu, or stepped back up to
            # the search box via a plain Up) -- Page Down starts counting
            # from "one above the first item," same convention plain Down
            # uses in _move_highlight, so a single Page Down still lands
            # PAGE_STEP-1 rows in, not PAGE_STEP+1.
            start = -1
        else:
            return  # Page Up with nothing highlighted: already at the top, nothing to do
        self._jump_highlight(start + direction * self.PAGE_STEP)

    def _move_highlight(self, direction, allow_collapse=False):
        """
        `allow_collapse` only ever matters for direction < 0 (Up), and
        even then only in the "nothing is currently highlighted" case --
        see the two-step design below.

        TWO-STEP UP, deliberately not a direct item-0-to-collapse jump:
        pressing Up while SOME row is highlighted (including the very
        first one) always lands on "nothing highlighted" first -- the
        same state the search box itself represents -- rather than
        collapsing the menu outright. Only a SECOND Up press, pressed
        while ALREADY in that nothing-highlighted state, actually closes
        the menu (allow_collapse's real effect). This matters because
        "nothing highlighted" already IS effectively "back at the search
        box" (real Qt keyboard focus never actually leaves the search box
        the whole time a filter menu is open -- see this class's own
        docstring point 1), so collapsing straight from row 0 skipped
        that intermediate, meaningful stop entirely. Was a real, reported
        bug: pressing Up with any row highlighted closed the whole menu
        instead of stepping back up to "search box active" first. Works
        identically whether the "row" in question is a checklist value or
        the registered Clear Filter action -- both are just entries in
        _navigable_actions() to this method.
        """
        actions = self._navigable_actions()
        if not actions:
            if allow_collapse and direction < 0:
                self._menu.close()
            return
        current = self._menu.activeAction()
        was_highlighted = current in actions
        if not was_highlighted:
            if direction < 0:
                # Already at/above the top (nothing highlighted) -- THIS
                # is the one case Up should collapse, and only when the
                # caller opted in (allow_collapse) -- see class docstring
                # point 4. Reached either by starting here fresh, or by a
                # PRIOR Up press that already stepped back to this state
                # (see the `index < 0` branch below).
                if allow_collapse:
                    self._menu.close()
                else:
                    self._menu.setActiveAction(None)  # stays clamped -- e.g. Shift+Tab's own Up-direction reuse
                return
            index = 0  # Down from nothing highlighted starts at the first item
        else:
            index = actions.index(current) + direction

        if index < 0:
            # Was highlighted on the FIRST item and moved up one more --
            # land back on "nothing highlighted" (the search box) rather
            # than collapsing immediately, regardless of allow_collapse.
            # Collapsing only happens on the NEXT Up press, once this
            # state is what "not was_highlighted" sees above.
            self._menu.setActiveAction(None)
            return
        index = min(index, len(actions) - 1)  # clamp bottom
        self._menu.setActiveAction(actions[index])
        self._menu.update()  # belt-and-suspenders repaint if setActiveAction doesn't force one

    def eventFilter(self, watched, event):
        # Deliberately NOT checking `watched is self` here. That condition
        # holds when an event is manually constructed and sent straight at
        # this widget (e.g. via QApplication.sendEvent(box, ...) in a test),
        # but there's no guarantee it holds for Qt's REAL popup keyboard-grab
        # routing -- a live QMenu grabs the keyboard for the whole
        # application while showing, and which object Qt reports as
        # `watched` for that routed event is an internal implementation
        # detail, not something this code should depend on. Since this
        # filter's entire lifetime is scoped to exactly one popup being open
        # (installed in __init__, torn down via aboutToHide below), and
        # nothing else in the app can legitimately be receiving keyboard
        # input while a popup has the grab, it's safe to react to the KEY
        # CODE alone rather than insisting on a specific receiver identity.
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Up:
                self._move_highlight(-1, allow_collapse=True)
                return True   # consumed: stop it reaching QMenu's own handling
            if event.key() == Qt.Key_Down:
                self._move_highlight(1)
                return True
            if event.key() == Qt.Key_Home:
                self._jump_highlight(0)
                return True
            if event.key() == Qt.Key_End:
                self._jump_highlight(len(self._navigable_actions()) - 1)
                return True
            if event.key() == Qt.Key_PageUp:
                self._page_highlight(-1)
                return True
            if event.key() == Qt.Key_PageDown:
                self._page_highlight(1)
                return True
            if event.key() == Qt.Key_Backtab or (
                event.key() == Qt.Key_Tab and event.modifiers() & Qt.ShiftModifier
            ):
                # Shift+Tab -- Qt reports this as a distinct Key_Backtab on
                # most platforms rather than Key_Tab with ShiftModifier set,
                # so both forms are checked to be safe.
                self._move_highlight(-1)
                return True
            if event.key() == Qt.Key_Tab:
                # Previously unhandled -- fell through to QMenu's own
                # default Tab navigation, which walks EVERY action
                # (including the disabled "Filter by X" header label and
                # the Show Columns submenu trigger), neither of which
                # should ever be a navigable stop. Routing through the
                # same _move_highlight() Up/Down already use fixes this for
                # free: it already filters to _navigable_actions() (see
                # that method), and neither the disabled header label nor
                # a submenu-opening action is checkable or registered, so
                # both are already excluded by the exact logic that's
                # already proven correct for arrow-key nav.
                self._move_highlight(1)
                return True
            if event.key() == Qt.Key_Space:
                # Real QMenu only toggles/activates an action on Space
                # when the MENU ITSELF has actual keyboard focus -- which
                # we deliberately never hand over (focus stays on this
                # search box the whole time, so typing keeps narrowing the
                # list). Without this, Space was always just a literal
                # character typed into the field, never reaching any
                # toggle/trigger logic at all. Triggers WHATEVER is
                # currently highlighted -- a checkable value (toggles it,
                # same as _StayOpenMenu's own click handling) or a
                # registered one-shot action like Clear Filter (runs it) --
                # rather than only checkable ones, so Clear Filter is
                # actually reachable by keyboard once navigated to.
                # Only intercepted once something is actually highlighted
                # (i.e. Up/Down has been pressed at least once) -- before
                # that, Space still types normally, so a multi-word search
                # term like "Lightly Played" isn't broken by this.
                active = self._menu.activeAction()
                if active is not None and (active.isCheckable() or active in self._extra_navigable_actions):
                    active.trigger()
                    return True
                # Nothing highlighted yet -- fall through to normal typing.
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if self._on_enter is not None:
                    self._on_enter(self.text())
                self._menu.close()
                return True
        return super().eventFilter(watched, event)



class CardTableHeader(QHeaderView):
    """
    Custom header handling:
      - Edition/Rarity: painted as two halves, each independently sortable.
      - Every other section: default Qt painting, plus two small overlays
        this class adds -- a direction-aware sort arrow (▲/▼) on whichever
        column is the active sort, and a filter-active dot on whichever
        columns currently have a filter applied. Type/Mana Cost/Price used
        to ALSO reserve a separate dropdown-arrow zone here for "group by"/
        "price source" -- that's gone now (see "Type/Mana/Price header
        cleanup" below); those controls moved into the same right-click
        menu the value-filter checklist already lives in, so clicking
        ANYWHERE in one of these headers just sorts, same as any other
        column, and the arrow zone that used to be reserved for the old
        dropdown is now just more room for the sort arrow.
      - RIGHT-click anywhere: a context menu with a per-column value
        checklist filter (where applicable) -- for Type/Mana Cost/Price
        specifically, also "Group by Type"/"Group by Color"/"Price
        Source" (see _build_context_menu) -- empty (and shown as no menu
        at all) for columns with nothing to filter or configure. Column-
        visibility toggling ("Show Columns") lives in a separate top-level
        button now (CardDatabaseView), not duplicated into every column's
        own menu -- build_show_columns_menu() below still builds that
        menu's contents, just no longer wires it in HERE.
      - A few pixels at each section border are reserved EXCLUSIVELY for
        drag-to-resize, checked first, before any of the above.
      - KEYBOARD FOCUS (this round): a column can hold keyboard focus
        independently of Qt's own real focus (self._focused_column, drawn
        as a ring via _paint_focus_ring) -- see focus_column()/
        activate_column() and keyPressEvent below. This is the part that
        makes right-click menus, sorting, and column visibility all
        reachable without a mouse at all: Alt+Shift+Up/Down from the table
        (CardTableView.keyPressEvent) or Ctrl+Tab from CardDatabaseView's
        meta-button row both land here.

    TYPE/MANA/PRICE HEADER CLEANUP: these three used to paint a SECOND
    small arrow glyph (▾, opening a "group by"/"price source" menu) right
    next to where the sort arrow now lives, and the two looked confusingly
    similar side by side while also being genuinely different affordances
    (sort-on-click vs. open-a-menu). Moving "Group by Type," "Group by
    Color," and "Price Source" into the existing right-click filter menu
    (as ordinary checkable actions / a submenu, alongside the value
    checklist that menu already has) removes that visual clash entirely --
    one menu per column for "everything about how this column is
    filtered/grouped/sourced," one click-anywhere-to-sort behavior for
    every header, no second arrow to explain.

    Reads/writes model state directly via self.model() (Qt wires this up
    automatically once the header is attached to a view via
    setHorizontalHeader()) rather than round-tripping through signals --
    reasonable here since this header is only ever used with CardTableModel.

    WHY RESIZE IS HANDLED MANUALLY RATHER THAN VIA super().mousePressEvent():
    Qt's own QHeaderView normally detects "click near a border" internally
    and starts a resize drag on its own. But since this header already
    intercepts every mousePressEvent to decide between sort / split-sort /
    right-click-filter, and those decisions were being made using OUR OWN
    idea of where the section boundary is, a click near an edge kept
    getting swallowed as "sort this column" before Qt's internal resize
    detection ever got a chance to see it -- which is exactly the bug
    reported ("clicking the border is read as sort"). Rather than hope our
    margin and Qt's internal margin happen to agree, RESIZE_MARGIN below is
    checked FIRST and, when it matches, this class does the entire
    press/move/release resize sequence itself (see mouseMoveEvent /
    mouseReleaseEvent) -- deterministic, and directly testable without
    depending on Qt's internal fuzzy hit-testing.
    """

    sort_requested = Signal(str)
    # Emitted after a sort-click is handled and after a right-click context
    # menu (filter checklist, group-by, price source, ...) closes -- see
    # CardTableView.__init__'s connection to self.setFocus. Without this,
    # clicking a header (to sort) or right-clicking it (to filter) leaves
    # keyboard focus sitting on the header/menu instead of back on the
    # table, so the very next arrow-key press does nothing until the user
    # clicks a cell first -- a real, felt keyboard-flow gap now that the
    # table has this much keyboard support built in elsewhere. STILL used
    # for every MOUSE-driven interaction, unchanged; see _run_context_menu
    # for how the KEYBOARD path differs (it keeps focus on the header
    # column instead -- see table_focus_requested below for how a
    # keyboard-focused header eventually hands off to the table instead).
    focus_requested = Signal()
    # Emitted by a header column that currently holds KEYBOARD focus (see
    # focus_column/keyPressEvent) when Tab/Ctrl+Tab (backward=False) or
    # Shift+Tab/Ctrl+Shift+Tab (backward=True) is pressed -- CardTableView
    # connects this straight to its own focus_table_for_metabutton_tab, the
    # exact same group-aware landing method CardDatabaseView's meta-button
    # row already uses for its own Tab/Shift+Tab. One shared "how Tab
    # arrives at the table from above it" convention, whether that
    # "somewhere above" is the meta-button row or a column header.
    table_focus_requested = Signal(bool)  # True = backward

    RESIZE_MARGIN = 6      # pixels at each section edge reserved purely for resizing
    MIN_SECTION_WIDTH = 24

    def __init__(self, column_keys):
        super().__init__(Qt.Horizontal)
        self.setSectionsClickable(True)
        self._column_keys = column_keys
        self._active_sort_key = None
        self._resizing_column = None
        self._resize_start_x = None

        # --- Keyboard column focus -------------------------------------
        # A QHeaderView defaults to Qt.NoFocus (setFocus() is a no-op
        # without this). Nothing routes ordinary Tab-traversal INTO the
        # header by accident -- the only entry points are the explicit
        # focus_column()/activate_column() calls below, reached from
        # CardTableView (Alt+Shift+Up/Down) or CardDatabaseView (Ctrl+Tab
        # from the meta-button row).
        self.setFocusPolicy(Qt.StrongFocus)
        self._focused_column = None        # int column index, or None -- see focus_column()
        self._keyboard_menu_column = None  # set while a KEYBOARD-opened menu is showing -- see _run_context_menu
        self._suppress_focus_clear = False  # True while a menu we opened is showing -- see focusOutEvent
        # {column: last-typed text} -- a fresh _MenuSearchBox is built
        # from scratch every time a menu opens (see _build_context_menu),
        # so without this its typed text would reset to blank on every
        # reopen. This is UI-only convenience state (what was typed into
        # the NARROW-the-checklist box, which doesn't map onto any real
        # filter value directly for checklist columns) -- EXPRESSION_
        # COLUMNS don't need an entry here at all, since their box is
        # always prefilled straight from the model's own
        # get_column_expression(), which already persists correctly.
        self._search_box_memory = {}

        # Tab/Backtab are caught via an APPLICATION-level event filter
        # (see eventFilter below), NOT keyPressEvent -- this matters, and
        # was a real, reported bug before the switch. QHeaderView is a
        # QAbstractItemView subclass, and Qt's own QWidget::event() tries
        # its OWN internal focusNextPrevChild() handling for a plain,
        # unmodified Tab/Shift+Tab BEFORE this widget's keyPressEvent()
        # ever runs -- but that internal handling is explicitly SKIPPED
        # for Ctrl/Alt-modified keys, which is exactly why Ctrl+Tab always
        # worked correctly here while plain Tab/Shift+Tab left the header
        # in an inconsistent focus state (the cell selection moved, but
        # real Qt focus and the header's own ring stayed put). Same
        # general class of "Qt's internal Tab handling doesn't reliably
        # defer to widget-level key logic" issue already documented (and
        # fixed the identical way -- an app-level filter installed ahead
        # of Qt's own routing) in collapsible_pane.py's module docstring
        # and card_database_view.py's meta-button event filter. Installed
        # once here, for this header's whole lifetime (same as those two
        # examples), rather than scoped to a single transient popup the
        # way _MenuSearchBox's own filter is.
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        """
        Catches Tab/Backtab (any modifier combination) aimed at THIS
        header, while it holds keyboard focus, before Qt's own internal
        per-widget Tab handling gets a chance to act on it -- see the
        app-level installEventFilter call in __init__ for why this has to
        happen at the filter stage rather than inside keyPressEvent.
        Every other key (Left/Right/Down/Enter/Space) is still handled
        entirely inside keyPressEvent below, since none of those are
        subject to Qt's own special-cased Tab/Backtab interception --
        only Tab/Backtab needed to move here.
        """
        if (self._focused_column is not None and watched is self
                and event.type() == QEvent.KeyPress):
            key = event.key()
            mods = event.modifiers()
            if key == Qt.Key_Backtab or (key == Qt.Key_Tab and mods & Qt.ShiftModifier):
                self._release_focus_to_table(backward=True)
                return True
            if key == Qt.Key_Tab:
                self._release_focus_to_table(backward=False)
                return True
        return super().eventFilter(watched, event)

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int):
        # Every column now gets plain Qt default section painting (colors
        # via main.py's QSS) plus this class's own overlays -- a sort
        # arrow, a filter-active dot, a keyboard-focus ring. Edition and
        # Rarity used to be one custom-painted "split" section here; now
        # they're ordinary columns like any other, so there's nothing left
        # to special-case in this method.
        super().paintSection(painter, rect, logical_index)
        # `is not None` matters here, not just style: _column_keys has
        # no entry at all for the checkbox column, so dict.get() returns
        # None for it -- comparing that directly against a genuinely-unset
        # _active_sort_key (also None) used to be True, painting a stray
        # sort arrow on it at startup before anything had ever been sorted.
        if self._active_sort_key is not None and self._column_keys.get(logical_index) == self._active_sort_key:
            self._paint_sort_arrow(painter, rect)
        if self._column_has_active_filter(logical_index):
            self._paint_filter_dot(painter, rect)
        if logical_index == self._focused_column:
            self._paint_focus_ring(painter, rect)

    def _sort_arrow_glyph(self):
        model = self.model()
        return "\u25bc" if (model is not None and model._sort_reverse) else "\u25b2"

    def _paint_sort_arrow(self, painter, rect, right_margin=4):
        painter.save()
        painter.setPen(QColor(SORT_ARROW_COLOR))
        arrow_rect = QRect(rect.right() - SORT_ARROW_ZONE_WIDTH - right_margin, rect.top(),
                            SORT_ARROW_ZONE_WIDTH, rect.height())
        painter.drawText(arrow_rect, Qt.AlignCenter, self._sort_arrow_glyph())
        painter.restore()

    def _column_has_active_filter(self, column):
        model = self.model()
        if model is None:
            return False
        if column == COL_MANA:
            return bool(model.mana_excluded_colors) or model.mana_mono_only
        if column == COL_TYPE:
            return bool(model.type_excluded_words)
        if column in EXPRESSION_COLUMNS:
            return bool(model.get_column_expression(column)) or bool(model._column_filters.get(column))
        return bool(model._column_filters.get(column))

    def _paint_filter_dot(self, painter, rect):
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(FILTER_DOT_COLOR))
        painter.drawEllipse(rect.left() + 4, rect.top() + 4, FILTER_DOT_SIZE, FILTER_DOT_SIZE)
        painter.restore()

    def _paint_focus_ring(self, painter, rect):
        """Drawn around whichever column self._focused_column names,
        regardless of whether the header currently holds REAL Qt focus --
        it can legitimately lose that to an open QMenu (a separate
        top-level popup) while still being the logically "active" column;
        see focusOutEvent's _suppress_focus_clear guard."""
        painter.save()
        pen = painter.pen()
        pen.setColor(QColor(HEADER_FOCUS_RING_COLOR))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect.adjusted(1, 1, -2, -2))
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

        # Clicking anywhere in a column's header sorts by it, full stop --
        # Type/Mana Cost/Price used to reserve a right-edge zone here that
        # opened a totally different menu instead (see the class
        # docstring's "Type/Mana/Price header cleanup" note), and Edition/
        # Rarity used to be one section split into two independently-
        # clickable halves -- both gone now; every column behaves
        # identically.
        key = self._column_keys.get(logical_index)
        if key:
            self._apply_sort(key)
            self.focus_requested.emit()
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

    def _apply_sort(self, sort_key):
        """
        Shared by every path that can trigger a sort: a left-click (see
        mousePressEvent) and a keyboard Enter/Space press on a focused
        column (see _trigger_sort_for_focused_column) both funnel through
        here, so the two can never drift on what "sorting this column"
        actually does.
        """
        self._active_sort_key = sort_key
        self.sort_requested.emit(sort_key)
        self.update()

    # --- Right-click: per-column filter + column visibility ------------------
    def _show_context_menu(self, column, global_pos):
        self._run_context_menu(column, global_pos, keyboard=False)

    def _run_context_menu(self, column, global_pos, keyboard):
        """
        Shared by the mouse right-click path (_show_context_menu) and the
        keyboard path (activate_column): builds and runs `column`'s
        context menu, then decides where keyboard focus ends up once it
        closes.

        `keyboard=True` (opened via Alt+Shift+Up/Down from the table, or
        Down on an already-focused header) keeps focus on THIS header
        column afterward -- via focus_column(), re-drawing the same focus
        ring rather than silently losing it -- so Left/Right, Down, Enter,
        and Tab/Ctrl+Tab are all still meaningful the instant the menu
        closes, however it closed (picking a value, Enter, Escape, or the
        new Up-at-the-top collapse -- see _MenuSearchBox._move_highlight's
        allow_collapse).

        `keyboard=False` (mouse right-click) preserves the ORIGINAL,
        already-established behavior unchanged: hand focus back to the
        table via focus_requested, exactly as before headers were
        keyboard-focusable at all -- a mouse user filtering via right-
        click should never suddenly need to Tab back to the table
        afterward.

        self._keyboard_menu_column tracks which column (if any) the
        CURRENTLY open menu was opened for via the keyboard path -- read
        back after menu.exec() returns, since the menu's own Up-collapse
        (_MenuSearchBox) has no direct reference to `keyboard` and closes
        the same way regardless of how the menu was opened; this is what
        lets the SAME close event route differently depending on how the
        menu got there in the first place.
        """
        menu = self._build_context_menu(column)
        # Show Columns used to live here too, so EVERY column's right-click
        # menu had at least one item even when nothing was filterable
        # (Checkbox, Actions). Now that it's a standalone button (see
        # CardDatabaseView), those columns have nothing left to show --
        # better to show no menu at all than an empty popup. Also means
        # Down-to-open on a keyboard-focused Checkbox column is a
        # deliberate no-op -- there's genuinely nothing there to open.
        if menu.isEmpty():
            return
        if keyboard:
            self._keyboard_menu_column = column
        # A QMenu is a separate top-level popup -- showing it genuinely
        # steals real Qt focus away from this header for as long as it's
        # open. Suppressing focusOutEvent's clear here is what keeps the
        # focus ring drawn (self._focused_column untouched) the whole time
        # instead of flickering off and back on around every menu.
        self._suppress_focus_clear = True
        menu.exec(global_pos)
        self._suppress_focus_clear = False
        # `menu` is a local variable, but its Qt PARENT is `self` (this
        # header -- see _StayOpenMenu(self) in _build_context_menu), which
        # outlives every menu built from it. Without an explicit teardown,
        # every right-click/keyboard-open left one more hidden, never-
        # deleted QMenu (and its embedded search/expression box) parented
        # to the header -- harmless functionally, but see NOTES.md's "menu
        # search box focus leak" entry for why this was also the likely
        # cause of a real, reported visual bug (a stray blinking cursor in
        # an old, hidden search box). deleteLater() is safe here even
        # though `column`'s own bookkeeping below still reads state off
        # `menu` first -- deletion is deferred to the next event-loop
        # pass, not immediate.
        menu.deleteLater()
        # The menu (filter checklist, group-by, price source, ...) just
        # closed, whether via a selection, Enter, Escape/click-away, or
        # the keyboard's own Up-collapse.
        if self._keyboard_menu_column == column:
            self._keyboard_menu_column = None
            self.focus_column(column)
        else:
            self.focus_requested.emit()

    def _build_context_menu(self, column):
        menu = _StayOpenMenu(self)

        if column not in FILTERABLE_COLUMNS:
            return menu

        if column == COL_QTY:
            label = self.model().qty_label
        elif column == COL_CROSS_QTY:
            label = self.model().cross_qty_label
        else:
            label = COLUMNS[column][1] or "this column"
        header_action = menu.addAction(f"Filter by {label}")
        header_action.setEnabled(False)  # acts as a section label, not clickable

        # Price Source lives here regardless of which filter UI this
        # column gets below it -- it's a display/grouping choice ("which
        # price column am I even looking at"), not a filter itself, so it
        # applies whether Price ends up with a checklist or an expression
        # box. A plain (non-stay-open) submenu -- picking a source is a
        # one-shot "choose exactly one" action, so closing on selection is
        # correct here, unlike the stay-open filter controls below it.
        if column == COL_PRICE:
            price_menu = menu.addMenu("Price Source")
            for source_key, source_label in PRICE_SOURCES:
                price_action = price_menu.addAction(source_label)
                price_action.setCheckable(True)
                price_action.setChecked(self.model().price_source == source_key)
                price_action.triggered.connect(
                    lambda checked=False, k=source_key: self.model().set_price_source(k)
                )
            menu.addSeparator()

        # EXPRESSION_COLUMNS (Have/Want/Power/Toughness/Price/Name) get a
        # single typed expression box instead of a value checklist -- see
        # this class's own docstring and NOTES.md's "Filter overhaul"
        # entry for why a checklist doesn't scale for these.
        if column in EXPRESSION_COLUMNS:
            self._add_expression_filter_controls(menu, column)
            return menu

        # Everything below is the checklist UI, still used for the
        # genuinely bounded categorical columns: Type, Mana Cost's color,
        # Edition, Rarity.

        # Mana Cost is special-cased: its checklist ONLY offers the 5 mono
        # colors, never "Colorless" or a multicolor combo like "U/B".
        # Colorless and multicolor cards are simply never excludable via
        # these checkboxes at all -- colorless in particular isn't
        # "filtered one way or another," by construction. "Monocolored
        # only" is a SEPARATE, persistent, real toggle
        # (model.mana_mono_only) -- checking it additionally excludes
        # colorless AND multicolor outright; the checkboxes below still
        # narrow WHICH mono colors show, whether or not the toggle is on.
        # Type is ALSO special-cased now, for the analogous reason -- see
        # _type_words()/type_excluded_words: it offers every distinct
        # type/supertype WORD across the card pool (Artifact, Creature,
        # Legendary, ...), not one mutually-exclusive category per card,
        # so a card containing SEVERAL of those words can be excluded by
        # any one of them independently.
        if column == COL_MANA:
            offered_values = [COLOR_NAMES[c] for c in COLOR_ORDER]  # White, Blue, Black, Red, Green -- WUBRG order
        elif column == COL_TYPE:
            offered_values = self.model().distinct_type_words()
        else:
            offered_values = self.model().distinct_values_for_column(column)

        # Excel-style search box: narrows which checkboxes are VISIBLE
        # as you type (case-insensitive substring match), and Enter
        # applies the typed text as a real filter (see
        # _apply_enter_filter) and closes the menu -- a fast path when
        # you already know what you're looking for. Prefilled with
        # whatever was last typed here (see self._search_box_memory --
        # this box is rebuilt from scratch every time the menu opens, so
        # without remembering it the narrowing text would reset to blank
        # on every reopen, unlike the expression box below, which is
        # already prefilled straight from real filter state).
        search_box = _MenuSearchBox(
            menu, on_enter=lambda text: self._apply_enter_filter(column, offered_values, text),
            initial_text=self._search_box_memory.get(column, ""),
        )
        search_action = QWidgetAction(menu)
        search_action.setDefaultWidget(search_box)
        menu.addAction(search_action)
        # Auto-focus the search box the instant the menu appears, so
        # you can start typing immediately on right-click without an
        # extra click into the box first -- also what satisfies "focus
        # on the dropdown menu and arrow controls" for the KEYBOARD
        # entry path (activate_column), since it's the same menu.
        menu.aboutToShow.connect(search_box.setFocus)

        # "Clear Filter" -- right below the search box for every checklist
        # column, same position and same one-shot "reset and close" shape
        # the expression box's own Clear Filter already has (see
        # _add_expression_filter_controls). Registered as a navigable
        # action (see _MenuSearchBox.add_navigable_action) so it's the
        # very first thing a Down press from the search box reaches.
        clear_action = menu.addAction("Clear Filter")
        clear_action.triggered.connect(
            lambda: (self.model().clear_column_filter(column), menu.close())
        )
        search_box.add_navigable_action(clear_action)
        menu.addSeparator()

        # "Group by Type"/"Group by Color" -- moved here from a separate
        # dropdown-arrow zone that used to live in the header itself (see
        # the class docstring's "Type/Mana/Price header cleanup" note).
        # Checkable + toggled (not triggered) so it behaves like every
        # other control in this STAY-OPEN menu: click it, see the effect,
        # keep going, rather than the menu snapping shut.
        if column == COL_TYPE:
            group_action = menu.addAction("Group by Type")
            group_action.setCheckable(True)
            group_action.setChecked(self.model().group_by == "type")
            group_action.toggled.connect(lambda checked, m="type": self.model().set_group_by(m))
            menu.addSeparator()

        mono_action = None
        if column == COL_MANA:
            mono_action = menu.addAction("Monocolored only")
            mono_action.setCheckable(True)
            mono_action.setChecked(self.model().mana_mono_only)
            mono_action.toggled.connect(self.model().set_mana_mono_only)
            group_color_action = menu.addAction("Group by Color")
            group_color_action.setCheckable(True)
            group_color_action.setChecked(self.model().group_by == "color")
            group_color_action.toggled.connect(lambda checked, m="color": self.model().set_group_by(m))
            menu.addSeparator()

        excluded = self.model()._column_filters.get(column, set())
        excluded_colors = self.model().mana_excluded_colors if column == COL_MANA else None
        excluded_type_words = self.model().type_excluded_words if column == COL_TYPE else None

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
            elif column == COL_TYPE:
                action.setChecked(value not in excluded_type_words)
                action.toggled.connect(
                    lambda checked, w=value: self.model().set_type_word_excluded(w, not checked)
                )
            else:
                action.setChecked(value not in excluded)
                action.toggled.connect(
                    lambda checked, v=value, col=column: self._on_filter_toggled(col, v, checked)
                )
            value_actions.append((value, action))

        def _narrow_checklist(text):
            self._search_box_memory[column] = text  # remembered for the next time this menu opens
            needle = text.strip().lower()
            for value, action in value_actions:
                action.setVisible(needle in value.lower())
        search_box.textChanged.connect(_narrow_checklist)
        if search_box.text():
            _narrow_checklist(search_box.text())  # apply the restored text's narrowing immediately, not just on the next keystroke

        return menu

    def _add_expression_filter_controls(self, menu, column):
        """
        Expression-based filter entry for EXPRESSION_COLUMNS -- built on
        the same _MenuSearchBox every checklist column's search box uses,
        even though there's no checklist here to narrow. This matters, not
        just for consistency: without it, Up/Down/Space had no interception
        at all, so they fell through to QMenu's own native handling, which
        (since nothing had ever been "the active action") could jump
        straight back to the QWidgetAction wrapping this very box --
        visible as "pressing Down focuses the textbox again." Reusing
        _MenuSearchBox removes that failure mode by construction (see its
        class docstring, point 1) and gives this box the same select-all-
        on-focus and Up-collapses-the-menu behavior every other filter box
        already has, for free.

        Prefilled with whatever expression is already active on this
        column (`initial_text` -- unlike the checklist boxes' own
        narrowing text, this already comes straight from real, persisted
        filter state via get_column_expression(), so it was never lost on
        reopen even before this round's fixes). Enter applies the typed
        text (CardTableModel.set_column_expression parses it -- see that
        method and _matches_expression for the actual >, >=, <, <=, != /
        substring syntax) and closes the menu. "Clear Filter" -- right
        below the box, registered as a navigable action the same way the
        checklist columns' own Clear Filter is -- empties it in one step.
        """
        expr_box = _MenuSearchBox(
            menu,
            on_enter=lambda text: self.model().set_column_expression(column, text),
            placeholder="e.g. >10, <=3.2, !=sliver, partial name",
            initial_text=self.model().get_column_expression(column),
        )
        action = QWidgetAction(menu)
        action.setDefaultWidget(expr_box)
        menu.addAction(action)
        menu.aboutToShow.connect(expr_box.setFocus)

        clear_action = menu.addAction("Clear Filter")
        clear_action.triggered.connect(
            lambda: (self.model().clear_column_filter(column), menu.close())
        )
        expr_box.add_navigable_action(clear_action)

    def build_show_columns_menu(self):
        """
        Standalone "Show Columns" visibility-toggle menu -- pulled out of
        _build_context_menu (where it used to be rebuilt IDENTICALLY inside
        every single column's right-click menu, the exact same "same lens,
        rebuilt N times" redundancy already resolved elsewhere in this app
        for Inventory/Wishlist/All-Card-Database). Now built exactly once,
        on demand, for the single "Columns" button CardDatabaseView puts in
        its button row alongside Inventory/Wishlist.

        Returns a _StayOpenMenu (not built inline by the caller) so
        toggling several columns' visibility in one sitting doesn't require
        reopening the menu between each click -- same stay-open behavior
        the per-column value checklists already have.
        """
        menu = _StayOpenMenu(self)
        for index, (_key, label, _kind) in enumerate(COLUMNS):
            if index == COL_QTY:
                display_label = self.model().qty_label
            elif index == COL_CROSS_QTY:
                display_label = self.model().cross_qty_label
            else:
                display_label = label or MENU_COLUMN_LABELS.get(index, f"Column {index}")
            action = menu.addAction(display_label)
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
        elif column == COL_TYPE:
            for value in offered_values:
                exclude_this = bool(text) and text not in value.lower()
                self.model().set_type_word_excluded(value, exclude_this)
        else:
            if not text:
                self.model().set_column_filter(column, set())
            else:
                non_matching = {v for v in offered_values if text not in v.lower()}
                self.model().set_column_filter(column, non_matching)

    # --- Keyboard column focus ------------------------------------------
    def focus_column(self, column):
        """
        Gives the header itself real keyboard focus and marks `column` as
        the keyboard-active one (drawn with a focus ring -- see
        _paint_focus_ring, called from paintSection). Focus-ONLY: doesn't
        open anything. See activate_column for the "also open its filter
        menu" variant used when ARRIVING at a header fresh (Alt+Shift+
        Up/Down from the table), or Down on an already-focused header
        (_open_menu_for_focused_column) -- also what a menu's own
        Up-collapse (_MenuSearchBox) returns to via _run_context_menu.
        """
        self._focused_column = column
        self.setFocus(Qt.ShortcutFocusReason)
        self.update()

    def activate_column(self, column):
        """
        focus_column() plus immediately opening that column's filter/
        context menu, if it has one -- what CardTableView's Alt+Shift+
        Up/Down (arriving fresh from the table) and this header's own
        Down key (_open_menu_for_focused_column, once a column already
        has keyboard focus) both do. A column with nothing to filter
        (Checkbox) just gets plain focus -- see _run_context_menu's
        isEmpty() check, the same "no menu at all" rule right-click
        already follows.
        """
        self.focus_column(column)
        section_x = self.sectionViewportPosition(column)
        rect = QRect(section_x, 0, self.sectionSize(column), self.height())
        self._run_context_menu(column, self.mapToGlobal(rect.bottomLeft()), keyboard=True)

    def _visible_columns(self):
        return [c for c in range(self.count()) if not self.isSectionHidden(c)]

    def _move_focused_column(self, direction):
        """
        Left/Right while a header column has keyboard focus -- steps to
        the adjacent VISIBLE column, WRAPPING at both ends. Wrapping (not
        clamping) deliberately matches CardDatabaseView's own meta-button
        row (_focus_adjacent_metabutton) -- one consistent "arrow keys
        loop over a fixed row of things" convention for both keyboard-
        navigable rows above the table, not two different ones.
        """
        columns = self._visible_columns()
        if self._focused_column not in columns:
            return
        index = columns.index(self._focused_column)
        self.focus_column(columns[(index + direction) % len(columns)])

    def _open_menu_for_focused_column(self):
        if self._focused_column is not None:
            self.activate_column(self._focused_column)

    def _trigger_sort_for_focused_column(self):
        """
        Enter/Return/Space on a keyboard-focused header -- the keyboard
        equivalent of a left-click, so a header is fully operable without
        a mouse, not just filterable. Deliberately does NOT emit
        focus_requested -- unlike a mouse click, this keeps keyboard focus
        right here on the header column, so the next keypress (Left/
        Right, Down, Tab...) still has something to act on.
        """
        column = self._focused_column
        if column is None:
            return
        key = self._column_keys.get(column)
        if key:
            self._apply_sort(key)

    def focusOutEvent(self, event):
        """
        Clears the focus ring when focus genuinely leaves the header --
        e.g. Tab/Ctrl+Tab/Shift+Tab handing off to the table
        (keyPressEvent below), or a plain mouse-driven sort-click's
        focus_requested stealing focus back to the table. Suppressed
        (_suppress_focus_clear) while a menu THIS header opened is
        showing -- see _run_context_menu's comment for why that's a
        genuine, expected, temporary loss of real Qt focus that shouldn't
        be read as "the user navigated away."
        """
        if not self._suppress_focus_clear:
            self._focused_column = None
            self.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        """
        Only meaningful once a column actually holds keyboard focus (see
        focus_column/activate_column -- reached via CardTableView's
        Alt+Shift+Up/Down or CardDatabaseView's Ctrl+Tab from the
        meta-button row). A header that's never been given keyboard focus
        falls straight through to Qt's default QHeaderView handling,
        exactly as before headers were keyboard-focusable at all.

        Tab/Backtab are NOT handled here -- see eventFilter above for why
        they have to be caught a step earlier, before this method ever
        runs for those keys.
        """
        if self._focused_column is None:
            super().keyPressEvent(event)
            return

        key = event.key()

        if key in (Qt.Key_Left, Qt.Key_Right):
            self._move_focused_column(-1 if key == Qt.Key_Left else 1)
            return
        if key == Qt.Key_Down:
            self._open_menu_for_focused_column()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._trigger_sort_for_focused_column()
            return
        super().keyPressEvent(event)

    def _release_focus_to_table(self, backward):
        """
        Explicitly clears THIS header's own keyboard-focus state (the
        ring, self._focused_column) and calls clearFocus() BEFORE
        emitting table_focus_requested -- rather than pressing Tab and
        just trusting an eventual focusOutEvent to notice real Qt focus
        left, the way the rest of this class's focus-loss handling
        normally works.

        WHY THIS EXTRA STEP WAS STILL NEEDED, EVEN AFTER MOVING TAB
        HANDLING TO THE APP-LEVEL FILTER (see eventFilter above, and that
        __init__ comment for the confirmed root cause -- Qt's own
        QWidget::event() runs focusNextPrevChild() for a plain Tab/
        Shift+Tab BEFORE keyPressEvent, but explicitly skips that for
        Ctrl/Alt-modified keys, which is why Ctrl+Tab always worked and
        plain Tab didn't): catching the key earlier stops Qt's internal
        handling from running AT ALL, but doesn't by itself guarantee
        THIS widget hands off its own focus state cleanly -- doing that
        explicitly here, before the connected slot's own setFocus() call
        on the table, removes any remaining ambiguity about which side
        "wins" the real Qt focus. Clearing state HERE, directly and
        unconditionally, removes any dependency on exactly how/when Qt's
        own internal handling processes the same
        keypress -- the header relinquishes itself deterministically
        before the table ever tries to claim focus, rather than the two
        racing.
        """
        self._focused_column = None
        self._suppress_focus_clear = False  # no menu is open at this point; nothing to protect
        self.clearFocus()
        self.update()
        self.table_focus_requested.emit(backward)


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
                       COL_EDITION: "set", COL_RARITY: "rarity",
                       COL_TYPE: "type_line", COL_MANA: "mana_cost",
                       COL_POWER: "power", COL_TOUGHNESS: "toughness",
                       COL_PRICE: "price"}
        self.header = CardTableHeader(column_keys)
        self.setHorizontalHeader(self.header)
        self.header.sort_requested.connect(self.card_model.sort_by_key)
        # See CardTableHeader.focus_requested's own comment -- returns
        # keyboard focus to the table after a MOUSE-driven sort-click or
        # right-click menu (filter checklist, group-by, price source)
        # closes.
        self.header.focus_requested.connect(self.setFocus)
        # A header column that itself holds KEYBOARD focus hands off to
        # the table the same group-aware way CardDatabaseView's own
        # meta-button row already does (Tab/Ctrl+Tab forward, Shift+Tab
        # backward) -- see CardTableHeader.keyPressEvent and this
        # method's own docstring below. One shared "how Tab arrives at
        # the table from above it" convention for both entry points.
        self.header.table_focus_requested.connect(self.focus_table_for_metabutton_tab)
        # Price-source selection now lives inside the header's own
        # right-click filter menu (CardTableHeader._build_context_menu)
        # rather than a separate dropdown -- no signal to wire up here
        # anymore, see that method's "Price Source" submenu.
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
        # A model reset ALSO unconditionally clears Qt's selection model
        # (beginResetModel/endResetModel does this regardless of what
        # triggered it), leaving currentIndex() invalid until something
        # re-selects a real cell. Left alone, that showed up as two
        # separate symptoms: nothing visibly looked selected after a
        # filter/sort/group-by change, and keyboard paths that need a REAL
        # current cell to know where to move FROM (Ctrl+Tab's group-jump,
        # Tab/Shift+Tab landing correctly when arriving from
        # CardDatabaseView's meta-button row) silently did nothing or fell
        # through to Qt's own default focus-chain instead. See
        # _select_default_cell_if_unselected's own docstring for why this
        # is safe to run unconditionally on every reset.
        self.card_model.modelReset.connect(self._select_default_cell_if_unselected)

        self.horizontalHeader().setStretchLastSection(False)
        self.setColumnWidth(COL_SELECTED, 28)
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

        # The fixed corner a Ctrl+Shift+Arrow/Home/End chain extends FROM --
        # see keyPressEvent's anchor-tracking comment and _extend_selection_to
        # for why this has to be tracked explicitly rather than re-derived
        # from currentIndex() each time.
        self._selection_anchor = QModelIndex()

        clear_filters_shortcut = QShortcut(QKeySequence("Ctrl+Alt+F"), self)
        clear_filters_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        clear_filters_shortcut.activated.connect(self.card_model.clear_all_filters)
        self._clear_filters_shortcut = clear_filters_shortcut  # keep alive

        # Default hotkeys for the four real bulk actions in the row
        # right-click menu (see _show_selection_menu) -- each operates on
        # WHATEVER's currently selected, evaluated fresh at press-time via
        # _get_selected_cards(), same as the menu items do. The still-TODO
        # "Filter by ..." items in that same menu deliberately get NO
        # default hotkey here -- see _show_selection_menu's comment for why.
        selection_action_bindings = [
            ("Alt+A", lambda: self._apply_tags_to(self._get_selected_cards())),
            ("Alt+D", lambda: self._add_to_deck(self._get_selected_cards())),
            ("Alt+E", lambda: self._add_to_inventory(self._get_selected_cards())),
            ("Alt+W", lambda: self._add_to_wishlist(self._get_selected_cards())),
        ]
        self._selection_action_shortcuts = []  # keep alive
        for sequence, slot in selection_action_bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
            self._selection_action_shortcuts.append(shortcut)

        # The initial table build (CardTableModel.__init__) never goes
        # through _commit_reorder()/modelReset at all (see that method's
        # own comment on why), so the modelReset connection above never
        # fires for the very first render -- call the same fallback
        # directly here too, so a cell is highlighted from the moment the
        # table first appears, not only after the first sort/filter/group
        # change.
        self._select_default_cell_if_unselected()

    def _select_default_cell_if_unselected(self):
        """
        Selects the table's top-left cell IF nothing is currently selected
        -- called once directly at the end of __init__ (first render) and
        on every subsequent modelReset (sort/filter/group-by changes all
        clear the selection outright; see __init__'s comment on why that's
        worth compensating for). A real, visible current cell should
        always exist rather than leaving currentIndex() invalid until the
        user happens to click something.

        Genuinely a no-op whenever something else already restored a real
        selection: _run_preserving_selection's own reselection logic runs
        immediately AFTER the mutation that triggered the modelReset this
        is connected to (i.e. strictly after this method), and
        unconditionally sets whatever selection it's restoring -- silently
        overriding the top-left fallback this picked in the meantime. This
        is purely a safety net for resets that DON'T bring their own
        follow-up selection (a plain sort/filter/group-by toggle).
        """
        if self.selectionModel().currentIndex().isValid():
            return
        target = self._top_left_selectable_index()
        if target is not None:
            self._move_current_clearing_selection(target)

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
        # A plain click (no Shift/Ctrl) starts a brand new selection --
        # this is the moment a future Ctrl+Shift+Arrow/Home/End chain
        # should extend FROM. Shift/Ctrl-modified clicks deliberately
        # don't touch the anchor (Shift-click extends from whatever's
        # already there, same as Excel).
        if event.button() == Qt.LeftButton and event.modifiers() == Qt.NoModifier:
            self._selection_anchor = self.currentIndex()

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        if not index.isValid() or self.card_model.card_at(index.row()) is None:
            return  # empty area or a group-header row -- nothing to act on

        # Explorer-style selection rule: right-clicking a row that's
        # already part of the current selection keeps the WHOLE selection
        # (so a multi-row selection can be bulk-acted-on); right-clicking a
        # row outside the current selection replaces it with just that row.
        selected_rows = {idx.row() for idx in self.selectionModel().selectedIndexes()}
        if index.row() not in selected_rows:
            self.selectionModel().clearSelection()
            self.selectRow(index.row())

        cards = self._get_selected_cards()
        if not cards:
            return
        self._show_selection_menu(cards, event.globalPos())

    def _show_selection_menu(self, cards, global_pos):
        """
        The right-click menu for a row selection. Two batches, separated
        visually: real bulk actions up top (each also bound to a default
        Alt+ hotkey -- see __init__), then a still-TODO batch of "filter by
        this card's ..." shortcuts underneath.

        THE FILTER-BY ITEMS ARE DELIBERATELY DISABLED, NOT HIDDEN OR
        OMITTED: they need the flexible search/filter engine parked in
        NOTES.md ("Flexible search engine") -- there's no per-selection
        query concept yet to hand a "restrict the table to cards matching
        THIS card's Name/Edition/Rarity/Type/Subtype/Color" request to.
        Keeping them visible-but-disabled reserves the menu real estate and
        gives that future feature an obvious, already-agreed-on entry
        point, rather than another "where would this even go" question
        when it gets built. They deliberately get NO default hotkey (unlike
        the four real actions above) -- binding a key to something that
        currently does nothing would just be confusing.
        """
        menu = QMenu(self)

        apply_tags_action = menu.addAction("Apply Tags...\tAlt+A")
        apply_tags_action.setEnabled(self.tag_source is not None)
        apply_tags_action.triggered.connect(lambda: self._apply_tags_to(cards))

        add_deck_action = menu.addAction("Add to Deck...\tAlt+D")
        add_deck_action.triggered.connect(lambda: self._add_to_deck(cards))

        add_inventory_action = menu.addAction("Add to Inventory\tAlt+E")
        add_inventory_action.triggered.connect(lambda: self._add_to_inventory(cards))

        add_wishlist_action = menu.addAction("Add to Wishlist\tAlt+W")
        add_wishlist_action.triggered.connect(lambda: self._add_to_wishlist(cards))

        menu.addSeparator()

        filter_header = menu.addAction("Filter by... (needs search engine)")
        filter_header.setEnabled(False)
        for label in ("Name", "Edition", "Rarity", "Type", "Subtype", "Color"):
            action = menu.addAction(f"    Filter by {label}")
            action.setEnabled(False)

        menu.exec(global_pos)
        # Same reasoning as CardTableHeader.focus_requested elsewhere in
        # this file: a closed popup shouldn't strand keyboard focus on
        # itself -- hand it back to the table so arrow keys work again
        # immediately, without requiring an extra click first.
        self.setFocus()

    def _apply_tags_to(self, cards):
        if self.tag_source is None or not cards:
            return
        self._tag_dialog = TagApplyDialog(cards, self.tag_source, parent=self)
        self._tag_dialog.exec()

    def _add_to_deck(self, cards):
        """
        No real per-deck card storage exists yet -- Deck Viewer's right
        pane is still a placeholder label (see deck_viewer.py) -- so
        there's nothing genuine to add these cards TO. Same honest-stub
        pattern main.py's File > Import/Export actions already use
        (_stub_action) rather than silently doing nothing on click.
        """
        if not cards:
            return
        QMessageBox.information(
            self, "Add to Deck",
            "Deck contents aren't implemented yet -- see NOTES.md's "
            "\u2018Deck contents\u2019 entry.",
        )

    def _add_to_inventory(self, cards):
        self._adjust_qty(cards, "qty")

    def _add_to_wishlist(self, cards):
        self._adjust_qty(cards, "cross_qty")

    def _adjust_qty(self, cards, field, delta=1):
        """
        Bulk-adjusts `field` ("qty" for Have/Inventory, "cross_qty" for
        Want/Wishlist) by `delta` on every card in the selection. Mutates
        the same dict objects the model already holds a reference to --
        same pattern CardDetailDialog._apply_changes uses for its Apply
        button -- then re-runs the model's sort/group/filter pipeline
        exactly ONCE for the whole batch (not once per card), so a
        multi-card selection doesn't trigger a rebuild per row.

        Wrapped in _run_preserving_selection: _commit_reorder() does a
        full model reset, which unconditionally clears Qt's selection --
        without this, bumping Have/Want on a selection would silently
        drop that same selection, which defeats the point of a
        SELECTION-scoped bulk action (you'd want to bump it again, or
        apply a different action to the same cards, right after).
        """
        if not cards:
            return

        def mutate():
            for card in cards:
                card[field] = max(0, card.get(field, 0) + delta)
            self.card_model._commit_reorder()

        self._run_preserving_selection(mutate)

    def _run_preserving_selection(self, mutate_fn):
        """
        Runs `mutate_fn` -- expected to end by calling
        CardTableModel._commit_reorder() -- while preserving which CARDS,
        not which row numbers, end up selected afterward. _commit_reorder()
        always wraps its work in beginResetModel()/endResetModel() (grouping
        can change the row COUNT, not just the order, so a plain
        layoutChanged signal isn't enough -- see that method's own
        docstring), and a full model reset unconditionally clears Qt's
        selection model. Without this, every bulk action that mutates card
        data would silently drop the selection it just acted on.

        Selected CELLS are remembered as (card identity, column) rather
        than (row, column) -- the mutation can re-sort/re-group the table
        (e.g. bumping Have while sorted by Have), so the same card can
        legitimately land on a different row than it started on, even
        though it's still "the same selection" from the user's point of
        view. A card that no longer passes the active filters after the
        mutation (e.g. a filter that excludes its new value) is simply
        dropped from the restored selection -- there's no row left for it
        to occupy.
        """
        selected_cells = [
            (id(self.card_model.card_at(idx.row())), idx.column())
            for idx in self.selectionModel().selectedIndexes()
            if self.card_model.card_at(idx.row()) is not None
        ]

        mutate_fn()

        if not selected_cells:
            return
        row_for_card_id = {
            id(self.card_model.card_at(row)): row
            for row in range(self.card_model.rowCount())
            if self.card_model.card_at(row) is not None
        }
        selection = QItemSelection()
        last_index = None
        for card_id, column in selected_cells:
            row = row_for_card_id.get(card_id)
            if row is None:
                continue  # filtered out by the mutation itself -- nothing to reselect
            index = self.card_model.index(row, column)
            selection.select(index, index)
            last_index = index
        if selection.isEmpty():
            return
        self.selectionModel().select(selection, QItemSelectionModel.ClearAndSelect)
        # Also restores the current/active cell and the Ctrl+Shift+Arrow
        # anchor (see keyPressEvent's anchor-tracking comment) to somewhere
        # inside the restored selection, rather than leaving them pointed
        # at whatever the reset left currentIndex() as (typically invalid).
        self.selectionModel().setCurrentIndex(last_index, QItemSelectionModel.NoUpdate)
        self._selection_anchor = last_index

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

        if key in (Qt.Key_Up, Qt.Key_Down) and modifiers == (Qt.AltModifier | Qt.ShiftModifier):
            # Jump from the current cell's COLUMN into that column's own
            # header and activate it (open its filter menu, if it has
            # one) -- see CardTableHeader.activate_column. Either
            # arrow reaches the SAME header: it sits directly above the
            # table with nothing "further" in either vertical direction
            # from here, so Up and Down are just two equally-sensible ways
            # to ask for it, not two different destinations. Checked
            # first, before the generic arrow-key branches below
            # (including the "nothing selected" one just below, which has
            # no modifier guard at all) so this combo can never be
            # swallowed by them.
            current = self.currentIndex()
            column = current.column() if current.isValid() else 0
            self.header.activate_column(column)
            return

        shift_held = bool(modifiers & Qt.ShiftModifier)
        plain_ctrl = modifiers == Qt.ControlModifier
        ctrl_shift = modifiers == (Qt.ControlModifier | Qt.ShiftModifier)
        arrow_keys = (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right)

        if key in arrow_keys and not self.currentIndex().isValid():
            # Nothing selected at all (fresh table, or a filter/sort reset
            # cleared the selection) -- ANY arrow, whatever modifiers are
            # held, should just plant a single-cell selection at the
            # table's top-left selectable cell, rather than trying to
            # extend-from or edge-jump-from an anchor that was never set.
            target = self._top_left_selectable_index()
            if target is not None:
                self._move_current_clearing_selection(target)
            return

        if key in arrow_keys and modifiers == Qt.NoModifier:
            current = self.currentIndex()
            if self._at_edge_for_key(current, key):
                # Already at the edge in this direction (e.g. current cell
                # is column 0 and Left was pressed again) -- there's
                # nowhere further to move. Rather than silently doing
                # nothing and leaving a stale multi-cell selection (e.g.
                # from an earlier Ctrl+Shift+Arrow) sitting on screen,
                # collapse the selection down to just this one edge cell
                # -- matching Excel's own "one more press at the edge
                # clears the selection" behavior.
                self._move_current_clearing_selection(current)
                return

        if key in (Qt.Key_Up, Qt.Key_Down) and modifiers == Qt.ShiftModifier:
            # Plain Shift+Up/Down (extend by one row, same column) is
            # handled explicitly rather than left to Qt's own native
            # Shift+Arrow extend. Reason: a group-header row is given a
            # full-width setSpan() (see _reapply_group_spans), and Qt's
            # native keyboard-selection-extend doesn't cleanly skip over
            # that span -- crossing one via native Shift+Down was
            # selecting the ENTIRE spanned row on both sides of it (every
            # column, not just the current one), not just the next real
            # card row in the current column. Computing the "next real
            # row" ourselves (skipping any header in between) and
            # extending through the already-span-safe _extend_selection_to
            # (see that method) sidesteps the quirk instead of fighting it.
            target = self._adjacent_selectable_row_target(key)
            if target is not None:
                self._extend_selection_to(target)
            return

        if key == Qt.Key_Space and modifiers == Qt.ShiftModifier:
            # Excel: Shift+Space selects the entire current row.
            current = self.currentIndex()
            if current.isValid():
                self.selectRow(current.row())
            return

        if key == Qt.Key_Space and plain_ctrl:
            # Excel: Ctrl+Space selects the entire current column.
            current = self.currentIndex()
            if current.isValid():
                self.selectColumn(current.column())
            return

        if plain_ctrl and key == Qt.Key_Home:
            self._move_current_clearing_selection(self.card_model.index(0, 0))
            return

        if plain_ctrl and key == Qt.Key_End:
            last_row = self.card_model.rowCount() - 1
            last_col = self.card_model.columnCount() - 1
            if last_row >= 0:
                self._move_current_clearing_selection(self.card_model.index(last_row, last_col))
            return

        if plain_ctrl and key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
            # Excel: Ctrl+Arrow (no Shift) MOVES the current cell to the
            # edge in that direction, collapsing the selection down to
            # just that one cell -- it does NOT extend anything. This is
            # the plain-navigation sibling of Ctrl+Shift+Arrow below;
            # both compute the same edge target (_edge_target_for_key),
            # they just do different things with it once they have it.
            target = self._edge_target_for_key(key)
            if target is not None:
                self._move_current_clearing_selection(target)
            return

        if plain_ctrl and key == Qt.Key_Tab:
            # Real Excel has no behavior bound to Ctrl+Tab at all (it's an
            # OS/application-switcher combo there) -- repurposed here
            # specifically for jumping between group headers when the
            # table is currently grouped, and a deliberate no-op
            # otherwise (see _jump_to_adjacent_group), rather than falling
            # through to Qt's own default Tab-moves-focus-to-next-widget
            # behavior, which would be a confusing surprise mid-table.
            # Wraps back to the first group once past the last one --
            # unlike Page Down below, which clamps -- since Ctrl+Tab reads
            # as "cycle through," the same expectation Ctrl+Tab carries in
            # a browser's own tab strip.
            self._jump_to_adjacent_group(1, wrap=True)
            return

        if modifiers == Qt.NoModifier and key in (Qt.Key_PageUp, Qt.Key_PageDown):
            if self.card_model.group_by:
                # Repurposed the same way Ctrl+Tab is, just clamped
                # (wrap=False) instead of cycling -- Page Up/Down stopping
                # at the first/last group mirrors how it already stops at
                # the table's edge when nothing's grouped (handled by
                # falling through to Qt's own native paging via super()
                # below when this branch doesn't apply).
                self._jump_to_adjacent_group(1 if key == Qt.Key_PageDown else -1, wrap=False)
                return

        if modifiers & Qt.ControlModifier and (
            key == Qt.Key_Backtab or (key == Qt.Key_Tab and shift_held)
        ):
            # Ctrl+Shift+Tab, the reverse of the above -- checked both
            # ways Qt can report it (a distinct Key_Backtab on most
            # platforms, or Key_Tab with ShiftModifier set on others),
            # same belt-and-suspenders reasoning _MenuSearchBox's own
            # Shift+Tab handling already uses elsewhere in this file.
            self._jump_to_adjacent_group(-1, wrap=True)
            return

        if ctrl_shift and key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
            target = self._edge_target_for_key(key)
            if target is not None:
                self._extend_selection_to(target)
            return

        if ctrl_shift and key == Qt.Key_Home:
            self._extend_selection_to(self.card_model.index(0, 0))
            return

        if ctrl_shift and key == Qt.Key_End:
            last_row = self.card_model.rowCount() - 1
            last_col = self.card_model.columnCount() - 1
            if last_row >= 0:
                self._extend_selection_to(self.card_model.index(last_row, last_col))
            return

        super().keyPressEvent(event)

        # ANCHOR TRACKING: any navigation Qt just handled NATIVELY (plain
        # arrows, Home/End, Page Up/Down) without Shift held is where a
        # FUTURE Ctrl+Shift+Arrow/Home/End chain should extend FROM.
        # Deliberately skipped when Shift IS held -- Qt's own native
        # Shift+Arrow extend-selection handling uses its own internal
        # anchor concept, which (since it's never touched here except by
        # a genuine non-shift move) stays implicitly in sync with this
        # one: both always point at "wherever the cursor was the last time
        # a plain, non-extending move happened." That's what lets a mixed
        # chain -- e.g. plain Shift+Right (native Qt), then
        # Ctrl+Shift+Down (ours) -- extend from the SAME original cell
        # instead of the two mechanisms disagreeing about where "the
        # selection started" was. Plain Tab/Backtab are handled ABOVE now
        # (Ctrl+Tab has its own meaning; plain Tab still falls through to
        # Qt's normal cell-to-cell move via super(), so it's still listed
        # here too).
        if not shift_held and key in (
            Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
            Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown,
            Qt.Key_Tab, Qt.Key_Backtab,
        ):
            self._selection_anchor = self.currentIndex()

    def _move_current_clearing_selection(self, target):
        """
        Ctrl+Home/Ctrl+End/plain Ctrl+Arrow: moves the current cell to
        `target` and COLLAPSES the selection down to just that one cell,
        matching Excel. Plain QAbstractItemView.setCurrentIndex() doesn't
        reliably do this -- it can leave the PREVIOUS selection in place
        and just add the new cell to it, which is what made Ctrl+End look
        like it selected "both the current cell and the last cell." Going
        through the selection model directly with an explicit
        ClearAndSelect command is what actually REPLACES the selection
        instead of appending to it.
        """
        self.selectionModel().setCurrentIndex(target, QItemSelectionModel.ClearAndSelect)
        self._selection_anchor = target

    def _extend_selection_to(self, target):
        """
        Shared authority behind every Shift/Ctrl+Shift+... extension:
        selects the rectangle between the fixed ANCHOR cell (see
        keyPressEvent's anchor-tracking comment) and `target`, then moves
        the current/active cell to `target` without disturbing that
        selection. Always a fresh ClearAndSelect over the WHOLE
        anchor-to-target span (never an incremental add onto whatever was
        already selected) -- that's what makes repeated presses always
        show exactly one selection, never a leftover shape from an
        earlier, different extension.

        BUILT AS ONE QItemSelection PER CONTIGUOUS RUN OF REAL (non-header)
        ROWS, not one flat QItemSelection(anchor, target) rectangle --
        this matters whenever the anchor-to-target span crosses a
        group-header row. Group headers get a full-width setSpan() (see
        _reapply_group_spans), and a flat rectangle selection that merely
        PASSES THROUGH a spanned row -- even though that row's own cells
        aren't individually selectable (see CardTableModel.flags()) --
        gets rendered by QTableView as the ENTIRE spanned row selected,
        every column, not just the ones actually being selected. Splitting
        the selection at each header row and skipping it entirely (rather
        than trying to exclude just that one row from a single rectangle,
        which QItemSelection can't express) sidesteps the span quirk
        instead of fighting it. Degrades to exactly the old single-
        rectangle behavior whenever no header row falls in the span (the
        common case, and the only case when nothing's grouped).
        """
        current = self.currentIndex()
        if not current.isValid():
            return
        if not self._selection_anchor.isValid():
            self._selection_anchor = current
        anchor = self._selection_anchor
        top, bottom = sorted((anchor.row(), target.row()))
        left, right = sorted((anchor.column(), target.column()))

        selection = QItemSelection()
        row = top
        while row <= bottom:
            if self.card_model.is_group_header(row):
                row += 1
                continue
            run_start = row
            while row <= bottom and not self.card_model.is_group_header(row):
                row += 1
            selection.select(
                self.card_model.index(run_start, left), self.card_model.index(row - 1, right)
            )
        self.selectionModel().select(selection, QItemSelectionModel.ClearAndSelect)
        # NOT self.setCurrentIndex(target) -- see _move_current_clearing_
        # selection's docstring for why that's unreliable here. NoUpdate
        # repositions the current-cell cursor without touching the
        # selection just set above.
        self.selectionModel().setCurrentIndex(target, QItemSelectionModel.NoUpdate)

    def _group_bounds_for_row(self, row):
        """
        (first_row, last_row) of the group containing `row` -- the range
        of real card rows between the group header immediately above it
        (or the top of the table) and the next group header (or the
        bottom of the table). Returns None if `row` is outside the
        table's actual range (0 <= row < rowCount) -- this is what lets
        _edge_target_for_key ask "is there a group PAST this edge at
        all?" and get a clean, unambiguous "no" instead of a clamped
        in-range guess. When nothing's grouped, every valid row's
        "group" is just the whole table.
        """
        total = self.card_model.rowCount()
        if row < 0 or row >= total:
            return None
        if not self.card_model.group_by:
            return 0, total - 1
        if self.card_model.is_group_header(row):
            # Shouldn't normally happen for the CURRENT cell specifically
            # (header rows are never selectable/current -- see
            # CardTableModel.flags()), but this method is also used to
            # probe rows that are deliberately expected to land ON a
            # header (see _edge_target_for_key's group-hop) -- step past
            # it into the group it introduces rather than assuming.
            row = min(row + 1, total - 1)
        start = row
        while start > 0 and not self.card_model.is_group_header(start - 1):
            start -= 1
        end = row
        while end < total - 1 and not self.card_model.is_group_header(end + 1):
            end += 1
        return start, end

    def _current_group_bounds(self):
        """(first_row, last_row) of the CURRENT cell's group -- see
        _group_bounds_for_row. Falls back to the whole table's row range
        if there's no current cell or the table is empty."""
        current = self.currentIndex()
        row = current.row() if current.isValid() else 0
        bounds = self._group_bounds_for_row(row)
        if bounds is not None:
            return bounds
        total = self.card_model.rowCount()
        return 0, max(total - 1, 0)

    def _adjacent_selectable_row_target(self, key):
        """
        The index one real row away from the current cell in the given
        vertical direction, in the SAME column, skipping over any inert
        group-header row in between (there's at most one between any two
        groups, but this loops just in case more than one ever exists) --
        what a plain Shift+Up/Down should land on (see keyPressEvent).
        Returns None at the table's actual top/bottom edge, where there's
        nothing further to extend to.
        """
        current = self.currentIndex()
        if not current.isValid():
            return None
        row, col = current.row(), current.column()
        step = 1 if key == Qt.Key_Down else -1
        total = self.card_model.rowCount()
        next_row = row + step
        while 0 <= next_row < total and self.card_model.is_group_header(next_row):
            next_row += step
        if not (0 <= next_row < total):
            return None
        return self.card_model.index(next_row, col)

    def _first_selectable_row(self):
        """
        The first row that isn't a synthetic group-header row -- row 0
        when the table isn't grouped (nothing to skip), or the first real
        card row once grouping puts an inert header bar ahead of it. None
        for a genuinely empty table.
        """
        for row in range(self.card_model.rowCount()):
            if not self.card_model.is_group_header(row):
                return row
        return None

    def _top_left_selectable_index(self):
        """
        Row 0/column 0 isn't always a valid target once grouping can place
        an inert header row at the very top of the table -- this is what
        "select the top-left cell" (see keyPressEvent) actually means: the
        first genuinely selectable cell, reading top-to-bottom then
        left-to-right.
        """
        row = self._first_selectable_row()
        return None if row is None else self.card_model.index(row, 0)

    def focus_table_for_metabutton_tab(self, backward=False):
        """
        Called both by CardDatabaseView when Tab/Ctrl+Tab (forward) or
        Shift+Tab (backward) is pressed while focus is on one of the
        meta-buttons above this table (Inventory/Wishlist/Columns/Clear
        Filters -- see that class's eventFilter), AND by this table's own
        header when Tab/Ctrl+Tab/Shift+Tab is pressed while a column has
        keyboard focus (see CardTableHeader.table_focus_requested) --
        one shared "how Tab arrives at the table from somewhere above it"
        convention for both entry points, not two. Rather than leaving
        whatever cell was selected before untouched, this places the
        current cell somewhere that matches which direction focus is
        arriving FROM -- the same "Tab lands on the first thing,
        Shift+Tab lands on the last thing" convention any normal focus
        chain gives you when moving between two widgets:
          - forward (Tab, Ctrl+Tab): the table's first selectable cell
            (top-left, or the first real card row of the first group).
          - backward (Shift+Tab): the first row of the LAST group, when
            the table is currently grouped -- mirrors "the last thing in
            this widget." Falls back to the same top-left cell as the
            forward case when nothing's grouped, since there's no other
            meaningful "last" position to distinguish it from "first"
            without groups to divide the table up.
        """
        target = None
        if backward and self.card_model.group_by:
            starts = self._group_start_rows()
            if starts:
                target = self.card_model.index(starts[-1], 0)
        if target is None:
            target = self._top_left_selectable_index()
        self.setFocus()
        if target is not None:
            self._move_current_clearing_selection(target)

    def focus_leftmost_header(self):
        """
        Jumps keyboard focus from the meta-button row straight into the
        table's HEADER -- its leftmost VISIBLE column -- rather than a
        cell. Called by CardDatabaseView's meta-button row specifically on
        Ctrl+Tab (see that class's eventFilter); plain Tab there still
        lands on a cell via focus_table_for_metabutton_tab, unchanged.
        Focus-ONLY, like CardTableHeader.focus_column -- deliberately
        doesn't open that column's filter menu, since arriving via a
        plain focus hop shouldn't also trigger an action (the same reason
        Tab-ing onto a button focuses it without clicking it).
        """
        columns = [c for c in range(self.card_model.columnCount())
                   if not self.header.isSectionHidden(c)]
        if not columns:
            self.setFocus()
            return
        self.header.focus_column(columns[0])

    def _at_edge_for_key(self, index, key):
        """
        Whether `index` already sits at the table's edge in the direction
        `key` would move -- i.e. a plain, unmodified press of that arrow
        genuinely has nowhere further to go. Used to collapse a leftover
        multi-cell selection down to one cell instead of the press
        silently doing nothing (see keyPressEvent). Deliberately keyed to
        the whole TABLE's edge, not the current group's -- Ctrl+Up/Down
        already has its own group-aware stopping point (see
        _current_group_bounds); a plain arrow reaching the edge of a
        group mid-table should just keep walking into the next group like
        normal row-to-row navigation always has.
        """
        if not index.isValid():
            return False
        if key == Qt.Key_Left:
            return index.column() <= 0
        if key == Qt.Key_Right:
            return index.column() >= self.card_model.columnCount() - 1
        if key == Qt.Key_Up:
            first_row = self._first_selectable_row()
            return first_row is None or index.row() <= first_row
        if key == Qt.Key_Down:
            return index.row() >= self.card_model.rowCount() - 1
        return False

    def _edge_target_for_key(self, key):
        """
        Shared by plain Ctrl+Arrow (moves) and Ctrl+Shift+Arrow (extends):
        the cell reached by moving ONE axis of the CURRENT cell's position
        all the way to an edge in the given direction, leaving the other
        axis untouched. Returns None if there's no current cell to move
        from.

        Left/Right always go to the table's actual first/last column --
        columns aren't grouped, so there's no narrower boundary to respect
        there. Up/Down go through _current_group_bounds() instead of the
        table's absolute first/last row: when the table is grouped, this
        is what stops Ctrl+Up/Down at the edge of the CURRENT group
        (landing on the first/last real CARD row of that group, never the
        inert header row itself) rather than rolling all the way to a
        completely different group. When nothing's grouped,
        _current_group_bounds() just returns the whole table's row range,
        so this is identical to the old always-jump-to-the-table's-edge
        behavior.

        ALREADY AT THAT EDGE -- e.g. Ctrl+Up pressed again while already
        sitting on the current group's own top row: rather than staying
        put (a no-op that made it impossible to reach an ADJACENT group
        with Ctrl+Up/Down at all, short of the wrapping Ctrl+Tab), this
        hops past the (always inert, always immediately-adjacent) header
        row into the neighboring group and lands on ITS far edge -- the
        previous group's bottom row for Ctrl+Up, the next group's top row
        for Ctrl+Down. Repeated presses walk group edge to group edge:
        current-top, previous-bottom, previous-top, before-that-bottom,
        ... A header row always sits exactly one row outside its own
        group's near edge (first_row - 1 for the top, last_row + 1 for
        the bottom), so the ADJACENT group's far edge is exactly two rows
        further out (first_row - 2 / last_row + 2) -- _group_bounds_for_row
        resolves that row's own group boundaries, or returns None if it's
        off the table entirely (already in the first/last group), in
        which case this just clamps at the current edge as before.

        SIMPLIFIED compared to real Excel, which jumps to the edge of the
        current contiguous block of non-empty cells (requires scanning
        for the nearest "gap" in the data -- not implemented here, see
        NOTES.md) -- this jumps to the table's (or current/adjacent
        group's) actual edge, which is still a genuinely useful "go to
        the end" action even if it doesn't replicate Excel's contiguous-
        block-aware jump precisely.
        """
        current = self.currentIndex()
        if not current.isValid():
            return None
        row, col = current.row(), current.column()
        if key in (Qt.Key_Up, Qt.Key_Down):
            first_row, last_row = self._current_group_bounds()
            if key == Qt.Key_Up:
                if row > first_row:
                    row = first_row
                else:
                    adjacent = self._group_bounds_for_row(first_row - 2)
                    row = adjacent[1] if adjacent is not None else first_row
            else:
                if row < last_row:
                    row = last_row
                else:
                    adjacent = self._group_bounds_for_row(last_row + 2)
                    row = adjacent[0] if adjacent is not None else last_row
        elif key == Qt.Key_Left:
            col = 0
        else:  # Key_Right
            col = self.card_model.columnCount() - 1
        return self.card_model.index(row, col)

    def _group_start_rows(self):
        """Row indices of the first real CARD row in every group -- i.e.
        every row that immediately follows a group-header row. Empty when
        the table isn't currently grouped (no header rows exist at all)."""
        total = self.card_model.rowCount()
        return [
            r + 1 for r in range(total)
            if self.card_model.is_group_header(r) and r + 1 < total
            and not self.card_model.is_group_header(r + 1)
        ]

    def _jump_to_adjacent_group(self, direction, wrap=False):
        """
        Ctrl+Tab (direction=1) / Ctrl+Shift+Tab (direction=-1) / Page Down
        (direction=1) / Page Up (direction=-1, both only when grouped):
        moves the current cell to the TOP-LEFT (first row, first column)
        of the next/previous group, and collapses the selection down to
        that one cell -- only meaningful when the table is currently
        grouped (Group by Type/Color, set via a column's own right-click
        menu -- see CardTableHeader._build_context_menu). A deliberate
        no-op when nothing's grouped, rather than falling back to Qt's
        default Tab-moves-focus behavior -- see keyPressEvent's comment
        for why Ctrl+Tab is intercepted unconditionally.

        ALWAYS COLUMN 0, not "whatever column you were already in" (an
        earlier version kept the current column) -- a group jump landing
        at a different column every time depending on where you happened
        to be standing made the destination unpredictable, especially
        landing on some arbitrary column when what you actually wanted was
        "the top of the next group." Column 0 is a fixed, always-visible,
        always-meaningful landing spot regardless of prior position -- the
        same reasoning CardDatabaseView's meta-button row uses when handing
        focus INTO the table via Tab/Shift+Tab/Ctrl+Tab (see
        focus_table_for_metabutton_tab), which this keeps consistent with.

        wrap=True (Ctrl+Tab/Ctrl+Shift+Tab) cycles back to the first/last
        group once past the other end, the same "keep cycling" expectation
        a browser's own Ctrl+Tab carries. wrap=False (Page Up/Down) clamps
        at the ends instead -- a no-op past the first/last group, matching
        how Page Up/Down already stops at the table's edge when nothing's
        grouped rather than wrapping around.
        """
        if not self.card_model.group_by:
            return
        current = self.currentIndex()
        if not current.isValid():
            return
        starts = self._group_start_rows()
        if not starts:
            return
        row = current.row()
        if direction > 0:
            candidates = [r for r in starts if r > row]
            if candidates:
                target_row = candidates[0]
            elif wrap:
                target_row = starts[0]
            else:
                target_row = None
        else:
            candidates = [r for r in starts if r < row]
            if candidates:
                target_row = candidates[-1]
            elif wrap:
                target_row = starts[-1]
            else:
                target_row = None
        if target_row is None:
            return
        self._move_current_clearing_selection(self.card_model.index(target_row, 0))

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
