"""
card_detail_popup.py
---------------------
The double-click detail view: card name, a clickable art placeholder, a row
of fixed-position stats (Type / Mana Cost / Edition / Rarity / Price), oracle
+ flavor text, then three tabs' worth of everything else (the "Card" tab
holds the stuff above; Legality and Rulings are their own tabs).

TWO PIECES OF CUSTOM MACHINERY WORTH CALLING OUT:

1. "FIXED POSITION even if text length changes" -- QLabel doesn't do this on
   its own; by default a longer string just makes the label (and everything
   after it) wider. StatField fixes each stat to a constant pixel width and
   ELIDES (truncates with "…") any text that doesn't fit, using
   QFontMetrics.elidedText(). The full untruncated text is still available
   as a tooltip. This is the standard Qt technique for "same width no matter
   the content."

2. The zoomable/draggable image window is a frameless top-level QWidget.
   Frameless means there's no OS title bar to drag by, so dragging is
   implemented by hand (track the mouse-down offset, move the window on
   mouse-move); "zoom" is implemented by resizing the window itself on
   wheelEvent, since we're drawing a placeholder color rather than a real
   QPixmap that could be scaled more efficiently -- when real card images
   arrive, this'll want to switch to scaling a QPixmap instead of just
   resizing the window, so the image doesn't visibly blur while dragging.
"""

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTabWidget,
    QToolButton, QMenu, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFontMetrics, QColor, QPainter

from mock_data import (
    get_card_by_name, get_card_prints, get_card_legalities, get_card_rulings,
    swatch_for_card, FORMATS, PRICE_SOURCES,
)

LEGALITY_COLORS = {
    "legal": "#4caf50", "not_legal": "#8a8d8f",
    "banned": "#d3202a", "restricted": "#e67e22",
}


class StatField(QWidget):
    """
    One fixed-width labeled stat (e.g. "Type" / "Legendary Creature — ...").
    `clickable=True` swaps the value QLabel for a QToolButton with a popup
    menu -- used for Edition and Price, which need to open a dropdown rather
    than just display text.
    """

    def __init__(self, title, width, clickable=False):
        super().__init__()
        self.setFixedWidth(width)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet("color: #a8adb5; font-size: 10px;")
        layout.addWidget(title_label)

        if clickable:
            self.value_button = QToolButton()
            self.value_button.setPopupMode(QToolButton.InstantPopup)
            self.value_button.setStyleSheet(
                "QToolButton { text-align: left; border: none; font-weight: 600; } "
                "QToolButton::menu-indicator { subcontrol-position: right center; }"
            )
            layout.addWidget(self.value_button)
            self.value_label = None
        else:
            self.value_label = QLabel()
            self.value_label.setStyleSheet("font-weight: 600;")
            layout.addWidget(self.value_label)
            self.value_button = None

    def set_menu(self, menu):
        self.value_button.setMenu(menu)

    def set_text(self, full_text):
        target = self.value_button or self.value_label
        # Elide to fit THIS field's fixed width, regardless of how long the
        # real value is -- this is what keeps every field's on-screen
        # position constant from card to card.
        metrics = QFontMetrics(target.font())
        elided = metrics.elidedText(full_text, Qt.ElideRight, self.width() - 12)
        target.setText(elided)
        target.setToolTip(full_text)  # full value still available on hover


class ClickableArt(QFrame):
    """Placeholder 'art' box. Clicking it opens the standalone zoom window."""
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_color(self, color):
        self.setStyleSheet(f"background-color: {color}; border-radius: 6px;")


class ImageZoomWidget(QWidget):
    """
    A separate, frameless, always-on-top-of-itself window showing the
    (placeholder) art at a user-adjustable zoom, draggable anywhere on
    screen. Closes on right-click or Escape, per spec.
    """

    BASE_SIZE = QSize(300, 420)
    MIN_ZOOM, MAX_ZOOM = 0.3, 4.0

    def __init__(self, color):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self._color = QColor(color)
        self._zoom = 1.0
        self._drag_offset = None
        self.resize(self.BASE_SIZE)
        self.setFocusPolicy(Qt.StrongFocus)  # so keyPressEvent (Escape) actually reaches us

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._color)
        painter.setPen(QColor("#e3e3e3"))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def wheelEvent(self, event):
        factor = 1.1 if event.angleDelta().y() > 0 else (1 / 1.1)
        self._zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom * factor))
        self.resize(int(self.BASE_SIZE.width() * self._zoom),
                    int(self.BASE_SIZE.height() * self._zoom))

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.close()
            return
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class CardDetailDialog(QDialog):
    def __init__(self, card_name, parent=None):
        super().__init__(parent)
        self.oracle = get_card_by_name(card_name)
        self.prints = get_card_prints(card_name)
        self.current_print_index = 0
        self.price_source = PRICE_SOURCES[0][0]
        self._zoom_widget = None  # keep a reference so it isn't garbage-collected while open

        self.setWindowTitle(card_name)
        self.resize(460, 620)

        layout = QVBoxLayout(self)
        name_label = QLabel(card_name)
        name_label.setStyleSheet("font-size: 19px; font-weight: 700;")
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        tabs = QTabWidget()
        layout.addWidget(tabs)
        tabs.addTab(self._build_card_tab(), "Card")
        self.legality_list = QListWidget()
        tabs.addTab(self.legality_list, "Legality")
        self.rulings_list = QListWidget()
        self.rulings_list.setWordWrap(True)
        tabs.addTab(self.rulings_list, "Rulings")

        self._build_edition_menu()
        self._build_price_menu()
        self._refresh_for_current_print()
        self._populate_legality()
        self._populate_rulings()

    def _build_card_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.art_box = ClickableArt()
        self.art_box.setFixedSize(220, 306)
        self.art_box.clicked.connect(self._open_zoom_window)
        layout.addWidget(self.art_box, alignment=Qt.AlignHCenter)

        # Fixed widths per field -- Type gets the most room since type
        # lines run long ("Legendary Creature — Human Soldier"); the others
        # are short and bounded. Order/position never changes card to card.
        stats_row = QHBoxLayout()
        self.type_field = StatField("Type", 170)
        self.mana_field = StatField("Mana Cost", 80)
        self.edition_field = StatField("Edition", 80, clickable=True)
        self.rarity_field = StatField("Rarity", 80)
        self.price_field = StatField("Price", 90, clickable=True)
        for field in (self.type_field, self.mana_field, self.edition_field,
                      self.rarity_field, self.price_field):
            stats_row.addWidget(field)
        stats_row.addStretch()
        layout.addLayout(stats_row)

        self.oracle_text_label = QLabel()
        self.oracle_text_label.setWordWrap(True)
        layout.addWidget(self.oracle_text_label)

        self.flavor_text_label = QLabel()
        self.flavor_text_label.setWordWrap(True)
        self.flavor_text_label.setStyleSheet("color: #a8adb5; font-style: italic;")
        layout.addWidget(self.flavor_text_label)

        layout.addStretch()
        return tab

    def _build_edition_menu(self):
        menu = QMenu(self)
        for i, print_info in enumerate(self.prints):
            action = menu.addAction(f'{print_info["set"].upper()}  ({print_info["rarity"]})')
            action.triggered.connect(lambda checked=False, idx=i: self._select_print(idx))
        self.edition_field.set_menu(menu)

    def _build_price_menu(self):
        menu = QMenu(self)
        for source_key, label in PRICE_SOURCES:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, k=source_key: self._select_price_source(k))
        self.price_field.set_menu(menu)

    def _select_print(self, index):
        self.current_print_index = index
        self._refresh_for_current_print()

    def _select_price_source(self, source_key):
        self.price_source = source_key
        self._refresh_for_current_print()

    def _refresh_for_current_print(self):
        """
        Re-renders everything that depends on which printing is selected:
        edition, rarity, price, flavor text, and (once real images exist)
        the art itself. Oracle-level fields (type, mana cost, oracle text)
        don't change between printings, so they're set from self.oracle,
        not from the print dict.
        """
        print_info = self.prints[self.current_print_index]
        self.type_field.set_text(self.oracle["type_line"])
        self.mana_field.set_text(self.oracle["mana_cost"])
        self.edition_field.set_text(print_info["set"].upper())
        self.rarity_field.set_text(print_info["rarity"].capitalize())
        self.price_field.set_text(f'${print_info.get(self.price_source, 0):.2f}')
        self.oracle_text_label.setText(self.oracle["oracle_text"])
        self.flavor_text_label.setText(print_info.get("flavor_text", ""))
        self.art_box.set_color(swatch_for_card(self.oracle))

    def _populate_legality(self):
        legalities = get_card_legalities(self.oracle["name"])
        for fmt in FORMATS:
            status = legalities.get(fmt, "not_legal")
            item = QListWidgetItem(f'{fmt}:  {status.replace("_", " ").title()}')
            item.setForeground(QColor(LEGALITY_COLORS.get(status, "#e3e3e3")))
            self.legality_list.addItem(item)

    def _populate_rulings(self):
        rulings = get_card_rulings(self.oracle["name"])
        if not rulings:
            self.rulings_list.addItem("No rulings for this card.")
            return
        for ruling in rulings:
            self.rulings_list.addItem(QListWidgetItem(ruling))

    def _open_zoom_window(self):
        color = swatch_for_card(self.oracle)
        self._zoom_widget = ImageZoomWidget(color)
        self._zoom_widget.show()
