"""
card_detail_popup.py
---------------------
The double-click detail view: card name, a clickable art placeholder, two
rows of fixed-position stats (gameplay: Type / Mana Cost -- metadata:
Edition / Rarity / Price), oracle + flavor text, then Legality and Rulings
as side-by-side panes (not tabs) separated by thin vertical rules.

THREE PIECES OF CUSTOM MACHINERY WORTH CALLING OUT:

1. "FIXED POSITION even if text length changes" -- QLabel doesn't do this on
   its own; by default a longer string just makes the label (and everything
   after it) wider. StatField fixes each stat to a constant pixel width and
   ELIDES (truncates with "…") any text that doesn't fit, using
   QFontMetrics.elidedText(). The full untruncated text is still available
   as a tooltip.

2. Panes-not-tabs layout: three widgets in one QHBoxLayout with
   setSpacing(0), each pane separated from its neighbor by a QFrame drawn as
   a vertical line (QFrame.VLine) rather than by layout spacing -- "without
   spaces, but with separators," as specified. Each pane keeps its own
   internal margins so its content doesn't press against the separator.

3. The zoomable/draggable image window is a frameless top-level QWidget.
   Frameless means there's no OS title bar to drag by, so dragging is
   implemented by hand; "zoom" is implemented by resizing the window itself
   on wheelEvent. See NOTES.md for a parked idea about adding reticle-based
   zoom-to-region later.
"""

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
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
    One fixed-width labeled stat. `clickable=True` swaps the value QLabel
    for a QToolButton with a popup menu -- used for Edition and Price.

    The clickable variant reserves extra width for Qt's own menu-indicator
    arrow (drawn automatically by the style for InstantPopup buttons) --
    without that reservation, the elided text is computed as if the full
    field width were available for text, and the arrow ends up drawn
    directly on top of the last few characters.
    """

    ARROW_RESERVE = 16  # px reserved for the QToolButton's native dropdown arrow

    def __init__(self, title, width, clickable=False):
        super().__init__()
        self.setFixedWidth(width)
        self._clickable = clickable
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet("color: #a8adb5; font-size: 10px;")
        layout.addWidget(title_label)

        if clickable:
            self.value_button = QToolButton()
            self.value_button.setPopupMode(QToolButton.InstantPopup)
            # padding-right physically pushes the text away from where the
            # style will paint the arrow, on top of the elide-width fix in
            # set_text() below -- belt and suspenders, since relying on
            # either alone was what let the arrow cover text before.
            self.value_button.setStyleSheet(
                "QToolButton { text-align: left; border: none; font-weight: 600; "
                f"padding-right: {self.ARROW_RESERVE}px; }} "
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
        metrics = QFontMetrics(target.font())
        reserve = self.ARROW_RESERVE if self._clickable else 0
        elided = metrics.elidedText(full_text, Qt.ElideRight, self.width() - 12 - reserve)
        target.setText(elided)
        target.setToolTip(full_text)


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
    screen. Closes on right-click or Escape.
    """

    BASE_SIZE = QSize(300, 420)
    MIN_ZOOM, MAX_ZOOM = 0.3, 4.0

    def __init__(self, color):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self._color = QColor(color)
        self._zoom = 1.0
        self._drag_offset = None
        self.resize(self.BASE_SIZE)
        self.setFocusPolicy(Qt.StrongFocus)

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


def _vline():
    """A thin vertical rule used as a pane separator -- zero layout spacing
    around it, so panes sit directly against the line rather than floating
    in extra whitespace."""
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setStyleSheet("color: #3a3c41;")
    return line


class CardDetailDialog(QDialog):
    def __init__(self, card_name, parent=None):
        super().__init__(parent)
        self.oracle = get_card_by_name(card_name)
        self.prints = get_card_prints(card_name)
        self.current_print_index = 0
        self.price_source = PRICE_SOURCES[0][0]
        self._zoom_widget = None  # keep a reference so it isn't garbage-collected while open

        self.setWindowTitle(card_name)
        self.resize(860, 560)

        outer = QVBoxLayout(self)
        name_label = QLabel(card_name)
        name_label.setStyleSheet("font-size: 19px; font-weight: 700;")
        name_label.setWordWrap(True)
        outer.addWidget(name_label)

        # Three panes side by side, no layout spacing between them -- the
        # separation comes entirely from the vertical-line separators, per
        # spec ("without spaces, but with separators").
        panes_row = QHBoxLayout()
        panes_row.setSpacing(0)
        panes_row.addLayout(self._build_card_pane(), stretch=3)
        panes_row.addWidget(_vline())
        panes_row.addLayout(self._build_legality_pane(), stretch=1)
        panes_row.addWidget(_vline())
        panes_row.addLayout(self._build_rulings_pane(), stretch=2)
        outer.addLayout(panes_row)

        self._build_edition_menu()
        self._build_price_menu()
        self._refresh_for_current_print()
        self._populate_legality()
        self._populate_rulings()

    def _pane_layout(self, title):
        """Shared scaffold for the two side panes: a small header label (the
        job tabs used to do) over a vertical layout with modest margins."""
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 4, 10, 4)
        header = QLabel(title)
        header.setStyleSheet("color: #a8adb5; font-size: 11px; font-weight: 600;")
        layout.addWidget(header)
        return layout

    def _build_card_pane(self):
        layout = self._pane_layout("Card")
        layout.setContentsMargins(4, 4, 10, 4)

        self.art_box = ClickableArt()
        self.art_box.setFixedSize(220, 306)
        self.art_box.clicked.connect(self._open_zoom_window)
        layout.addWidget(self.art_box, alignment=Qt.AlignHCenter)

        # GAMEPLAY row: only Type and Mana Cost -- the two fields that
        # actually matter while playing. Each gets much more breathing room
        # now that it isn't sharing a row with three metadata fields, since
        # type lines ("Legendary Creature — Human Soldier") and some mana
        # costs run long.
        gameplay_row = QHBoxLayout()
        self.type_field = StatField("Type", 280)
        self.mana_field = StatField("Mana Cost", 130)
        gameplay_row.addWidget(self.type_field)
        gameplay_row.addWidget(self.mana_field)
        gameplay_row.addStretch()
        layout.addLayout(gameplay_row)

        # METADATA row: Edition / Rarity / Price -- collection/shopping
        # information, not gameplay information, so it's visually separated
        # onto its own line rather than crowding the row above.
        metadata_row = QHBoxLayout()
        self.edition_field = StatField("Edition", 90, clickable=True)
        self.rarity_field = StatField("Rarity", 90)
        self.price_field = StatField("Price", 100, clickable=True)
        metadata_row.addWidget(self.edition_field)
        metadata_row.addWidget(self.rarity_field)
        metadata_row.addWidget(self.price_field)
        metadata_row.addStretch()
        layout.addLayout(metadata_row)

        self.oracle_text_label = QLabel()
        self.oracle_text_label.setWordWrap(True)
        layout.addWidget(self.oracle_text_label)

        self.flavor_text_label = QLabel()
        self.flavor_text_label.setWordWrap(True)
        self.flavor_text_label.setStyleSheet("color: #a8adb5; font-style: italic;")
        layout.addWidget(self.flavor_text_label)

        layout.addStretch()
        return layout

    def _build_legality_pane(self):
        layout = self._pane_layout("Legality")
        self.legality_list = QListWidget()
        layout.addWidget(self.legality_list)
        return layout

    def _build_rulings_pane(self):
        layout = self._pane_layout("Rulings")
        self.rulings_list = QListWidget()
        self.rulings_list.setWordWrap(True)
        layout.addWidget(self.rulings_list)
        return layout

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
