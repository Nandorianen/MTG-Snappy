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
   FramelessDialog's show_title=False) -- the card's NAME is shown exactly
   once, as the Card pane's own header, styled the way a header should be
   (bold, larger, full-brightness) rather than also duplicated into a
   title bar.
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
   QWidget of its own (see ImageZoomWidget) -- it behaves like a real
   image viewer: opens fit-to-screen, tracks a zoom scalar and a
   separate pan point (not a single crop rectangle -- see
   ImageZoomWidget's own docstring for why that distinction is what makes
   wheel-zoom grow the window correctly; NOTES.md has the two earlier,
   now-superseded designs), and supports actual click-drag panning once
   zoomed in past what fits on screen, falling back to the original
   click-drag-moves-the-window behavior when nothing is cropped.

5. StatField's clickable (dropdown) variant CENTERS BY HUGGING ITS OWN
   CONTENT rather than centering long text inside an artificially wide
   button -- see StatField's docstring for why that distinction is what
   actually fixes Edition/Price/Language/Condition's alignment.

SCALING (scaling.py): every fixed pixel constant this dialog uses
(spacing constants below, the 900x560 default size, the art box, the
legality column width, ImageZoomWidget's BASE_SIZE) is routed through
sp() -- so a NEWLY-OPENED detail popup or zoom window always reflects
whatever ui_scale is current at the moment it's constructed. Deliberately
NOT wired to live-rescale an ALREADY-OPEN dialog the way simpler chrome
(frameless_dialog.py's title bar, dialog_common.py's tab list) is:
StatField's dynamic-anchor Type-column alignment took three real attempts
to get right (see NOTES.md) and depends on FIELD_INNER_MARGIN being
IDENTICAL between the margin actually applied at construction and the
margin subtracted in set_text()'s anchor formula on every subsequent
call -- reapplying sp() mid-lifetime without re-deriving both together
risks exactly the kind of two-independently-computed-numbers drift
NOTES.md's debugging lesson #3 already warns about. Since this dialog is
recreated fresh on every double-click anyway (card_table.py never caches
one), "correct at open time" covers the overwhelmingly common case; see
NOTES.md's "Scaling infrastructure" entry for this as a tracked TODO
rather than a silent gap.
"""

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frameless_dialog import FramelessDialog
from scaling import scale_manager, sp
from mock_data import (
    CONDITIONS,
    FORMATS,
    LANGUAGES,
    PRICE_SOURCES,
    get_card_by_name,
    get_card_legalities,
    get_card_prints,
    get_card_rulings,
    swatch_for_card,
)

LEGALITY_COLORS = {
    "legal": "#4caf50",
    "not_legal": "#8a8d8f",
    "banned": "#d3202a",
    "restricted": "#e67e22",
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
# because the dynamic_anchor calculation in set_text() needs this exact
# number: anchor_center is computed relative to a FIELD's OUTER left edge
# (matching how a real grid column's width/center is measured), but gets
# applied via setContentsMargins() on the LABEL INSIDE that field, whose
# own local coordinate origin is already shifted right by this same
# margin -- subtracting it is what keeps the two coordinate spaces
# consistent (see NOTES.md's "Type-column alignment" entry for the bug
# this fixes). Keep in sync with StatField.__init__'s own
# `layout.setContentsMargins(FIELD_INNER_MARGIN, 0, FIELD_INNER_MARGIN, 0)`.
FIELD_INNER_MARGIN = 4

# Reused for the Apply button so it reads as the same "confirm/primary
# action" affordance CardDatabaseView's Inventory/Wishlist toggle buttons
# already established elsewhere in the app, instead of inventing a second
# visual language for "this button does something meaningful." Unlike
# those two, this one is a plain QPushButton (not checkable) -- it's a
# one-shot action, not a persistent on/off state -- so only the base +
# hover rules apply; there's no :checked rule to borrow.
def _apply_button_style():
    """Function, not a static string -- see main.py's build_stylesheet
    comment for why any QSS with a pixel metric has to be evaluated at
    USE time against the current ui_scale rather than frozen at import."""
    return f"""
QPushButton {{
    padding: {sp(5)}px {sp(14)}px;
    border: 1px solid #4f8fc0;
    border-radius: {sp(4)}px;
    background-color: #3d6a8f;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: #4f8fc0;
}}
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

    WHY THE CLICKABLE VARIANT CENTERS BY HUGGING ITS OWN CONTENT, NOT BY
    STRETCHING TO FILL THE FIELD: centering via CSS `text-align: center`
    on a full-width button depends on correctly reserving space for Qt's
    native dropdown-arrow subcontrol alongside it -- two independent
    systems (Qt's own arrow placement, our own padding estimate) that have
    to agree on the same pixels to look right. This class sidesteps that
    entirely: the button is sized to its own `sizeHint()`
    (`QSizePolicy.Maximum`) and centered within the field via ordinary
    layout stretches (`addStretch()` on both sides -- see __init__ below),
    and the native arrow is removed rather than padded around
    (`menu-indicator { image: none; width: 0px; }`), since the value text
    itself is already the click target. No arrow to reserve space for, no
    two systems to keep in agreement. See NOTES.md's "StatField clickable-
    variant centering" entry for what this replaced and why it drifted.
    """

    def __init__(
        self,
        title,
        width=None,
        clickable=False,
        align=Qt.AlignLeft,
        caption_half_width=False,
        wrap=False,
        dynamic_anchor=False,
    ):
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
        the grid) -- not approximated via a formula. Two earlier formula-
        based approaches each looked reasonable and were each wrong for a
        different reason (see NOTES.md's "Type-column alignment" entry).
        A QGridLayout removes the guessing entirely: column widths are a
        single property the grid itself computes and enforces identically
        for every cell in that column, spanning or not, so asking the grid
        (via cellRect()) for column 0's width IS the authoritative answer,
        not an approximation of it.
        """
        super().__init__()
        self._fixed_width = width
        self._anchor_grid = None  # see set_grid_anchor()
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
        layout.setContentsMargins(sp(FIELD_INNER_MARGIN), 0, sp(FIELD_INNER_MARGIN), 0)
        layout.setSpacing(sp(CAPTION_VALUE_SPACING))

        title_label = QLabel(title)
        title_label.setStyleSheet("color: #a8adb5; font-size: 10px;")
        self.title_label = (
            title_label  # kept so dynamic_anchor fields can reposition it in set_text()
        )

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
        available = (
            self.width()
            if (self._fixed_width is not None or self.width() > 40)
            else 260
        )

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
                ref_width = self._anchor_grid.cellRect(
                    self._anchor_row, self._anchor_col
                ).width()
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
            # spaces consistent -- see NOTES.md's "Type-column alignment"
            # entry for the bug this fixes.
            anchor_center = ref_width / 2 - sp(FIELD_INNER_MARGIN)

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
                elided = metrics.elidedText(
                    full_text, Qt.ElideRight, available - indent - 12
                )
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
    """
    Placeholder 'art' box. Clicking it opens the standalone zoom window.

    WHY event.accept() MATTERS HERE (not just tidiness): a left-click is
    fully handled by emitting `clicked` -- but the base QFrame
    implementation of mousePressEvent calls event.ignore() by default,
    and an ignored mouse event gets propagated by Qt to the PARENT widget
    for a second delivery attempt. That was always happening, silently,
    with no visible effect -- until ImageZoomWidget's outside-click-
    closes filter (see that class) started existing: the zoom window
    gets created and shown SYNCHRONOUSLY inside this very handler (via
    the clicked signal), so its global event filter is already installed
    by the time Qt processes the propagated redelivery to the parent
    dialog a moment later. That redelivery is a real, distinct
    MouseButtonPress whose watched.window() is the CARD DETAIL DIALOG,
    not the zoom window -- exactly what the filter treats as an outside
    click -- so the zoom window was closing itself in the same click
    that opened it, and only a SECOND click (with no zoom window yet
    open to race against) visibly worked. Explicitly accepting a handled
    click stops that propagation at the source instead of requiring
    ImageZoomWidget to somehow guess which propagated events to ignore.
    """

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def set_color(self, color):
        self.setStyleSheet(f"background-color: {color}; border-radius: 6px;")


class ImageZoomWidget(QWidget):
    """
    A separate, frameless, always-on-top-of-itself window showing the
    (placeholder) art, zoomable and pannable like a standard image
    viewer (ACDSee/XnView-style): opens fit-to-screen, and behaves like a
    real camera-position-plus-zoom-level viewer from there. Closes on
    right-click, Escape, a click anywhere outside it (see eventFilter),
    or its owning CardDetailDialog closing (see that class's closeEvent).
    Singleton per dialog -- see CardDetailDialog._open_zoom_window.

    TWO PIECES OF STATE: _zoom (a scalar; 1.0 = fit-to-screen) and
    _pan_center (a normalized 0..1 point in the FULL image, which point
    is centered in the viewport). Both mouse-wheel and reticle-select
    read and write the SAME two variables -- see the history note below
    for why an earlier version's single-crop-rectangle model couldn't
    reproduce standard zoom behavior, and the one before that's
    "separate _zoom and _view_rect" model let the two drift apart.

    HOW THE WINDOW'S OWN SIZE IS DERIVED (_geometry_for_zoom): the full
    image, at the current _zoom, has a size of `fit_size * _zoom` in
    BOTH dimensions together (uniform scaling -- the image's own aspect
    ratio, the card's true shape, is NEVER distorted by zoom, only
    enlarged or shrunk as a whole). The window's ACTUAL on-screen size
    is that image size clamped INDEPENDENTLY per axis to the current
    screen's available area. This is what makes the window grow
    correctly as you zoom in from the opening (fit-to-screen) state:
    whichever axis was already touching the screen edge (typically
    height, for a portrait card on a landscape screen) stays capped
    there, while the OTHER axis (still growing, since the underlying
    image keeps enlarging uniformly) keeps widening the window to fill
    more of the screen -- until it ALSO reaches the screen edge, past
    which further zoom can no longer grow the window at all (both axes
    already maxed) and instead shows progressively less of the image on
    BOTH axes, exactly like zooming into a photo past "fit to window" in
    a real viewer.

    HOW PANNING WORKS: once the image (at the current zoom) exceeds the
    screen on at least one axis, there's real content sitting outside
    the window that _pan_center says which part of. Plain click+drag
    ADJUSTS _pan_center in that case (see mousePressEvent/mouseMoveEvent)
    instead of moving the window -- moving the window only happens when
    there's nothing to pan to (the whole image already fits), since
    otherwise "drag" unambiguously means "look at a different part of
    what's zoomed in," not "reposition this box on my desktop."

    HOW RETICLE-SELECT FITS IN: a completed Ctrl+drag computes a NEW
    _zoom and _pan_center from the selected rectangle (mapped through the
    CURRENT visible fraction into normalized image coordinates -- see
    _finish_reticle) rather than touching a separate crop concept. The
    zoom increase is whatever makes the WHOLE selection visible without
    clipping (the smaller of the two per-axis ratios, same "fit, don't
    overflow" convention _geometry_for_zoom itself uses for the screen).

    MAX_ZOOM (default 4x the fit-to-screen size) is an explicit ceiling
    requested after an earlier version let repeated reticle zooms push
    the effective magnification far higher than any wheel-zoom-out could
    smoothly recover from in one tick -- see history note. Intended to
    become a configurable Options-window setting eventually (explicitly
    low priority), not hardcoded forever.

    HISTORY: two earlier designs (a separate window-size/crop-rectangle
    pair, then a single crop rectangle scaled by wheel) each fixed a real
    bug and revealed the next one -- see NOTES.md's "Reticle-zoom image
    viewer" entry for the full history. THIS version separates "how big
    is the image" (_zoom, uniform, never distorts shape) from "which part
    is centered" (_pan_center) explicitly, instead of representing both
    with one rectangle, and bounds _zoom to a fixed range so neither
    earlier failure mode has room to recur.

    WHY grabMouse() DURING A RETICLE DRAG: the window can be much larger
    than a small fixed starting size (it opens fit-to-screen). Without an
    explicit mouse grab, Qt stops delivering mouseMoveEvent/
    mouseReleaseEvent the instant the cursor leaves the widget mid-drag.
    grabMouse()/releaseMouse() bracket the gesture so it tracks correctly
    all the way to wherever the button is actually released -- same
    "Qt's default per-widget delivery isn't enough here" shape as
    collapsible_pane.py needing an app-level event filter for Tab.
    """

    # The card's own aspect ratio (~2.5:3.5) -- a RATIO reference only, not
    # a literal on-screen size (this window opens fit-to-screen, always
    # larger than this). Deliberately NOT a class-level constant computed
    # once at import time -- see this module's own scaling note above and
    # scaling.py's docstring for why a bare `QSize(sp(300), sp(420))` at
    # class-body scope would freeze at whatever ui_scale happened to be
    # active on first import. Set as an INSTANCE attribute in __init__
    # instead, from the ui_scale current at the moment this particular
    # zoom window is opened (this widget is always freshly constructed
    # per open, never cached/reused -- see CardDetailDialog._open_zoom_
    # window's singleton-per-DIALOG, not per-app, comment).
    BASE_SIZE = QSize(300, 420)
    MIN_ZOOM = 0.3
    # Explicit ceiling, requested after an earlier design let effective
    # magnification run away far higher than a single wheel-out tick
    # could smoothly recover from (see history note above). Meant to
    # become a configurable Options-window setting eventually -- low
    # priority, not built yet.
    MAX_ZOOM = 4.0
    MIN_RETICLE_SIZE = 8
    # How close a per-axis visible fraction needs to be to 1.0 to count
    # as "the whole image already fits, nothing to pan to" -- guards
    # against floating-point noise (e.g. 0.999999997) being treated as
    # "still slightly cropped" and incorrectly entering pan mode.
    _FULLY_VISIBLE_THRESHOLD = 0.999

    def __init__(self, color, on_close=None):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self._color = QColor(color)
        self._on_close = on_close

        # Instance override of the class-level ratio constant above,
        # scaled to the ui_scale active right now -- see that attribute's
        # own comment for why this can't just be computed once at class-
        # definition time.
        self.BASE_SIZE = QSize(sp(self.BASE_SIZE.width()), sp(self.BASE_SIZE.height()))

        self._zoom = 1.0
        self._pan_center = QPointF(0.5, 0.5)

        # Reticle drag state -- None whenever a Ctrl+drag isn't active.
        self._reticle_start = None  # QPoint, local widget coords
        self._reticle_rect = None  # QRect, current drag extent, for the overlay

        # Plain-drag state -- exactly ONE of these two pairs is active at
        # a time, decided at press-time by whether there's anything to
        # pan to (see mousePressEvent). Window-move:
        self._drag_offset = None
        # Pan:
        self._pan_start = None  # QPoint, local widget coords at press
        self._pan_center_start = None  # QPointF, _pan_center at press
        self._pan_visible_frac = None  # (float, float), visible fraction at press

        self.setFocusPolicy(Qt.StrongFocus)

        # Best-effort initial sizing before the window has ever been
        # shown (self.screen() can't yet reflect which real screen this
        # will end up on). Corrected for real on the next event-loop
        # tick via _settle_after_show, once the platform has actually
        # placed the window -- same "settle on the next tick" pattern
        # CardDetailDialog already uses for its own post-show fixups.
        self._apply_zoom(QApplication.primaryScreen())
        QTimer.singleShot(0, self._settle_after_show)

        # Click-anywhere-outside-closes -- see eventFilter for the exact
        # condition. Installed/removed the same way FramelessDialog and
        # _MenuSearchBox already do it elsewhere in this app.
        QApplication.instance().installEventFilter(self)

    def _settle_after_show(self):
        screen = self.screen() or QApplication.primaryScreen()
        self._apply_zoom(screen)

    def _geometry_for_zoom(self, screen):
        """
        The single authority both wheelEvent and _finish_reticle read
        from: given the CURRENT _zoom, returns (window_size, visible_
        fraction_x, visible_fraction_y) for `screen`. Nothing downstream
        derives window size or visible fraction any other way, so they
        can never independently disagree with each other about what the
        current zoom level actually looks like.
        """
        avail = screen.availableGeometry()
        fit_zoom = min(
            avail.width() / self.BASE_SIZE.width(),
            avail.height() / self.BASE_SIZE.height(),
        )
        image_w = self.BASE_SIZE.width() * fit_zoom * self._zoom
        image_h = self.BASE_SIZE.height() * fit_zoom * self._zoom
        window_w = min(image_w, float(avail.width()))
        window_h = min(image_h, float(avail.height()))
        size = QSize(max(1, int(window_w)), max(1, int(window_h)))
        return size, window_w / image_w, window_h / image_h

    def _apply_zoom(self, screen):
        """
        Resizes to _geometry_for_zoom's window size and centers the
        result within `screen`'s available area. Called on every zoom
        CHANGE (wheel, reticle, initial show) -- not on plain panning,
        since panning only changes which part of an already-sized window
        is (conceptually) shown, not the window's own on-screen bounds.
        """
        size, _, _ = self._geometry_for_zoom(screen)
        avail = screen.availableGeometry()
        x = avail.x() + (avail.width() - size.width()) // 2
        y = avail.y() + (avail.height() - size.height()) // 2
        self.setGeometry(x, y, size.width(), size.height())
        # Explicit repaint request -- NOT guaranteed by setGeometry()
        # above, which only triggers Qt's automatic repaint when the new
        # geometry actually DIFFERS from the current one (e.g. re-entering
        # a zoom level the window is already sized for).
        self.update()

    def _clamp_pan_center(self, screen):
        """
        Keeps _pan_center from sitting somewhere that would require
        showing past the image's own edges. When a given axis is fully
        visible (visible_frac >= 1, nothing to pan on that axis), the
        clamp bounds collapse to exactly 0.5 -- forcing pan back to
        center on that axis rather than leaving it wherever a previous,
        more-zoomed-in pan happened to leave it.
        """
        _, vis_w, vis_h = self._geometry_for_zoom(screen)
        x = min(max(self._pan_center.x(), vis_w / 2), 1.0 - vis_w / 2)
        y = min(max(self._pan_center.y(), vis_h / 2), 1.0 - vis_h / 2)
        self._pan_center = QPointF(x, y)

    def _effective_zoom_multiplier(self):
        return self._zoom

    def paintEvent(self, event):
        painter = QPainter(self)
        # --- Real-art hook-in point ---
        # Once real card images exist, this flat fillRect becomes drawing
        # the sub-rectangle of the real pixmap implied by the current
        # _pan_center and the visible fraction from _geometry_for_zoom --
        # everything needed for that (an exact normalized source rect) is
        # already computed by this class, just not consumed by painting
        # yet since there's no real pixmap to sample from.
        painter.fillRect(self.rect(), self._color)
        painter.setPen(QColor("#e3e3e3"))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        if self._reticle_rect is not None:
            self._paint_reticle_overlay(painter)

        zoom_multiplier = self._effective_zoom_multiplier()
        if zoom_multiplier > 1.01:  # hidden at the default (fully zoomed out) state
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
        text_rect = (
            painter.fontMetrics().boundingRect(label).adjusted(-pad, -pad, pad, pad)
        )
        text_rect.moveTopLeft(self.rect().topLeft() + QPoint(10, 10))
        painter.setBrush(QColor(20, 21, 23, 200))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(text_rect, 4, 4)
        painter.setPen(QColor("#e3e3e3"))
        painter.drawText(text_rect, Qt.AlignCenter, label)
        painter.restore()

    def wheelEvent(self, event):
        factor = 1.1 if event.angleDelta().y() > 0 else (1 / 1.1)
        self._zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom * factor))
        screen = self.screen() or QApplication.primaryScreen()
        # The valid pan range depends on the zoom that just changed --
        # re-clamp before resizing, not after, so _apply_zoom never
        # briefly renders against a pan_center that's already stale for
        # the new zoom level.
        self._clamp_pan_center(screen)
        self._apply_zoom(screen)

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
            return

        screen = self.screen() or QApplication.primaryScreen()
        _, vis_w, vis_h = self._geometry_for_zoom(screen)
        if (
            vis_w < self._FULLY_VISIBLE_THRESHOLD
            or vis_h < self._FULLY_VISIBLE_THRESHOLD
        ):
            # The image exceeds the screen on at least one axis at the
            # current zoom -- there's real content outside the window
            # for _pan_center to point at, so plain drag pans instead of
            # moving the window (matching a real image viewer: once
            # zoomed in past "fit," drag unambiguously means "look
            # elsewhere in the image," not "move this box around").
            self._pan_start = event.position().toPoint()
            self._pan_center_start = QPointF(self._pan_center)
            self._pan_visible_frac = (vis_w, vis_h)
        else:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._reticle_start is not None:
            self._reticle_rect = QRect(
                self._reticle_start, event.position().toPoint()
            ).normalized()
            self.update()
            return
        if self._pan_start is not None:
            pos = event.position().toPoint()
            dx = pos.x() - self._pan_start.x()
            dy = pos.y() - self._pan_start.y()
            vis_w, vis_h = self._pan_visible_frac
            w, h = self.width(), self.height()
            # Dragging right/down reveals content that was further
            # left/up -- the pan center moves OPPOSITE the drag
            # direction, same convention as "grab and drag the canvas"
            # in any standard image viewer or map application.
            new_x = self._pan_center_start.x() - (dx / w) * vis_w
            new_y = self._pan_center_start.y() - (dy / h) * vis_h
            self._pan_center = QPointF(new_x, new_y)
            self._clamp_pan_center(self.screen() or QApplication.primaryScreen())
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
            big_enough = (
                rect is not None
                and rect.width() >= self.MIN_RETICLE_SIZE
                and rect.height() >= self.MIN_RETICLE_SIZE
            )
            if big_enough:
                self._finish_reticle(rect, global_release_pos)
            else:
                self.update()  # clear the overlay even when the drag was too small to act on
            return
        self._pan_start = None
        self._drag_offset = None

    def _finish_reticle(self, local_rect, global_release_pos):
        """
        Commits a completed reticle drag: maps the dragged LOCAL rectangle
        through the CURRENT visible fraction into normalized image
        coordinates (so a selection made while already zoomed/panned in
        composes correctly against that state, rather than being measured
        against the full original image), then derives a new _zoom (the
        smallest increase that makes the WHOLE selection visible without
        clipping -- the smaller of the two per-axis fit ratios) and a new
        _pan_center (the selection's own center).
        """
        screen = (
            QApplication.screenAt(global_release_pos)
            or self.screen()
            or QApplication.primaryScreen()
        )
        w, h = self.width(), self.height()
        _, vis_w, vis_h = self._geometry_for_zoom(screen)

        vis_left = min(max(0.0, self._pan_center.x() - vis_w / 2), 1.0 - vis_w)
        vis_top = min(max(0.0, self._pan_center.y() - vis_h / 2), 1.0 - vis_h)

        sel_w = (local_rect.width() / w) * vis_w
        sel_h = (local_rect.height() / h) * vis_h
        if sel_w <= 0 or sel_h <= 0:
            return
        sel_left = vis_left + (local_rect.x() / w) * vis_w
        sel_top = vis_top + (local_rect.y() / h) * vis_h

        zoom_factor = min(1.0 / sel_w, 1.0 / sel_h)
        self._zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom * zoom_factor))
        self._pan_center = QPointF(sel_left + sel_w / 2, sel_top + sel_h / 2)
        self._clamp_pan_center(screen)
        self._apply_zoom(screen)

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
        of its own to exempt, so ANY press whose target isn't part of
        THIS window counts as outside -- including a click back on the
        card detail dialog itself. A press that starts a Ctrl+drag
        reticle, a pan drag, or the right-click that closes via
        mousePressEvent above, all originate ON this window
        (watched.window() IS self), so none of them are affected by
        this check.
        """
        if (
            event.type() == QEvent.MouseButtonPress
            and isinstance(watched, QWidget)
            and watched.window() is not self
        ):
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

        self.resize(sp(900), sp(560))

        panes_row = QHBoxLayout()
        panes_row.setSpacing(0)
        panes_row.addLayout(self._build_card_pane(), stretch=3)
        panes_row.addWidget(_vline())
        panes_row.addLayout(
            self._build_legality_pane()
        )  # no stretch -- sized to content, see below
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

        WHY THIS WAS NEEDED: setMaximumWidth() on an individual cell (see
        StatField.set_text()) caps what THAT WIDGET is allocated, but
        doesn't reliably stop QGridLayout from sizing the whole COLUMN off
        an uncapped minimumSizeHint() -- a real difference from the old
        per-row QHBoxLayout structure, where each row's width was decided
        independently and never had to reconcile against a different
        row's content. Setting BOTH setColumnMinimumWidth() and
        setMaximumWidth() on every cell in a column to the identical
        number removes Qt's remaining freedom to negotiate -- the column
        can't be anything other than that fixed value. See NOTES.md's
        "Type-column alignment" entry for the failed attempts that
        preceded this fix.
        """
        col_width = self.card_grid.cellRect(
            1, 0
        ).width()  # Edition's cell -- authoritative real column-0 width
        if col_width <= 40:
            return  # still pre-layout somehow; nothing reliable to lock in yet

        for col in range(3):
            self.card_grid.setColumnMinimumWidth(col, col_width)

        single_column_fields = (
            self.mana_field,
            self.edition_field,
            self.rarity_field,
            self.price_field,
            self.language_field,
            self.condition_field,
            self.foil_toggle,
        )
        for field in single_column_fields:
            field.setMaximumWidth(col_width)

        # Type spans columns 0+1 -- its cap is two locked columns plus the
        # single gap between them, not col_width alone.
        self.type_field.setMaximumWidth(col_width * 2 + sp(ROW_COLUMN_SPACING))

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
        layout.setContentsMargins(sp(10), sp(4), sp(10), sp(4))
        header = QLabel(title)
        header.setStyleSheet("color: #a8adb5; font-size: 11px; font-weight: 600;")
        header.setAlignment(Qt.AlignHCenter)
        layout.addWidget(header)
        layout.addSpacing(sp(8))
        return layout

    def _build_card_pane(self):
        # NOT using self._pane_layout() here -- the Card pane's header is
        # the card's NAME, not a generic caption, styled heavier (bold,
        # larger, full-brightness) since this dialog has no separate
        # title-bar text of its own (see FramelessDialog's show_title=False
        # in this dialog's __init__) -- the name is shown exactly once,
        # here.
        layout = QVBoxLayout()
        layout.setContentsMargins(sp(4), sp(4), sp(10), sp(4))

        name_label = QLabel(self.oracle["name"])
        name_label.setAlignment(Qt.AlignHCenter)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #e3e3e3;")
        layout.addWidget(name_label)
        layout.addSpacing(sp(8))

        self.art_box = ClickableArt()
        self.art_box.setFixedSize(sp(220), sp(306))
        self.art_box.clicked.connect(self._open_zoom_window)
        layout.addWidget(self.art_box, alignment=Qt.AlignHCenter)
        layout.addSpacing(sp(14))  # a bit more breathing room before the stats start

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
        self.card_grid.setHorizontalSpacing(sp(ROW_COLUMN_SPACING))
        self.card_grid.setVerticalSpacing(sp(STAT_ROW_SPACING))
        self.card_grid.setContentsMargins(0, 0, 0, 0)
        for col in range(3):
            self.card_grid.setColumnStretch(col, 1)

        self.type_field = StatField("Type", width=None, wrap=True, dynamic_anchor=True)
        self.mana_field = StatField(
            "Mana Cost", width=None, align=Qt.AlignHCenter, wrap=True
        )
        self.card_grid.addWidget(
            self.type_field, 0, 0, 1, 2
        )  # row 0, col 0, spans 2 columns
        self.card_grid.addWidget(self.mana_field, 0, 2)

        self.edition_field = StatField(
            "Edition", width=None, clickable=True, align=Qt.AlignHCenter
        )
        self.rarity_field = StatField("Rarity", width=None, align=Qt.AlignHCenter)
        self.price_field = StatField(
            "Price", width=None, clickable=True, align=Qt.AlignHCenter
        )
        self.card_grid.addWidget(self.edition_field, 1, 0)
        self.card_grid.addWidget(self.rarity_field, 1, 1)
        self.card_grid.addWidget(self.price_field, 1, 2)

        # Wired up right after Edition's field exists: a genuine
        # single-column (colspan=1) cell in the SAME grid Type can query
        # directly for "how wide is column 0, really" -- see
        # set_grid_anchor()'s docstring.
        self.type_field.set_grid_anchor(self.card_grid, anchor_row=1, anchor_col=0)

        self.language_field = StatField(
            "Language", width=None, clickable=True, align=Qt.AlignHCenter, wrap=True
        )
        self.condition_field = StatField(
            "Condition", width=None, clickable=True, align=Qt.AlignHCenter, wrap=True
        )
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
        layout.addSpacing(sp(STAT_ROW_SPACING))

        # Applies the currently-selected Edition/Language/Condition/Foil
        # back onto the actual collection entry (see _apply_changes) --
        # without this there was no way to actually CHANGE what a card in
        # Card Database is recorded as, only preview different options.
        # Deliberately doesn't close the dialog
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
        apply_button.setStyleSheet(_apply_button_style())
        apply_button.clicked.connect(self._apply_changes)
        apply_row.addWidget(self.apply_feedback_label)
        apply_row.addStretch()
        apply_row.addWidget(apply_button)
        layout.addLayout(apply_row)

        layout.addSpacing(sp(6))
        layout.addWidget(_hline())
        layout.addSpacing(sp(6))

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
        self.legality_list.setWordWrap(
            True
        )  # fallback for anything the fixed width still can't fit
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
            (
                f"{fmt}:  {status.replace('_', ' ').title()}"
                for fmt in FORMATS
                for status in LEGALITY_COLORS
            ),
            key=lambda text: metrics.horizontalAdvance(text),
        )
        return (
            metrics.horizontalAdvance(widest) + sp(44)
        )  # padding for list margins + scrollbar

    def _build_rulings_pane(self):
        layout = self._pane_layout("Rulings")
        self.rulings_list = QListWidget()
        self.rulings_list.setWordWrap(True)
        # At least as wide as the Legality pane, rather than left to
        # whatever share of the row a stretch factor happens to leave it --
        # a pane holding rulings text shouldn't end up narrower than one
        # holding a short "format: status" list.
        self.rulings_list.setMinimumWidth(self._legality_column_width())
        layout.addWidget(self.rulings_list)
        return layout

    def _build_edition_menu(self):
        menu = QMenu(self)
        for i, print_info in enumerate(self.prints):
            action = menu.addAction(
                f"{print_info['set'].upper()}  ({print_info['rarity']})"
            )
            action.triggered.connect(
                lambda checked=False, idx=i: self._select_print(idx)
            )
        self.edition_field.set_menu(menu)

    def _build_price_menu(self):
        menu = QMenu(self)
        for source_key, label in PRICE_SOURCES:
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, k=source_key: self._select_price_source(k)
            )
        self.price_field.set_menu(menu)

    def _build_language_menu(self):
        menu = QMenu(self)
        for lang in LANGUAGES:
            action = menu.addAction(lang)
            action.triggered.connect(
                lambda checked=False, l=lang: self._select_language(l)
            )
        self.language_field.set_menu(menu)

    def _build_condition_menu(self):
        menu = QMenu(self)
        for cond in CONDITIONS:
            action = menu.addAction(cond)
            action.triggered.connect(
                lambda checked=False, c=cond: self._select_condition(c)
            )
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
        self.price_field.set_text(f"${print_info.get(self.price_source, 0):.2f}")
        self.oracle_text_label.setText(self.oracle["oracle_text"])
        self.flavor_text_label.setText(print_info.get("flavor_text", ""))
        self.art_box.set_color(swatch_for_card(self.oracle))

    def _populate_legality(self):
        legalities = get_card_legalities(self.oracle["name"])
        for fmt in FORMATS:
            status = legalities.get(fmt, "not_legal")
            item = QListWidgetItem(f"{fmt}:  {status.replace('_', ' ').title()}")
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
