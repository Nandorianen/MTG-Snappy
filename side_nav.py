"""
side_nav.py
-----------
The left-hand tab strip. Deliberately built as plain checkable QPushButtons
in a QButtonGroup rather than QTabWidget/QTabBar -- Qt's built-in tab widgets
are designed to sit ABOVE their content as a horizontal strip; getting them
to behave as a narrow VERTICAL sidebar fights the widget rather than using
it. A button group gives the same "exactly one active at a time" behavior
with layout that matches what you actually want.

Width/margins/spacing are all sp()-scaled and re-applied live on
scale_manager.scale_changed -- see scaling.py.

TEXT WRAPPING AT HIGH text_scale: QPushButton has no native word-wrap
property (the same gap card_detail_popup.py already worked around for
QToolButton -- see that module's _wrap_to_pixel_width). At a high enough
text_scale, a label like "Tag Database" no longer fits sp(140)'s width on
one line and would otherwise just get silently clipped by Qt's own text
painting -- there's no ui_scale fix for that, since it's the FONT that
grew, not the available space. Every button's text is re-wrapped (manual
"\n"-insertion, same technique) against the CURRENT font metrics and
width budget both at construction and on every scale_changed -- see
_refresh_button_labels. Embedded newlines render as real multiple lines
on a QPushButton exactly as they already do on a QToolButton elsewhere in
this app.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QButtonGroup
from PySide6.QtCore import Signal
from PySide6.QtGui import QFontMetrics

from scaling import scale_manager, sp

# (internal key, display label) -- the key is what gets emitted on view_changed
# and is what main.py uses to decide which widget to show in the QStackedWidget.
# Order here is also the order Ctrl-less digit shortcuts 1/2/3 map to (see
# main.py's _handle_digit_shortcut) and the order tabs appear top-to-bottom.
TABS = [
    ("cards", "Card Database"),
    ("tags", "Tag Database"),
    ("decks", "Deck Viewer"),
]


def _wrap_to_pixel_width(text, pixel_width, font_metrics):
    """
    Manual word-wrap for QPushButton text -- duplicated from card_detail_
    popup.py's identical helper (used there for QToolButton's Condition/
    Language fields) rather than imported: it's a small, pure,
    dependency-free function with no other coupling to either module, and
    importing a leading-underscore "private" helper across two otherwise
    unrelated UI modules would be a stranger dependency than just
    repeating six lines. Breaks on whitespace, joins with a real "\\n" --
    QPushButton renders embedded newlines as separate lines the same way
    QToolButton does, even without QLabel's setWordWrap(True) (which
    QPushButton has no equivalent of).
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


class SideNav(QWidget):
    view_changed = Signal(str)  # emits one of the keys above

    # Rough per-side budget subtracted from sp(140) when deciding how much
    # horizontal room a button's TEXT actually has to work with -- covers
    # SideNav's own layout margin (sp(6) each side) plus a QPushButton's
    # native default internal padding (this app doesn't explicitly style
    # these buttons, so this is an estimate, not an exact figure). Slightly
    # UNDER-estimating available width (wrapping a touch earlier than
    # strictly necessary) is a far smaller problem than over-estimating it
    # (text silently clipped again) -- not worth chasing an exact pixel
    # number for a rough wrap budget.
    _TEXT_WIDTH_PADDING = 28

    def __init__(self):
        super().__init__()
        self.setFixedWidth(sp(140))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(sp(6), sp(6), sp(6), sp(6))
        layout.setSpacing(sp(4))
        # Live rescaling: re-derive the fixed width and margins whenever
        # ui_scale changes (Ctrl+wheel or Options' slider) -- setFixedWidth
        # and setContentsMargins were both one-shot calls above, so
        # without this the nav strip would stay stuck at whatever width
        # was active when the app launched.
        scale_manager.scale_changed.connect(self._apply_scale)

        # key -> original (unwrapped) label -- _refresh_button_labels
        # always re-wraps from this, never from whatever a button's text
        # currently shows, so repeated scale changes (grow, then shrink)
        # never compound leftover "\n"s from an earlier wrap.
        self._labels = {key: label for key, label in TABS}
        self.buttons = {}  # key -> QPushButton, so shortcuts can trigger them by key
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)  # only one checked at a time -- this IS the "tab" behavior

        for key, label in TABS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked, k=key: self._on_clicked(k))
            self.button_group.addButton(button)
            self.buttons[key] = button
            layout.addWidget(button)

        layout.addStretch()
        # Deliberately NO default-checked button: the app opens with nothing
        # selected and an empty placeholder pane in the main content area
        # (see main.py) until the user actually picks a tab. QButtonGroup
        # with setExclusive(True) is fine left with none checked -- that
        # only constrains "at most one checked," not "always exactly one."

        self._refresh_button_labels()

    def _apply_scale(self):
        self.setFixedWidth(sp(140))
        self.layout().setContentsMargins(sp(6), sp(6), sp(6), sp(6))
        self.layout().setSpacing(sp(4))
        self._refresh_button_labels()

    def _refresh_button_labels(self):
        """
        Re-wraps every button's text against the CURRENT font (text_scale,
        via each button's own .font(), which already reflects the live
        app-wide default font) and CURRENT width budget (ui_scale, via
        sp(140)) -- called once at construction and again on every
        scale_changed, so a label that used to fit on one line gets
        re-wrapped the moment text_scale (or the nav's own width) grows
        past what it can hold, and un-wraps again if scale shrinks back.
        """
        width_budget = max(20, sp(140) - sp(self._TEXT_WIDTH_PADDING))
        for key, button in self.buttons.items():
            metrics = QFontMetrics(button.font())
            button.setText(_wrap_to_pixel_width(self._labels[key], width_budget, metrics))

    def _on_clicked(self, key):
        self.view_changed.emit(key)

    def select_tab(self, key):
        """Called by main.py's digit shortcuts (1/2/3, no Ctrl -- see
        this module's own docstring) to switch tabs programmatically."""
        button = self.buttons.get(key)
        if button and not button.isChecked():
            button.setChecked(True)
            self._on_clicked(key)
