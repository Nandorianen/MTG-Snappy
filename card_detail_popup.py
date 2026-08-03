"""
card_detail_popup.py
---------------------
The double-click detail view: a custom (frameless, no OS title bar) window
with a clickable art placeholder, two rows of fixed-position stats
(gameplay: Type / Mana Cost -- metadata: Edition / Language / Condition /
Foil / Rarity / Price), oracle + flavor text, then Legality and Rulings as
side-by-side panes separated by thin vertical rules.

FIVE PIECES OF CUSTOM MACHINERY WORTH CALLING OUT:

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
   text-scaling settings, etc). Every pane's caption is centered with a
   fixed gap before its content (_pane_layout) -- shared by all three so
   Legality/Rulings/Card read as one consistent family of headers rather
   than each pane inventing its own spacing.

3. No system title bar, AND no redundant in-dialog title either: this is a
   frameless top-level QDialog with only a thin CLOSE-button strip (see
   FramelessDialog's show_title=False) -- the card's NAME is what used to
   duplicate as both the window's title-bar text and a generic "Card" pane
   caption; now it's shown exactly once, as the Card pane's own header,
   styled the way a header should be (bold, larger, full-brightness) which
   also happens to be the same visual weight the title bar used to use.
   KNOWN LIMITATION: going frameless also loses the OS's native edge-drag
   resize; this dialog is a fixed size for now rather than reimplementing
   resize handles, which wasn't asked for.
   It also closes automatically the moment the user clicks anywhere in the
   MAIN application window -- checked via `watched.window() is <the main
   window>`, which is what correctly tells a genuine main-window click apart
   from a click inside this dialog OR inside a transient popup menu it
   opened (a QMenu's own `.window()` is the menu itself, not the main
   window, so choosing an Edition/Price/Language/Condition option never
   accidentally closes the dialog mid-click).

4. The zoomable/draggable image window is a separate frameless top-level
   QWidget of its own (see ImageZoomWidget) -- dragging is implemented by
   hand since there's no OS title bar to drag by there either; wheel-zoom
   scales the window uniformly on wheelEvent. Ctrl+drag adds a SECOND,
   independent zoom mechanism: a reticle-select that crops to a region and
   fills the current screen (see ImageZoomWidget's own docstring for why
   this is deliberately kept separate from wheel-zoom rather than unified
   into one "zoom level," and for the normalized _view_rect tracking that
   makes repeated reticle zooms compose correctly instead of each one
   re-measuring against the full original image). This resolves the
   reticle-zoom idea that used to be parked in NOTES.md -- see README.md's
   changelog entry for this round for the full design writeup.

5. StatField's clickable (dropdown) variant now CENTERS BY HUGGING ITS OWN
   CONTENT rather than centering long text inside an artificially wide
   button -- see StatField's docstring for why that distinction is what
   actually fixes Edition/Price/Language/Condition's alignment, and why
   the old "reserve the arrow's width twice" patch was treating a symptom
   instead of the real cause.
"""

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QToolButton, QMenu, QListWidget, QListWidgetItem, QApplication, QSizePolicy,
    QPushButton,
)
from PySide6.QtCore import Qt, Signal, QSize, QEvent, QTimer, QRect, QRectF, QPoint
from PySide6.QtGui import QFontMetrics, QColor, QPainter

from frameless_dialog import FramelessDialog
from mock_data import (
    get_card_by_name, get_card_prints, get_card_legalities, get_card_rulings,
    swatch_for_card, FORMATS, PRICE_SOURCES, LANGUAGES, CONDITIONS,
)

LEGALITY_COLORS = {
    "legal": "#4caf50", "not_legal": "#8a8d8f",
    "banned": "#d3202a", "restricted": "#e67e22",
}

# Two distinct gaps, deliberately different sizes so the visual hierarchy
# reads correctly: a caption belongs to the value directly below it (tight
# gap), while one ROW of stats (gameplay / edition-rarity-price /
# language-condition-foil) is a separate grouping from the next row (looser
# gap). CAPTION_VALUE_SPACING is used inside StatField's own layout;
# STAT_ROW_SPACING is added between rows in _build_card_pane. Kept as named
# constants (rather than two more magic numbers) specifically so this
# ordering -- row gap > caption/value gap -- is enforced by a single glance
# at these two lines, not by re-measuring pixel values scattered through
# the layout code below.
CAPTION_VALUE_SPACING = 4
STAT_ROW_SPACING = 9
# Gap between adjacent columns WITHIN a stat row (Type|Mana, or
# Edition|Rarity|Price, etc). Explicitly set on every row's QHBoxLayout
# (rather than left as Qt's implicit style-default spacing) specifically
# so Type's dynamic-anchor formula in StatField.set_text() can use this
# EXACT, KNOWN value to compute where column 1 of a real 3-column row
# centers -- see that formula's comment for the derivation. Leaving this
# as an unstated implicit default would make that formula a guess instead
# of an exact answer.
ROW_COLUMN_SPACING = 8
# StatField's own inner QVBoxLayout margin (left/right side). Named here
# because the dynamic_anchor calculation in set_text() needs to know this
# exact number: anchor_center is computed relative to a FIELD's OUTER left
# edge (to match how a real grid column's width/center is measured), but
# it gets applied via setContentsMargins() on the LABEL INSIDE that field,
# whose own local coordinate origin is already shifted right by this same
# margin. Forgetting to subtract it was a real, measured ~4px bug -- not a
# rounding artifact -- caught by instantiating the dialog headlessly and
# comparing actual rendered text positions rather than trusting the
# algebra alone. Keep this in sync with StatField.__init__'s own
# `layout.setContentsMargins(FIELD_INNER_MARGIN, 0, FIELD_INNER_MARGIN, 0)`.
FIELD_INNER_MARGIN = 4

# Reused for the Apply button so it reads as the same "confirm/primary
# action" affordance CardDatabaseView's Inventory/Wishlist toggle buttons
# already established elsewhere in the app, instead of inventing a second
# visual language for "this button does something meaningful." Unlike
# those two, this one is a plain QPushButton (not checkable) -- it's a
# one-shot action, not a persistent on/off state -- so only the base +
# hover rules apply; there's no :checked rule to borrow.
APPLY_BUTTON_STYLE = """
QPushButton {
    padding: 5px 14px;
    border: 1px solid #4f8fc0;
    border-radius: 4px;
    background-color: #3d6a8f;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #4f8fc0;
}
"""


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

    WHY THE CLICKABLE VARIANT USED TO DRIFT LEFT (and how this fixes it):
    The old approach stretched the QToolButton to fill the ENTIRE field
    width, then relied on the button's own `text-align: center` CSS plus
    manually-reserved left/right padding to make the text land in the
    middle. That's two independent systems fighting over the same pixels:
    Qt's style engine positions the native dropdown-arrow subcontrol
    (QToolButton::menu-indicator) according to its OWN geometry rules,
    while our CSS `padding-left`/`padding-right` was a separate, hand-
    guessed estimate of how much room that arrow actually needs. When the
    two disagreed -- which they did, consistently -- the visible text sat
    off-center by a fixed, structural amount, not a per-case glitch.

    THE FIX, PART 1 (centering): stop stretching the button to fill the
    field. Give it QSizePolicy.Maximum so it sizes to its own sizeHint()
    and nothing more, then center THAT tight button within the field using
    ordinary layout stretches (addStretch() on both sides in a
    QHBoxLayout) -- see __init__ below. Centering happens at the LAYOUT
    level now, not via CSS text-align, so it doesn't care what the native
    style does internally.

    THE FIX, PART 2 (the arrow itself): rather than trying to reserve
    exactly the right amount of space for the native dropdown-arrow
    subcontrol -- which is what caused part 1's bug in the first place,
    and remains a source of "aligns by a width that quietly includes an
    arrow nobody asked to measure" even once the button hugs its own
    content -- the arrow is removed entirely (`menu-indicator { image:
    none; width: 0px; }`). The value text itself is the click target
    (QToolButton with an attached QMenu opens that menu on any click,
    arrow glyph or not), so the arrow was purely decorative and, worse,
    the one remaining thing whose width this class had to estimate rather
    than measure. No estimate, no drift.
    """

    def __init__(self, title, width=None, clickable=False, align=Qt.AlignLeft,
                 caption_half_width=False, wrap=False, dynamic_anchor=False):
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

        dynamic_anchor=True is Type's special case: instead of a fixed
        pixel indent, the value is anchored to the midpoint of a notional
        1/3-width slot (the same point a normal field's centered value
        would occupy) and grows RIGHTWARD, unevenly, once text is too long
        to sit centered around that point without spilling past the
        field's own left edge. See set_text() for the actual formula --
        it's one clamp, not a length-based branch, so short and long
        values are really the same rule, not two different code paths that
        happen to look similar.

        The "notional 1/3-width slot" is read directly from a real
        single-column sibling cell in the SAME QGridLayout (see
        set_grid_anchor(), called by CardDetailDialog right after building
        the grid), rather than approximated via a formula. Two earlier
        approaches -- deriving it from Type's own width alone, and later a
        correction formula involving row spacing -- were each individually
        reasonable-looking but ultimately still guesses about what a
        DIFFERENT, independently-laid-out row's column width was. A
        QGridLayout removes the guessing entirely: column widths are a
        single property the grid itself computes and enforces identically
        for every cell in that column, spanning or not, so asking the grid
        (via cellRect()) for column 0's width IS the authoritative answer,
        not an approximation of it.
        """
        super().__init__()
        self._fixed_width = width
        self._anchor_grid = None    # see set_grid_anchor()
        self._anchor_row = None
        self._anchor_col = None
        if width is not None:
            self.setFixedWidth(width)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._clickable = clickable
        self._wrap = wrap
        self._align = align
        self._dynamic_anchor = dynamic_anchor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(FIELD_INNER_MARGIN, 0, FIELD_INNER_MARGIN, 0)
        layout.setSpacing(CAPTION_VALUE_SPACING)

        title_label = QLabel(title)
        title_label.setStyleSheet("color: #a8adb5; font-size: 10px;")
        self.title_label = title_label  # kept so dynamic_anchor fields can reposition it in set_text()

        if dynamic_anchor:
            # Positioned via the exact same anchor-point/indent-margin
            # mechanism the VALUE uses below (see set_text()), rather than
            # the separate stretch-based half-width trick the old
            # caption_half_width path used. Sharing one mechanism for both
            # is what guarantees the caption and the value can never drift
            # apart from each other.
            title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.addWidget(title_label)
        elif caption_half_width:
            # Retained for any future field that wants a half-width
            # caption WITHOUT a live sibling-width reference to anchor
            # against -- Type itself no longer takes this path now that
            # dynamic_anchor covers its case more precisely (see above).
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
            # Hug content, don't fill the field -- this is the whole fix
            # (see class docstring). Only Maximum-vs-Preferred matters here;
            # the actual centering happens via the addStretch() pair below.
            self.value_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            # Plain left-aligned text, no padding to reserve -- there's no
            # wide box to center WITHIN (see class docstring, part 1), and
            # no arrow glyph left to make room for (see part 2). The
            # menu-indicator rule below suppresses the native style's
            # arrow entirely rather than trying to size around it.
            self.value_button.setStyleSheet(
                "QToolButton { text-align: left; border: none; font-weight: 600; padding: 0px; } "
                "QToolButton::menu-indicator { image: none; width: 0px; }"
            )
            button_row = QHBoxLayout()
            button_row.setContentsMargins(0, 0, 0, 0)
            button_row.addStretch(1)
            button_row.addWidget(self.value_button)
            button_row.addStretch(1)
            layout.addLayout(button_row)
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

    def set_grid_anchor(self, grid, anchor_row, anchor_col):
        """
        Only meaningful for the dynamic_anchor (Type) field, when it's
        placed into a QGridLayout as a cell that SPANS more than one
        column (Type spans columns 0+1 -- see CardDetailDialog's grid
        construction -- so a long value can grow rightward into column
        1's otherwise-empty space instead of being clipped or wrapping
        early). Points this field at a genuine SINGLE-COLUMN cell
        elsewhere in the SAME grid (Edition's cell: row 1, column 0) so
        SHORT values can still center on column 0 alone, not the midpoint
        of the full 2-column span this field's own width now covers.

        Uses QGridLayout.cellRect() -- a pure layout-geometry query --
        rather than reading a sibling WIDGET's .width() directly. cellRect
        asks the grid itself "how wide is column 0," which is a single
        number the grid computes once and enforces identically for every
        cell in that column; it doesn't depend on whether Edition's own
        set_text() happens to have run yet, or on any other content-
        driven timing at all.
        """
        self._anchor_grid = grid
        self._anchor_row = anchor_row
        self._anchor_col = anchor_col

    def set_text(self, full_text):
        target = self.value_button or self.value_label
        metrics = QFontMetrics(target.font())

        # For fixed-width fields, self.width() is reliable immediately (it
        # was set explicitly in __init__). For stretch-governed fields
        # (width=None, e.g. Type/Mana in the gameplay row), self.width()
        # may still report a stale pre-layout value the first time this
        # runs -- fall back to a generous estimate rather than aggressively
        # over-eliding before the real layout has ever run.
        available = self.width() if (self._fixed_width is not None or self.width() > 40) else 260

        # Hard ceiling on the button's own width, independent of whatever
        # Qt's internal multi-line size calculation thinks it needs for
        # the embedded "\n" breaks _wrap_to_pixel_width() inserts. Without
        # this, a genuinely wide two-line value (e.g. "Chinese" /
        # "Simplified") could report a sizeHint a few pixels past what our
        # own wrap budget intended, and since nothing was capping the
        # button, the containing row would dutifully grow to accommodate
        # it -- visibly shifting every OTHER column in that row too, since
        # they all share equal stretch off the same row width. Explicit
        # setMaximumWidth() is a hard cap Qt layouts always respect (never
        # allocates more, even if the widget's own minimumSizeHint would
        # prefer more) -- worst case for an unrealistically long unbroken
        # word is the text overflowing/clipping visually, which is a far
        # smaller problem than the whole row resizing under you. Applied
        # to every clickable field uniformly (not just the wrap-enabled
        # ones) since it's a no-op for the already-elided single-line
        # fields -- their elided text width is already bounded well under
        # this same ceiling by construction.
        if self._clickable:
            self.value_button.setMaximumWidth(max(20, int(available)))

        if self._dynamic_anchor:
            # Type's rule: anchor the value to the midpoint of a notional
            # 1/3-width slot -- the SAME point column 1 of the Edition/
            # Rarity/Price row (or Language/Condition/Foil row) centers
            # its own value on, so Type's caption/value visually line up
            # with those columns instead of landing at a plausible-looking
            # but structurally different point.
            #
            # Read DIRECTLY from the grid via cellRect() -- see
            # set_grid_anchor()'s docstring for why this is an exact
            # answer rather than an approximation. `available` here is
            # Type's OWN width, which -- because Type's grid cell spans
            # columns 0+1 -- is genuinely "column 0 + column 1 + the gap
            # between them," not something that needs deriving.
            ref_width = 0
            if self._anchor_grid is not None:
                ref_width = self._anchor_grid.cellRect(self._anchor_row, self._anchor_col).width()
            if ref_width <= 40:
                # Pre-layout fallback (same staleness pattern `available`
                # itself guards against elsewhere in this method) --
                # roughly half of Type's own width, since Type's cell
                # spans two real columns and a single column is roughly
                # half of that. Corrected within one event-loop tick by
                # CardDetailDialog's deferred re-refresh.
                ref_width = available / 2
            # anchor_center is measured relative to the FIELD's own OUTER
            # left edge (matching how cellRect/a real column's center is
            # measured). But it gets APPLIED below via setContentsMargins
            # on the caption/value LABEL, whose own local coordinate
            # origin is already shifted right by FIELD_INNER_MARGIN (this
            # field's own inner QVBoxLayout margin) relative to that outer
            # edge. Subtracting it here is what keeps the two coordinate
            # spaces consistent -- skipping this was a real, measured bug
            # (confirmed by instantiating the dialog and comparing actual
            # rendered pixel positions, not just re-deriving the algebra
            # again): every dynamic_anchor value/caption landed exactly
            # FIELD_INNER_MARGIN pixels further right than intended.
            anchor_center = ref_width / 2 - FIELD_INNER_MARGIN

            # indent = distance from Type's left edge to where the text
            # should START if it's centered around that anchor point.
            # Clamped at 0 (never negative): once text is wide enough that
            # centering it would require starting to the LEFT of the
            # field's own edge -- room that doesn't exist -- the indent
            # just stops shrinking, and every additional pixel of text
            # length is forced to overflow rightward instead. Short values
            # still look centered around the same point every other
            # field's value would occupy; long values grow asymmetrically
            # without ever needing a separate branch for "long" vs "short."
            #
            # Caption gets the SAME anchor_center, same clamp-at-0 rule --
            # just measured against its own (short, static, e.g. "Type")
            # text width instead of the value's. This is what keeps the
            # caption and the value pinned to one shared point rather than
            # two independently-approximated ones. Uses the caption
            # label's own font (smaller, gray) for its metrics, not the
            # value's -- the two fonts aren't the same size.
            caption_metrics = QFontMetrics(self.title_label.font())
            caption_width = caption_metrics.horizontalAdvance(self.title_label.text())
            caption_indent = max(0, int(anchor_center - caption_width / 2))
            self.title_label.setContentsMargins(caption_indent, 0, 0, 0)

            text_width = metrics.horizontalAdvance(full_text)
            indent = max(0, int(anchor_center - text_width / 2))
            target.setContentsMargins(indent, 0, 0, 0)

            if self._wrap:
                # QLabel wraps natively against its own contentsRect, which
                # is `available` minus the indent margin just set above --
                # correct now that `available` reflects the real width
                # instead of a stale pre-layout one.
                target.setText(full_text)
            else:
                elided = metrics.elidedText(full_text, Qt.ElideRight, available - indent - 12)
                target.setText(elided)
            target.setToolTip(full_text)
            return

        # No arrow left to reserve space for (see class docstring) -- every
        # field, clickable or not, gets the full field width to work with.
        if self._wrap:
            if self._clickable:
                # QToolButton has no native word-wrap -- break it ourselves
                # and rely on embedded newlines, which QToolButton DOES render.
                wrapped = _wrap_to_pixel_width(full_text, available - 12, metrics)
                target.setText(wrapped)
            else:
                target.setText(full_text)
            target.setToolTip(full_text)
            return

        elided = metrics.elidedText(full_text, Qt.ElideRight, available - 12)
        target.setText(elided)
        target.setToolTip(full_text)


class FoilToggle(QToolButton):
    """
    A simple checkable toggle for the Foil attribute -- styled like the
    other metadata fields (small caption above, bold value below) but as
    one clickable unit rather than a dropdown, since "foil" is binary.
    Not affected by the StatField centering fix above: there's no dropdown
    arrow here to reserve space for, and this button already legitimately
    fills its field (it IS the clickable surface, not a value next to one),
    so text-align:center already centered it correctly before and still does.
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
    screen. Closes on right-click, Escape, a click anywhere outside it
    (see eventFilter), or its owning CardDetailDialog closing (see that
    class's closeEvent). Singleton per dialog -- see CardDetailDialog.
    _open_zoom_window for why a second click on the art re-focuses this
    same window instead of spawning a duplicate.

    ONE UNIFIED MAGNIFICATION MODEL, not two independent ones:
    - _zoom is a pure scale factor on the card's own fixed aspect ratio
      (BASE_SIZE, 300x420 -- MTG's real ~2.5:3.5 ratio). Mouse wheel is
      the only thing that changes it incrementally; nothing ever
      substitutes a DIFFERENT baseline in for BASE_SIZE.
    - _view_rect is which fraction of the (eventual, real) source image
      is framed, in normalized 0..1 coordinates. Only Ctrl+drag reticle
      zoom ever narrows it.
    - The two compose multiplicatively into one displayed number (see
      _effective_zoom_multiplier): shrinking the crop by half doubles
      the multiplier for a FIXED window size, exactly the same way
      doubling the window's pixel size would for a FIXED crop -- they're
      the same kind of magnification, just driven by different inputs,
      which is why the label reads correctly regardless of which one the
      user just changed.

    EARLIER VERSION'S BUG, for context if this needs revisiting: a
    reticle zoom used to OVERWRITE the wheel-zoom baseline with the
    screen's own (non-card-shaped) rectangle and reset _zoom to 1.0.
    That caused three separate visible symptoms from one root cause:
    wheel-zooming out after a reticle zoom jumped disproportionately
    (the "1.0" was relative to a suddenly-huge new baseline, not a
    continuation of whatever zoom level the reticle had actually
    reached); the window took on the SCREEN's aspect ratio instead of
    the card's once wheel-zoomed afterward (a landscape screen produces
    a landscape window); and the zoom label never moved on plain wheel
    scrolling regardless (it only ever read _view_rect, never _zoom, so
    wheel-only magnification was invisible even before the baseline bug).
    Keeping _zoom always relative to the SAME constant baseline, and
    folding _zoom into the displayed multiplier, fixes all three at once
    because they were symptoms of the same "two things claiming to
    measure the same axis, only one of which is real" shape -- treat
    that as a warning sign to look for elsewhere in this app if a
    similar cluster of oddly-related symptoms shows up again.

    WHY grabMouse() DURING A RETICLE DRAG: the window starts small
    (BASE_SIZE, 300x420) -- a real drag gesture will often cross outside
    its bounds before the button comes up. Without an explicit mouse
    grab, Qt simply stops delivering mouseMoveEvent/mouseReleaseEvent the
    instant the cursor leaves the widget, silently abandoning the drag.
    grabMouse()/releaseMouse() bracket the gesture so it tracks correctly
    all the way to wherever the button is actually released -- same
    "Qt's default per-widget delivery isn't enough here" problem shape as
    collapsible_pane.py needing an app-level event filter for Tab.
    """

    BASE_SIZE = QSize(300, 420)
    MIN_ZOOM = 0.3
    # No fixed upper constant -- a hardcoded max would either cut off a
    # legitimate screen-filling reticle zoom on a large monitor, or (if
    # set generously high to avoid that) be a guessed number untethered
    # to any real screen -- exactly the "assumed instead of measured"
    # trap NOTES.md's DPI/scaling entry already warns about elsewhere in
    # this app. The real ceiling (how far BASE_SIZE can scale before it
    # no longer fits the CURRENT screen) is something Qt can just be
    # asked for directly -- see _max_zoom_for_screen().
    MIN_RETICLE_SIZE = 8

    def __init__(self, color, on_close=None):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self._color = QColor(color)
        self._zoom = 1.0
        self._drag_offset = None
        # Called from closeEvent once this window is actually gone --
        # lets CardDetailDialog clear its own reference to this widget
        # (see _on_zoom_widget_closed) so a later click on the art
        # doesn't try to re-focus an already-closed window.
        self._on_close = on_close

        # Which portion of the (eventual, real) source image this window
        # currently frames, in normalized 0..1 image-space coordinates --
        # (0,0,1,1) = the whole image. Only reticle zoom ever narrows this.
        # The placeholder swatch is one flat color with no sub-regions, so
        # this has no visible effect on painting today (see paintEvent) --
        # it's tracked now so real art later needs one new line (a
        # QPixmap.copy() using this exact rect, marked below) instead of a
        # redesign.
        self._view_rect = QRectF(0.0, 0.0, 1.0, 1.0)

        # Reticle drag state -- None whenever a Ctrl+drag isn't active.
        # Local (widget) pixel coords, since that's what paintEvent needs.
        self._reticle_start = None   # QPoint -- where the Ctrl+drag began
        self._reticle_rect = None    # QRect -- current drag extent, for the overlay

        self.resize(self.BASE_SIZE)
        self.setFocusPolicy(Qt.StrongFocus)

        # Click-anywhere-outside-closes -- see eventFilter for the exact
        # condition. Installed/removed the same way FramelessDialog and
        # _MenuSearchBox already do it elsewhere in this app: on the
        # QApplication instance (so it sees every click regardless of
        # which widget receives it), torn down in closeEvent so a closed
        # window doesn't leak a permanent global filter.
        QApplication.instance().installEventFilter(self)

    def _max_zoom_for_screen(self, screen):
        """
        The largest _zoom that keeps a BASE_SIZE-shaped window within
        `screen`'s available area, preserving BASE_SIZE's own aspect
        ratio -- computed from real screen geometry via
        QScreen.availableGeometry(), not a guessed constant. Shared by
        wheelEvent (the ceiling wheel-zoom-in can reach) and
        _finish_reticle (the exact fit a reticle zoom lands on) so the
        two can never independently drift into disagreeing about what
        "as zoomed as the screen allows" means -- same "one shared
        authority instead of two formulas that both have to agree"
        principle as the stat-grid column-width fix in this dialog's own
        alignment work (see the class docstring above and NOTES.md).
        """
        avail = screen.availableGeometry()
        return min(avail.width() / self.BASE_SIZE.width(),
                   avail.height() / self.BASE_SIZE.height())

    def _size_for_zoom(self):
        return QSize(int(self.BASE_SIZE.width() * self._zoom),
                     int(self.BASE_SIZE.height() * self._zoom))

    def _effective_zoom_multiplier(self):
        """
        The single number the on-screen readout shows -- see the class
        docstring for why _zoom and _view_rect compose multiplicatively
        rather than being two separately-reported figures.
        """
        return self._zoom / min(self._view_rect.width(), self._view_rect.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        # --- Real-art hook-in point ---
        # Once real card images exist, this flat fillRect becomes:
        #   painter.drawPixmap(self.rect(), self._pixmap, self._denormalized_source_rect())
        # where _denormalized_source_rect() just multiplies self._view_rect
        # by the pixmap's own size. Everything else in this class already
        # produces the right self._view_rect for that call to be correct.
        painter.fillRect(self.rect(), self._color)
        painter.setPen(QColor("#e3e3e3"))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        if self._reticle_rect is not None:
            self._paint_reticle_overlay(painter)

        zoom_multiplier = self._effective_zoom_multiplier()
        if zoom_multiplier > 1.01:  # only once actually zoomed in from the default
            self._paint_zoom_label(painter, zoom_multiplier)

    def _paint_reticle_overlay(self, painter):
        painter.save()
        # Same accent blue used for selection everywhere else in the app
        # (table row selection, tag-tree focus ring) -- reusing it here
        # keeps this reading as the same KIND of affordance, not a new one.
        painter.setPen(QColor("#4f8fc0"))
        painter.setBrush(QColor(79, 143, 192, 60))  # same blue, translucent
        painter.drawRect(self._reticle_rect)
        painter.restore()

    def _paint_zoom_label(self, painter, zoom_multiplier):
        painter.save()
        label = f"{zoom_multiplier:.1f}\u00d7"  # e.g. "3.2×"
        pad = 6
        text_rect = painter.fontMetrics().boundingRect(label).adjusted(-pad, -pad, pad, pad)
        text_rect.moveTopLeft(self.rect().topLeft() + QPoint(10, 10))
        painter.setBrush(QColor(20, 21, 23, 200))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(text_rect, 4, 4)
        painter.setPen(QColor("#e3e3e3"))
        painter.drawText(text_rect, Qt.AlignCenter, label)
        painter.restore()

    def wheelEvent(self, event):
        factor = 1.1 if event.angleDelta().y() > 0 else (1 / 1.1)
        screen = self.screen() or QApplication.primaryScreen()
        max_zoom = self._max_zoom_for_screen(screen)
        self._zoom = max(self.MIN_ZOOM, min(max_zoom, self._zoom * factor))
        self.resize(self._size_for_zoom())
        # Belt-and-suspenders: resize() already repaints when the pixel
        # size actually changes, but a tiny _zoom delta can round to the
        # SAME integer pixel size (no-op resize, no automatic repaint)
        # while _zoom itself still moved slightly -- cheap enough to just
        # always request one explicitly rather than reason about whether
        # this particular tick happened to cross a pixel boundary.
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.close()
            return
        if event.button() != Qt.LeftButton:
            return
        if event.modifiers() & Qt.ControlModifier:
            self._reticle_start = event.position().toPoint()
            self._reticle_rect = QRect(self._reticle_start, self._reticle_start)
            self.grabMouse()
        else:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._reticle_start is not None:
            self._reticle_rect = QRect(self._reticle_start, event.position().toPoint()).normalized()
            self.update()
            return
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        if self._reticle_start is not None:
            self.releaseMouse()
            rect = self._reticle_rect
            global_release_pos = event.globalPosition().toPoint()
            self._reticle_start = None
            self._reticle_rect = None
            big_enough = rect is not None and rect.width() >= self.MIN_RETICLE_SIZE and rect.height() >= self.MIN_RETICLE_SIZE
            if big_enough:
                self._finish_reticle(rect, global_release_pos)
            else:
                self.update()  # clear the overlay even when the drag was too small to act on
            return
        self._drag_offset = None

    def _finish_reticle(self, local_rect, global_release_pos):
        """
        Commits a completed reticle drag: narrows self._view_rect to the
        selected region (composed against whatever was already framed --
        see below), then sets _zoom to the largest value that FITS the
        current screen (via _max_zoom_for_screen) and centers the
        resulting card-shaped window on it.

        WHY COMPOSED, NOT REPLACED: a SECOND reticle zoom should crop
        further into the first one, not restart measuring from the full
        original image. Expressing the new selection as a FRACTION of the
        current window, then scaling that fraction by the OLD view_rect,
        is what makes repeated zooms stack correctly instead of each one
        silently discarding the previous crop.

        WHY FIT, NOT STRETCH: setting the window to exactly the screen's
        own rectangle (the earlier approach) distorts a card-shaped image
        into whatever shape the screen happens to be. Using
        _max_zoom_for_screen instead scales BASE_SIZE's own aspect ratio
        up until it touches the screen on whichever axis is tighter --
        the window stays card-shaped at every zoom level, letterboxed
        (not stretched) against the screen on the other axis.

        WHY setGeometry() HERE STILL COUNTS AS "CENTERED": the window is
        no longer necessarily screen-sized on BOTH axes (fitting, not
        stretching, can leave one axis smaller than the screen) -- so
        centering is now a real placement step (see _center_on_screen),
        not a side effect of exactly matching the screen rect the way a
        stretch-to-fill approach got it "for free."

        WHY _zoom CARRIES OVER RATHER THAN RESETTING: the earlier version
        reset _zoom to 1.0 here, relative to a baseline it had ALSO just
        replaced with the screen's own size -- two changes at once that
        made the next wheel-zoom-out jump discontinuously. Setting _zoom
        directly to the real fit value (still relative to the one
        constant baseline, BASE_SIZE) means a subsequent wheel-out starts
        from wherever the reticle zoom actually landed and shrinks
        smoothly from there, with _view_rect (the actual crop) completely
        unaffected by wheel input either way.
        """
        w, h = self.width(), self.height()
        frac = QRectF(local_rect.x() / w, local_rect.y() / h,
                       local_rect.width() / w, local_rect.height() / h)

        old = self._view_rect
        self._view_rect = QRectF(
            old.x() + frac.x() * old.width(),
            old.y() + frac.y() * old.height(),
            frac.width() * old.width(),
            frac.height() * old.height(),
        )

        screen = QApplication.screenAt(global_release_pos) or self.screen() or QApplication.primaryScreen()
        self._zoom = self._max_zoom_for_screen(screen)
        self._center_on_screen(screen)

        # Explicit repaint request -- NOT guaranteed by _center_on_screen's
        # own setGeometry() call. Qt only sends a resize/move event (which
        # triggers an automatic repaint) when the new geometry actually
        # DIFFERS from the current one; a second reticle zoom on the SAME
        # screen can compute the identical fit geometry as the first,
        # making that call a real no-op Qt silently skips. Confirmed
        # headlessly during the original version of this fix: 0 repaints
        # on a same-geometry reticle zoom without this line, 1 with it.
        self.update()

    def _center_on_screen(self, screen):
        """
        Resizes to the current _zoom (see _size_for_zoom) and repositions
        so the window sits centered within `screen`'s available area.
        Used after a reticle zoom, where "center on screen" is an
        absolute placement decided fresh each time -- unlike wheelEvent's
        plain resize() (which anchors at the window's current top-left
        corner, appropriate for a small incremental scroll adjustment,
        not a full re-placement).
        """
        avail = screen.availableGeometry()
        size = self._size_for_zoom()
        x = avail.x() + (avail.width() - size.width()) // 2
        y = avail.y() + (avail.height() - size.height()) // 2
        self.setGeometry(x, y, size.width(), size.height())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self._reticle_start is not None:
                # Cancel just the in-progress selection, not the whole
                # viewer -- Escape mid-drag reads as "never mind this
                # selection," not "close the window."
                self.releaseMouse()
                self._reticle_start = None
                self._reticle_rect = None
                self.update()
            else:
                self.close()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        """
        Click-anywhere-outside-this-window closes it. Checked via
        `watched.window() is not self` rather than a main-window-specific
        check like FramelessDialog uses: this widget has no popup menus
        of its own to exempt (unlike FramelessDialog, which has to tell
        "a real outside click" apart from "a click on one of the
        dialog's own dropdown menus"), so ANY press whose target isn't
        part of THIS window counts as outside -- including a click back
        on the card detail dialog itself, which is what makes this
        window read as an attached preview rather than an independent
        one the user has to remember to close by hand. A press that
        starts a Ctrl+drag reticle, or the right-click that closes via
        mousePressEvent above, both originate ON this window
        (watched.window() IS self), so neither is affected by this check.
        """
        if (event.type() == QEvent.MouseButtonPress
                and isinstance(watched, QWidget) and watched.window() is not self):
            self.close()
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        if self._on_close is not None:
            self._on_close()
        super().closeEvent(event)


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


class CardDetailDialog(FramelessDialog):
    def __init__(self, card_name, collection_card=None, on_applied=None, parent=None):
        # show_title=False: the window's own thin top strip is now JUST the
        # close button -- the card's name is shown once, as the Card pane's
        # own header (see _build_card_pane), instead of being duplicated
        # into both the title bar AND a generic "Card" pane caption.
        super().__init__(card_name, parent, show_title=False)
        self.oracle = get_card_by_name(card_name)
        self.prints = get_card_prints(card_name)
        self.current_print_index = 0
        self.price_source = PRICE_SOURCES[0][0]
        # collection_card is the ACTUAL row dict the table holds -- Apply
        # writes directly into it (see _apply_changes). It's distinct from
        # self.oracle, which is the read-only oracle-level lookup. None
        # when there's no real collection context (shouldn't normally
        # happen given how this dialog is opened, but handled safely).
        self.collection_card = collection_card
        self.on_applied = on_applied
        if collection_card is not None:
            self.language = collection_card.get("language", LANGUAGES[0])
            self.condition = collection_card.get("condition", CONDITIONS[0])
        else:
            self.language = LANGUAGES[0]
            self.condition = CONDITIONS[0]
        # Keeps a reference so the window isn't garbage-collected while
        # open, AND doubles as the singleton/lifecycle tracker for it --
        # see _open_zoom_window (re-focuses instead of duplicating) and
        # closeEvent below (closing this dialog closes the zoom window
        # too, rather than leaving it orphaned on screen).
        self._zoom_widget = None

        self.resize(900, 560)

        panes_row = QHBoxLayout()
        panes_row.setSpacing(0)
        panes_row.addLayout(self._build_card_pane(), stretch=3)
        panes_row.addWidget(_vline())
        panes_row.addLayout(self._build_legality_pane())  # no stretch -- sized to content, see below
        panes_row.addWidget(_vline())
        panes_row.addLayout(self._build_rulings_pane(), stretch=2)
        self.content_layout.addLayout(panes_row)

        self._build_edition_menu()
        self._build_price_menu()
        self._build_language_menu()
        self._build_condition_menu()
        self._refresh_for_current_print()
        self._populate_legality()
        self._populate_rulings()

        # Runs a second time, once, on the next event-loop tick -- by which
        # point the caller has called .show() and Qt has done a real
        # layout pass, so every field's self.width() now reflects its
        # ACTUAL geometry instead of whatever it reported before ever
        # being shown. Chained with _lock_column_widths() (see that
        # method's docstring) rather than scheduled as a second, separate
        # singleShot -- this guarantees the locking step runs AFTER the
        # refresh has had a chance to settle real content into every
        # field, not dependent on Qt's ordering between two independently
        # queued zero-timeout timers.
        QTimer.singleShot(0, self._settle_after_first_layout)

    def closeEvent(self, event):
        """
        Cascades to the zoom window: every way this dialog can close (the
        title bar's close button, FramelessDialog's own click-outside-
        the-main-window auto-close, or a programmatic .close()) funnels
        through this one override, so there's a single place that
        guarantees the zoom window never survives its owning card detail
        view -- rather than trying to catch each closing path separately.
        Guarded by `is not None` because the zoom window may already be
        gone by the time this runs (e.g. the user closed it directly, or
        an outside click landed on THIS dialog and closed the zoom window
        via ITS OWN eventFilter microseconds earlier in the same click) --
        ImageZoomWidget.closeEvent already clears self._zoom_widget via
        the on_close callback in that case, so this is a no-op rather than
        a double-close.
        """
        if self._zoom_widget is not None:
            self._zoom_widget.close()
        super().closeEvent(event)

    def _settle_after_first_layout(self):
        self._refresh_for_current_print()
        self._lock_column_widths()

    def _lock_column_widths(self):
        """
        Converts the stat grid's column widths from "whatever stretch +
        content size hints currently produce" into a FIXED, PERMANENT
        pixel number -- immune to any later content change (selecting a
        long Language or Condition value, etc.) ever causing a column to
        widen. Called once, right after the first real layout pass (see
        _settle_after_first_layout).

        WHY THIS IS SAFE: this dialog is a fixed-size window (900x560,
        never resized by the user -- see the class docstring's "known
        limitation" about frameless windows losing native edge-drag
        resize). There's no dynamic-resize scenario a fixed column width
        would ever need to adapt to, so locking it down loses nothing.

        WHY THIS WAS NEEDED: setMaximumWidth() on an individual value
        button (see StatField.set_text()) caps what THAT WIDGET is
        allocated, but doesn't reliably stop QGridLayout from using an
        uncapped minimumSizeHint() when it decides how wide a COLUMN
        itself needs to be -- a number every cell in that column
        contributes to jointly. That's a genuinely different computation
        than the old per-row QHBoxLayout structure had to do, where each
        row's width was decided independently and never needed to
        reconcile against a DIFFERENT row's content at all. Setting BOTH
        setColumnMinimumWidth() and setMaximumWidth() on every cell in a
        column to the exact SAME number removes any remaining degree of
        freedom for Qt to negotiate -- the column can't be anything other
        than that fixed value, regardless of what any individual cell's
        internal size hint claims.
        """
        col_width = self.card_grid.cellRect(1, 0).width()  # Edition's cell -- authoritative real column-0 width
        if col_width <= 40:
            return  # still pre-layout somehow; nothing reliable to lock in yet

        for col in range(3):
            self.card_grid.setColumnMinimumWidth(col, col_width)

        single_column_fields = (
            self.mana_field, self.edition_field, self.rarity_field, self.price_field,
            self.language_field, self.condition_field, self.foil_toggle,
        )
        for field in single_column_fields:
            field.setMaximumWidth(col_width)

        # Type spans columns 0+1 -- its cap is two locked columns plus the
        # single gap between them, not col_width alone.
        self.type_field.setMaximumWidth(col_width * 2 + ROW_COLUMN_SPACING)

    def _pane_layout(self, title):
        """
        Shared caption treatment for every pane: centered text, then a
        fixed gap before whatever content gets added next. Centering was
        the missing piece before (title_label defaulted to AlignLeft);
        without it, "Legality" and "Rulings" read as left-hugging labels
        rather than headers. The addSpacing(8) after the label is what
        gives content a bit of breathing room instead of starting flush
        against the caption's own text.
        """
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 4, 10, 4)
        header = QLabel(title)
        header.setStyleSheet("color: #a8adb5; font-size: 11px; font-weight: 600;")
        header.setAlignment(Qt.AlignHCenter)
        layout.addWidget(header)
        layout.addSpacing(8)
        return layout

    def _build_card_pane(self):
        # NOT using self._pane_layout() here -- the Card pane's header is
        # the card's NAME now, not a generic caption, and it gets a
        # visually heavier style (bold, larger, full-brightness) to match
        # what the window's title bar used to look like, since this is
        # replacing that text rather than sitting alongside it.
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 10, 4)

        name_label = QLabel(self.oracle["name"])
        name_label.setAlignment(Qt.AlignHCenter)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #e3e3e3;")
        layout.addWidget(name_label)
        layout.addSpacing(8)

        self.art_box = ClickableArt()
        self.art_box.setFixedSize(220, 306)
        self.art_box.clicked.connect(self._open_zoom_window)
        layout.addWidget(self.art_box, alignment=Qt.AlignHCenter)
        layout.addSpacing(14)  # a bit more breathing room before the stats start

        # All three stat rows (Type/Mana, Edition/Rarity/Price,
        # Language/Condition/Foil) now live in ONE QGridLayout instead of
        # three independent QHBoxLayouts. WHY THIS MATTERS: a QGridLayout
        # guarantees every cell in the same COLUMN shares the exact same
        # pixel width across every row -- a hard invariant Qt itself
        # enforces, not something reconstructed via a formula that has to
        # correctly guess how a DIFFERENT row's layout divides up its own
        # width. Column 0 (Edition/Language, and now Type's anchor point)
        # is therefore guaranteed to line up, full stop.
        #
        # Type's cell SPANS columns 0+1 (columnSpan=2) rather than living
        # in a single cell -- column 1 is otherwise empty on this row, so
        # spanning into it gives a long type line real room to grow
        # rightward without being clipped or wrapping early, while
        # set_text() still centers SHORT values on column 0 ALONE by
        # querying a genuine single-column sibling cell directly (see
        # StatField.set_grid_anchor(), wired up right after Edition's
        # field exists below).
        self.card_grid = QGridLayout()
        self.card_grid.setHorizontalSpacing(ROW_COLUMN_SPACING)
        self.card_grid.setVerticalSpacing(STAT_ROW_SPACING)
        self.card_grid.setContentsMargins(0, 0, 0, 0)
        for col in range(3):
            self.card_grid.setColumnStretch(col, 1)

        self.type_field = StatField("Type", width=None, wrap=True, dynamic_anchor=True)
        self.mana_field = StatField("Mana Cost", width=None, align=Qt.AlignHCenter, wrap=True)
        self.card_grid.addWidget(self.type_field, 0, 0, 1, 2)  # row 0, col 0, spans 2 columns
        self.card_grid.addWidget(self.mana_field, 0, 2)

        self.edition_field = StatField("Edition", width=None, clickable=True, align=Qt.AlignHCenter)
        self.rarity_field = StatField("Rarity", width=None, align=Qt.AlignHCenter)
        self.price_field = StatField("Price", width=None, clickable=True, align=Qt.AlignHCenter)
        self.card_grid.addWidget(self.edition_field, 1, 0)
        self.card_grid.addWidget(self.rarity_field, 1, 1)
        self.card_grid.addWidget(self.price_field, 1, 2)

        # Wired up right after Edition's field exists: a genuine
        # single-column (colspan=1) cell in the SAME grid Type can query
        # directly for "how wide is column 0, really" -- see
        # set_grid_anchor()'s docstring.
        self.type_field.set_grid_anchor(self.card_grid, anchor_row=1, anchor_col=0)

        self.language_field = StatField("Language", width=None, clickable=True, align=Qt.AlignHCenter, wrap=True)
        self.condition_field = StatField("Condition", width=None, clickable=True, align=Qt.AlignHCenter, wrap=True)
        self.foil_toggle = FoilToggle()
        if self.collection_card is not None:
            self.foil_toggle.setChecked(self.collection_card.get("foil", False))
        self.card_grid.addWidget(self.language_field, 2, 0)
        self.card_grid.addWidget(self.condition_field, 2, 1)
        self.card_grid.addWidget(self.foil_toggle, 2, 2)

        layout.addLayout(self.card_grid)

        # Same row-to-row gap as above, between the last stat row and the
        # Apply button, so Apply reads as its own distinct action rather
        # than crowding directly under Language/Condition/Foil -- and so
        # all three gaps in this pane are driven by one constant instead of
        # three numbers that happened to start out close to each other.
        layout.addSpacing(STAT_ROW_SPACING)

        # Applies the currently-selected Edition/Language/Condition/Foil
        # back onto the actual collection entry (see _apply_changes) --
        # without this there was no way to actually CHANGE what a card in
        # Inventory/All Card Database is recorded as, only preview
        # different options. Deliberately doesn't close the dialog
        # afterward (unlike the tag-apply widget's one-shot Apply) -- this
        # is more of a "preview, then commit, keep browsing" tool than a
        # single decisive action. Styled to match CardDatabaseView's
        # Inventory/Wishlist buttons (bright fill, rounded border) rather
        # than a flat default QPushButton, so it reads as the primary
        # action in this pane instead of blending into the background.
        apply_row = QHBoxLayout()
        self.apply_feedback_label = QLabel("")
        self.apply_feedback_label.setStyleSheet("color: #4caf50;")
        apply_button = QPushButton("Apply")
        apply_button.setStyleSheet(APPLY_BUTTON_STYLE)
        apply_button.clicked.connect(self._apply_changes)
        apply_row.addWidget(self.apply_feedback_label)
        apply_row.addStretch()
        apply_row.addWidget(apply_button)
        layout.addLayout(apply_row)

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
        # below Legality's content-driven width.
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
        self.language_field.set_text(self.language)
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
        """
        Opens the zoomable image window, or -- if one's already open for
        this card -- just brings it back to the front instead of spawning
        a second one. Singleton per dialog: without this, clicking the
        art a second time while a zoom window is already showing (fully
        possible; nothing about having it open disables the art box)
        would leave the FIRST window still alive and unreferenced by
        self._zoom_widget once the second replaced it, so it could never
        be reached (or cleanly closed) again by this dialog. Re-focusing
        the existing window instead also preserves whatever crop/zoom
        state the user already had, which a fresh replacement would lose.
        """
        if self._zoom_widget is not None:
            self._zoom_widget.raise_()
            self._zoom_widget.activateWindow()
            return
        color = swatch_for_card(self.oracle)
        self._zoom_widget = ImageZoomWidget(color, on_close=self._on_zoom_widget_closed)
        self._zoom_widget.show()

    def _on_zoom_widget_closed(self):
        # Fired by ImageZoomWidget.closeEvent, however it got closed
        # (Escape, right-click, an outside click, or this dialog's own
        # closeEvent below calling .close() on it directly). Clearing the
        # reference here -- rather than each of those call sites doing it
        # themselves -- is what keeps _open_zoom_window's singleton check
        # and this dialog's own closeEvent both honest about whether a
        # zoom window genuinely still exists, from a single choke point.
        self._zoom_widget = None

    def _apply_changes(self):
        """
        Commits the currently-previewed Edition/Language/Condition/Foil back
        onto the ACTUAL collection entry (self.collection_card is the same
        dict object the table's model holds, so mutating it here is
        immediately visible to the table once it redraws). Deliberately
        does NOT close the dialog -- this is a "preview several options,
        commit whichever one you land on, keep browsing" tool.
        """
        if self.collection_card is None:
            return
        print_info = self.prints[self.current_print_index]
        self.collection_card["set"] = print_info["set"]
        self.collection_card["rarity"] = print_info["rarity"]
        self.collection_card["language"] = self.language
        self.collection_card["condition"] = self.condition
        self.collection_card["foil"] = self.foil_toggle.isChecked()

        if self.on_applied is not None:
            self.on_applied()

        self.apply_feedback_label.setText("Applied ✓")
        QTimer.singleShot(1800, lambda: self.apply_feedback_label.setText(""))
