"""
card_detail_popup.py
---------------------
The double-click detail view: a custom (frameless, no OS title bar) window
with its own name+close title bar, a clickable art placeholder, two rows of
fixed-position stats (gameplay: Type / Mana Cost -- metadata: Edition /
Language / Condition / Foil / Rarity / Price), oracle + flavor text, then
Legality and Rulings as side-by-side panes separated by thin vertical rules.

FOUR PIECES OF CUSTOM MACHINERY WORTH CALLING OUT:

1. "FIXED POSITION even if text length changes" -- StatField fixes each
   stat to a constant pixel width and ELIDES (truncates with "…") any text
   that doesn't fit, via QFontMetrics.elidedText(). Full text stays
   available as a tooltip.

2. Panes-not-tabs layout: three widgets in one QHBoxLayout with
   setSpacing(0), separated by QFrame vertical-line separators rather than
   layout spacing. The Legality pane is sized to its CONTENT (the widest
   "format: status" string that can actually occur) rather than a
   proportional share of the dialog's width, with word-wrap as a fallback
   for anything that still doesn't fit (longer translated strings, larger
   text-scaling settings, etc).

3. No system title bar: this is a frameless top-level QDialog with its own
   thin title bar (name + a close button, styled to blend via the palette
   rather than look like a separate app), draggable by that bar. KNOWN
   LIMITATION: going frameless also loses the OS's native edge-drag resize;
   this dialog is a fixed size for now rather than reimplementing resize
   handles, which wasn't asked for.
   It also closes automatically the moment the user clicks anywhere in the
   MAIN application window -- checked via `watched.window() is <the main
   window>`, which is what correctly tells a genuine main-window click apart
   from a click inside this dialog OR inside a transient popup menu it
   opened (a QMenu's own `.window()` is the menu itself, not the main
   window, so choosing an Edition/Price/Language/Condition option never
   accidentally closes the dialog mid-click).

4. The zoomable/draggable image window is a separate frameless top-level
   QWidget of its own (see ImageZoomWidget) -- dragging is implemented by
   hand since there's no OS title bar to drag by there either; "zoom" is
   implemented by resizing the window on wheelEvent. See NOTES.md for a
   parked idea about reticle-based zoom-to-region.
"""

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QToolButton, QMenu, QListWidget, QListWidgetItem, QApplication, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QSize, QEvent
from PySide6.QtGui import QFontMetrics, QColor, QPainter

from mock_data import (
    get_card_by_name, get_card_prints, get_card_legalities, get_card_rulings,
    swatch_for_card, FORMATS, PRICE_SOURCES, LANGUAGES, CONDITIONS,
)

LEGALITY_COLORS = {
    "legal": "#4caf50", "not_legal": "#8a8d8f",
    "banned": "#d3202a", "restricted": "#e67e22",
}


def _wrap_to_pixel_width(text, pixel_width, font_metrics):
    """
    Manual word-wrap for QToolButton text -- unlike QLabel, QToolButton has
    no native word-wrap property, but it DOES render embedded newlines as
    separate lines, so we break the text ourselves and join with "\\n".
    Used for the Condition field, which can't rely on QLabel's automatic
    wrapping since it needs to stay clickable (a dropdown button).
    """
    words = text.split()
    if not words:
        return text
    lines, current = [], words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font_metrics.horizontalAdvance(candidate) <= pixel_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return "\n".join(lines)


class StatField(QWidget):
    """
    One fixed-width labeled stat. `clickable=True` swaps the value QLabel
    for a QToolButton with a popup menu -- used for Edition, Language,
    Condition, and Price.

    The clickable variant reserves extra width for Qt's own menu-indicator
    arrow (drawn automatically by the style for InstantPopup buttons) --
    without that reservation, elided text is computed as if the full field
    width were available for text, and the arrow ends up drawn directly on
    top of the last few characters.
    """

    ARROW_RESERVE = 16  # px reserved for the QToolButton's native dropdown arrow

    def __init__(self, title, width=None, clickable=False, align=Qt.AlignLeft,
                 caption_half_width=False, wrap=False):
        """
        width=None means "no fixed width -- let the containing layout's
        stretch factor govern my size instead" (used for the proportional
        row splits). Any other value fixes the width exactly, which is what
        makes elision reliable for the metadata fields.

        caption_half_width=True centers the CAPTION (the small label above
        the value) within only the first half of this field's width, rather
        than its full width -- used for Type, which occupies 2/3 of the
        gameplay row for its VALUE (long type lines need the room) but
        whose caption should still land where a normal 1/3-width field's
        caption would, so the header row reads consistently with Mana
        Cost's caption instead of looking like it's centered in a much
        wider box than every other caption.

        wrap=True switches from eliding ("…") to wrapping onto multiple
        lines as a fallback when text doesn't fit -- QLabel does this
        natively; QToolButton needs the manual _wrap_to_pixel_width() helper
        since it has no built-in word-wrap.
        """
        super().__init__()
        self._fixed_width = width
        if width is not None:
            self.setFixedWidth(width)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._clickable = clickable
        self._wrap = wrap
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet("color: #a8adb5; font-size: 10px;")
        if caption_half_width:
            # The caption gets HALF the field's width (a stand-in for "a
            # normal 1/3-of-the-row slot," since this field itself is 2/3 of
            # the row), centered within that half, with the remaining half
            # left as blank space -- rather than centering across the
            # field's full (much wider) width.
            title_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            caption_row = QHBoxLayout()
            caption_row.setContentsMargins(0, 0, 0, 0)
            caption_row.addWidget(title_label, stretch=1)
            caption_row.addStretch(1)
            layout.addLayout(caption_row)
        else:
            title_label.setAlignment(align | Qt.AlignVCenter)
            layout.addWidget(title_label)

        if clickable:
            self.value_button = QToolButton()
            self.value_button.setPopupMode(QToolButton.InstantPopup)
            align_css = "center" if align == Qt.AlignHCenter else "left"
            # Symmetric padding is what makes text-align:center actually
            # LOOK centered: with only padding-right reserved (needed so the
            # arrow glyph doesn't overlap text), Qt centers within a content
            # box that's shifted left by that same amount, which reads as
            # visibly off-center. Matching padding-left restores a truly
            # symmetric content box for the center-aligned case; left-
            # aligned fields don't need it since they were never centered
            # in the first place.
            left_padding = self.ARROW_RESERVE if align == Qt.AlignHCenter else 0
            self.value_button.setStyleSheet(
                f"QToolButton {{ text-align: {align_css}; border: none; font-weight: 600; "
                f"padding-left: {left_padding}px; padding-right: {self.ARROW_RESERVE}px; }} "
                "QToolButton::menu-indicator { subcontrol-position: right center; }"
            )
            layout.addWidget(self.value_button)
            self.value_label = None
        else:
            self.value_label = QLabel()
            self.value_label.setAlignment(align | Qt.AlignVCenter)
            self.value_label.setStyleSheet("font-weight: 600;")
            if wrap:
                self.value_label.setWordWrap(True)
            layout.addWidget(self.value_label)
            self.value_button = None

    def set_menu(self, menu):
        self.value_button.setMenu(menu)

    def set_text(self, full_text):
        target = self.value_button or self.value_label
        metrics = QFontMetrics(target.font())
        reserve = self.ARROW_RESERVE if self._clickable else 0
        # For fixed-width fields, self.width() is reliable immediately (it
        # was set explicitly in __init__). For stretch-governed fields
        # (width=None, e.g. Type/Mana in the gameplay row), self.width()
        # may still report a stale pre-layout value the first time this
        # runs -- fall back to a generous estimate rather than aggressively
        # over-eliding before the real layout has ever run.
        available = self.width() if (self._fixed_width is not None or self.width() > 40) else 260

        if self._wrap:
            if self._clickable:
                # QToolButton has no native word-wrap -- break it ourselves
                # and rely on embedded newlines, which QToolButton DOES render.
                wrapped = _wrap_to_pixel_width(full_text, available - 12 - reserve, metrics)
                target.setText(wrapped)
            else:
                # QLabel wraps natively once setWordWrap(True) is set (done
                # in __init__) -- no eliding, no manual line-breaking needed.
                target.setText(full_text)
            target.setToolTip(full_text)
            return

        elided = metrics.elidedText(full_text, Qt.ElideRight, available - 12 - reserve)
        target.setText(elided)
        target.setToolTip(full_text)


class FoilToggle(QToolButton):
    """
    A simple checkable toggle for the Foil attribute -- styled like the
    other metadata fields (small caption above, bold value below) but as
    one clickable unit rather than a dropdown, since "foil" is binary.
    """

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setText("Foil: No")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setStyleSheet(
            "QToolButton { text-align: center; border: none; font-weight: 600; "
            "padding-top: 14px; }"
            "QToolButton:checked { color: #e6c15c; }"
        )
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked):
        self.setText("Foil: Yes" if checked else "Foil: No")


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
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setStyleSheet("color: #3a3c41;")
    return line


def _hline():
    """Thin horizontal rule -- separates the stat rows from the oracle text
    below, so the two zones read as visually distinct without needing a
    heavier box/border around either."""
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("color: #3a3c41;")
    return line


class _TitleBar(QWidget):
    """
    Stands in for the OS title bar we removed: shows the card name and a
    close button, and is itself the drag handle (press-and-drag anywhere on
    it moves the window, same as dragging a native title bar would).
    """

    def __init__(self, title, on_close):
        super().__init__()
        self.setFixedHeight(34)
        self._drag_offset = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        name_label = QLabel(title)
        name_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(name_label)
        layout.addStretch()

        close_button = QToolButton()
        close_button.setText("\u2715")  # ✕
        close_button.setStyleSheet(
            "QToolButton { border: none; padding: 4px 8px; border-radius: 3px; } "
            "QToolButton:hover { background-color: #a83a3a; color: white; }"
        )
        close_button.clicked.connect(on_close)
        layout.addWidget(close_button)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().pos()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None


class CardDetailDialog(QDialog):
    def __init__(self, card_name, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.oracle = get_card_by_name(card_name)
        self.prints = get_card_prints(card_name)
        self.current_print_index = 0
        self.price_source = PRICE_SOURCES[0][0]
        self.language = LANGUAGES[0]
        self.condition = CONDITIONS[0]
        self._zoom_widget = None  # keep a reference so it isn't garbage-collected while open

        # Remembered so the click-outside-closes check (in eventFilter
        # below) can tell "a click landed in the actual main window" apart
        # from "a click landed inside this dialog" or "inside a popup menu
        # this dialog opened" -- see the module docstring, point 3.
        self._app_window = parent.window() if parent is not None else None

        self.resize(900, 560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(_TitleBar(card_name, self.close))

        content = QVBoxLayout()
        content.setContentsMargins(12, 8, 12, 12)
        outer.addLayout(content)

        panes_row = QHBoxLayout()
        panes_row.setSpacing(0)
        panes_row.addLayout(self._build_card_pane(), stretch=3)
        panes_row.addWidget(_vline())
        panes_row.addLayout(self._build_legality_pane())  # no stretch -- sized to content, see below
        panes_row.addWidget(_vline())
        panes_row.addLayout(self._build_rulings_pane(), stretch=2)
        content.addLayout(panes_row)

        self._build_edition_menu()
        self._build_price_menu()
        self._build_language_menu()
        self._build_condition_menu()
        self._refresh_for_current_print()
        self._populate_legality()
        self._populate_rulings()

        QApplication.instance().installEventFilter(self)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.MouseButtonPress and self._app_window is not None
                and isinstance(watched, QWidget) and watched.window() is self._app_window):
            self.close()
        return super().eventFilter(watched, event)

    def _pane_layout(self, title):
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
        layout.addSpacing(14)  # a bit more breathing room before the stats start

        # GAMEPLAY row: only what matters while playing. Type gets 2/3 of the
        # row (left-aligned, since type lines read left-to-right and can run
        # long), Mana Cost gets the remaining 1/3 (centered, since mana costs
        # are short symbol clusters that read fine centered in their space).
        # Stretch factors (not fixed pixel widths) are what make this an
        # actual 2:1 PROPORTION of whatever width the row ends up with,
        # rather than two fixed sizes with leftover blank space -- there's
        # deliberately no addStretch() after them, since the two fields
        # together ARE meant to fill the row.
        gameplay_row = QHBoxLayout()
        self.type_field = StatField("Type", width=None, caption_half_width=True, wrap=True)
        self.mana_field = StatField("Mana Cost", width=None, align=Qt.AlignHCenter)
        gameplay_row.addWidget(self.type_field, stretch=2)
        gameplay_row.addWidget(self.mana_field, stretch=1)
        layout.addLayout(gameplay_row)

        # METADATA row 1: Edition / Rarity / Price -- collection/shopping
        # info, separated from gameplay info above. Each field is
        # width=None + equal stretch=1, same technique as the gameplay row's
        # 2:1 split -- this is what actually makes them 1/3 of the row each;
        # fixed pixel widths plus a trailing addStretch() (the previous
        # approach) left them left-packed with blank space at the end,
        # which is also why centering the TEXT inside each field didn't
        # look like it was doing anything -- the fields themselves weren't
        # occupying an even share of the row to be centered within.
        metadata_row = QHBoxLayout()
        self.edition_field = StatField("Edition", width=None, clickable=True, align=Qt.AlignHCenter)
        self.rarity_field = StatField("Rarity", width=None, align=Qt.AlignHCenter)
        self.price_field = StatField("Price", width=None, clickable=True, align=Qt.AlignHCenter)
        for field in (self.edition_field, self.rarity_field, self.price_field):
            metadata_row.addWidget(field, stretch=1)
        layout.addLayout(metadata_row)

        # METADATA row 2: Language / Condition / Foil -- kept off row 1 so
        # that row doesn't get cramped; these three also describe a specific
        # OWNED COPY rather than the card or print itself, which is a
        # reasonable second reason to group them apart from Edition/Rarity/
        # Price. Not yet wired to actually saving against a collection
        # entry (see NOTES.md). Same even-thirds technique as row 1.
        collection_row = QHBoxLayout()
        self.language_field = StatField("Language", width=None, clickable=True, align=Qt.AlignHCenter)
        self.condition_field = StatField("Condition", width=None, clickable=True, align=Qt.AlignHCenter, wrap=True)
        self.foil_toggle = FoilToggle()
        for field in (self.language_field, self.condition_field, self.foil_toggle):
            collection_row.addWidget(field, stretch=1)
        layout.addLayout(collection_row)

        layout.addSpacing(6)
        layout.addWidget(_hline())
        layout.addSpacing(6)

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
        self.legality_list.setWordWrap(True)  # fallback for anything the fixed width still can't fit
        self.legality_list.setFixedWidth(self._legality_column_width())
        layout.addWidget(self.legality_list)
        return layout

    def _legality_column_width(self):
        """
        Sized to the WIDEST "format: status" string that can actually occur
        (all formats x all statuses), not a proportional share of the
        dialog. Word-wrap above is the fallback for anything that still
        doesn't fit -- longer translated strings, larger text-scaling
        settings, a format name we haven't accounted for, etc.
        """
        probe = QListWidget()
        metrics = QFontMetrics(probe.font())
        widest = max(
            (f'{fmt}:  {status.replace("_", " ").title()}'
             for fmt in FORMATS for status in LEGALITY_COLORS),
            key=lambda text: metrics.horizontalAdvance(text),
        )
        return metrics.horizontalAdvance(widest) + 44  # padding for list margins + scrollbar

    def _build_rulings_pane(self):
        layout = self._pane_layout("Rulings")
        self.rulings_list = QListWidget()
        self.rulings_list.setWordWrap(True)
        # At least as wide as the Legality pane -- previously it only got
        # whatever the 3:2 stretch split left over, which could shrink
        # below Legality's content-driven width. The border-looking-missing
        # complaint was actually QListWidget not being included in the
        # app's bordered/backgrounded style rule at all (fixed in main.py's
        # STYLE_SHEET) -- both panes' QListWidgets get the same visible
        # border now, this width floor is the separate "at least as wide" ask.
        self.rulings_list.setMinimumWidth(self._legality_column_width())
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

    def _build_language_menu(self):
        menu = QMenu(self)
        for lang in LANGUAGES:
            action = menu.addAction(lang)
            action.triggered.connect(lambda checked=False, l=lang: self._select_language(l))
        self.language_field.set_menu(menu)

    def _build_condition_menu(self):
        menu = QMenu(self)
        for cond in CONDITIONS:
            action = menu.addAction(cond)
            action.triggered.connect(lambda checked=False, c=cond: self._select_condition(c))
        self.condition_field.set_menu(menu)

    def _select_print(self, index):
        self.current_print_index = index
        self._refresh_for_current_print()

    def _select_price_source(self, source_key):
        self.price_source = source_key
        self._refresh_for_current_print()

    def _select_language(self, language):
        # Mock simplification: we don't have real per-language art/text, so
        # this just relabels the field. Once real localized print data
        # exists, this is where re-fetching that print's image/text would go.
        self.language = language
        self.language_field.set_text(language)

    def _select_condition(self, condition):
        self.condition = condition
        self.condition_field.set_text(condition)

    def _refresh_for_current_print(self):
        print_info = self.prints[self.current_print_index]
        self.type_field.set_text(self.oracle["type_line"])
        self.mana_field.set_text(self.oracle["mana_cost"])
        self.edition_field.set_text(print_info["set"].upper())
        self.language_field.set_text(print_info.get("language", self.language))
        self.condition_field.set_text(self.condition)
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
