"""
collapsible_pane.py
--------------------
CollapsibleSplitter wraps ANY left widget + right widget pair with:
  - drag-to-resize (QSplitter's native behavior),
  - a tall arrow zone centered on the divider that toggles collapse with a
    single click, without needing to drag the divider to zero,
  - collapsing the LEFT pane when the user clicks anywhere in the RIGHT
    widget's contents,
  - collapsing on Tab (a placeholder binding, as you said -- easy to rebind
    later).

This class deliberately knows NOTHING about trees, decks, or tags -- it just
holds "widget A" and "widget B." That's what makes it reusable for the Deck
Viewer and Tag Database views today, and for anything else later that wants
a collapsible sidebar (e.g. a future filter panel).

WHY TAB IS HANDLED IN eventFilter() RATHER THAN keyPressEvent()/event():
An earlier version of this file caught Key_Tab in the SPLITTER's own
event() override. That worked in isolated tests (calling splitter.event()
directly) but not in the real app, and here's why: keyboard focus normally
sits on a CHILD widget -- the tree inside the left pane, or a table inside
the right pane -- not on the splitter itself. Qt delivers key events
directly to whichever widget currently has focus, and that widget's own
event() handling intercepts Tab internally to move focus to the next widget,
before the event ever bubbles up to a parent's event() override. So a
Key_Tab pressed while the tree has focus never reaches the splitter's
event() at all.
The fix: an application-level event filter (installed via
QApplication.installEventFilter) runs BEFORE the event reaches its target
widget's own event() handling, for every event in the whole application.
By checking here whether the event's target is this splitter or one of its
descendants, we can intercept and consume Key_Tab before Qt's internal
focus-traversal logic ever sees it -- regardless of which specific child
widget currently holds focus.
"""

from PySide6.QtWidgets import QSplitter, QSplitterHandle, QApplication
from PySide6.QtCore import Qt, QEvent, QRect
from PySide6.QtGui import QPainter, QColor

# Height of the clickable/painted toggle zone, centered vertically on the
# handle. ~4-5x a normal small icon size, per feedback that the original
# 18px zone was too small a target to reliably click.
ARROW_ZONE_HEIGHT = 90


class _CollapseHandle(QSplitterHandle):
    """
    The draggable divider between the two panes, with a tall toggle zone
    centered on it. Everywhere OUTSIDE that zone behaves like a normal
    QSplitter handle (drag to resize); only the zone itself intercepts the
    click to toggle collapse instead.
    """

    def _arrow_rect(self):
        zone_height = min(ARROW_ZONE_HEIGHT, self.height())
        zone_top = (self.height() - zone_height) // 2
        return QRect(0, zone_top, self.width(), zone_height)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        splitter = self.splitter()
        rect = self._arrow_rect()
        painter.setBrush(QColor("#3a3c41"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect.adjusted(1, 0, -1, 0), 4, 4)
        arrow_glyph = "▸" if splitter.is_collapsed() else "◂"
        painter.setPen(QColor("#e3e3e3"))
        painter.drawText(rect, Qt.AlignCenter, arrow_glyph)

    def mousePressEvent(self, event):
        if self._arrow_rect().contains(event.pos()):
            self.splitter().toggle()
            event.accept()
            return
        super().mousePressEvent(event)  # elsewhere on the handle: normal drag-resize


class CollapsibleSplitter(QSplitter):
    def __init__(self, left_widget, right_widget, default_left_width=220):
        super().__init__(Qt.Horizontal)
        self._left_widget = left_widget
        self._right_widget = right_widget
        self._expanded_width = default_left_width
        self._collapsed = False

        self.addWidget(left_widget)
        self.addWidget(right_widget)
        self.setSizes([default_left_width, 800])
        self.setHandleWidth(10)
        # NOTE: setCollapsible(index, True) is required here, and it means
        # something different than it sounds like. It doesn't just permit
        # dragging past the minimum size -- Qt also uses it to decide
        # whether setSizes() is ALLOWED to shrink a pane below its minimum
        # size hint programmatically. With collapsible=False, our own
        # collapse() calls below get silently clamped back to the widget's
        # minimum width instead of reaching 0.
        self.setCollapsible(0, True)
        self.setCollapsible(1, True)

        # One event filter handles BOTH "click in the right pane collapses"
        # and "Tab toggles collapse" -- see the module docstring for why
        # Tab specifically has to be caught this way rather than in a normal
        # keyPressEvent override.
        QApplication.instance().installEventFilter(self)

    def createHandle(self):
        return _CollapseHandle(self.orientation(), self)

    def is_collapsed(self):
        return self._collapsed

    def toggle(self):
        self.collapse() if not self._collapsed else self.expand()

    def collapse(self):
        if self._collapsed:
            return
        sizes = self.sizes()
        if sizes[0] > 0:
            self._expanded_width = sizes[0]
        self._collapsed = True
        self.setSizes([0, sum(sizes)])

    def expand(self):
        if not self._collapsed:
            return
        self._collapsed = False
        total = sum(self.sizes())
        self.setSizes([self._expanded_width, max(total - self._expanded_width, 100)])

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Tab:
            if watched is self or self.isAncestorOf(watched):
                self.toggle()
                return True  # consume -- stop Qt's default focus-next-widget behavior

        if (event.type() == QEvent.MouseButtonPress
                and not self._collapsed
                and (watched is self._right_widget or self._right_widget.isAncestorOf(watched))):
            self.collapse()

        return super().eventFilter(watched, event)
