"""
collapsible_pane.py
--------------------
CollapsibleSplitter wraps ANY left widget + right widget pair with:
  - drag-to-resize (QSplitter's native behavior),
  - a small arrow zone at the top of the divider that toggles collapse
    with a single click, without needing to drag the divider to zero,
  - collapsing when the LEFT is already collapsed... no -- collapsing
    the LEFT pane specifically when the user clicks anywhere in the RIGHT
    widget's contents,
  - collapsing on Tab (a placeholder binding, as you said -- easy to
    rebind later; see the `event()` override below for why Tab specifically
    needs special handling).

This class deliberately knows NOTHING about trees, decks, or tags -- it just
holds "widget A" and "widget B." That's what makes it reusable for the Deck
Viewer and Tag Database views today, and for anything else later that wants
a collapsible sidebar (e.g. a future filter panel).

WHY TAB NEEDS event() INSTEAD OF keyPressEvent():
Qt intercepts the Tab key very early, before it ever reaches a widget's
keyPressEvent(), to implement "move focus to the next widget." Overriding
keyPressEvent() to catch Key_Tab would never actually run. The fix is to
override event() itself and consume the QKeyEvent for Key_Tab before Qt's
own focus-traversal logic gets a chance to act on it. This is a real Qt
quirk worth knowing about any time a shortcut refuses to fire and Tab is
involved.
"""

from PySide6.QtWidgets import QSplitter, QSplitterHandle, QApplication
from PySide6.QtCore import Qt, QEvent, QRect
from PySide6.QtGui import QPainter, QColor

ARROW_ZONE_HEIGHT = 18  # pixels of the handle reserved for the click-to-toggle arrow


class _CollapseHandle(QSplitterHandle):
    """
    The draggable divider between the two panes, with a small toggle zone
    pinned to its top. Everywhere OUTSIDE that zone behaves like a normal
    QSplitter handle (drag to resize); only the small zone intercepts the
    click to toggle collapse instead.
    """

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        splitter = self.splitter()
        arrow_rect = QRect(0, 0, self.width(), min(ARROW_ZONE_HEIGHT, self.height()))
        painter.fillRect(arrow_rect, QColor("#3a3c41"))
        arrow_glyph = "▸" if splitter.is_collapsed() else "◂"
        painter.setPen(QColor("#e3e3e3"))
        painter.drawText(arrow_rect, Qt.AlignCenter, arrow_glyph)

    def mousePressEvent(self, event):
        arrow_zone = QRect(0, 0, self.width(), min(ARROW_ZONE_HEIGHT, self.height()))
        if arrow_zone.contains(event.pos()):
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
        # minimum width instead of reaching 0. So this has to be True for
        # our OWN collapse()/expand() methods to work, not just for drag.
        self.setCollapsible(0, True)
        self.setCollapsible(1, True)

        # A click anywhere inside the right widget (or any of ITS children --
        # e.g. a cell inside a QTableView living inside right_widget) should
        # collapse the left pane. Per-widget event filters don't reach into
        # child widgets automatically, so we filter at the application level
        # and check ancestry instead.
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

    def event(self, e):
        if e.type() == QEvent.KeyPress and e.key() == Qt.Key_Tab:
            self.toggle()
            return True
        return super().event(e)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.MouseButtonPress
                and not self._collapsed
                and (watched is self._right_widget or self._right_widget.isAncestorOf(watched))):
            self.collapse()
        return super().eventFilter(watched, event)
