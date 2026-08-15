"""
frameless_dialog.py
--------------------
Shared base for popup windows that shouldn't pretend to be their own
separate application: no OS title bar, a thin custom title bar (name +
close button, draggable), and auto-close on a genuine click in the main
app window. Used by CardDetailDialog and TagApplyDialog (via
dialog_common.py's VerticalTabDialog, by Options and Data Management too)
so the click-outside-closes logic -- slightly fiddly to get right -- lives
in exactly one place.

See _TitleBar and FramelessDialog.eventFilter for the two tricky bits:
dragging without a native title bar, and telling "a click in the real main
window" apart from "a click inside this dialog" or "inside a transient
popup menu this dialog opened" (a QMenu's own `.window()` is the menu
itself, not the main window, so choosing a dropdown option never
accidentally closes the dialog mid-click).

show_title: the title bar is always needed as a drag handle + close
button, but the TEXT it shows is optional -- False lets a dialog put its
own heading directly in the content pane instead (CardDetailDialog does
this: the card's name is styled bigger/bolder as the Card pane's own
header, so it isn't shown twice). Defaults to True, which is what
TagApplyDialog relies on to show "Apply Tags" in the title bar.

Bar height/margins/close-button metrics are sp()-scaled and reapplied
live on scale_manager.scale_changed; the title text rides the app-wide
scaled default font instead of a hardcoded px size -- see scaling.py.
"""

from PySide6.QtWidgets import QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QApplication
from PySide6.QtCore import Qt, QEvent

from scaling import scale_manager, sp


def _close_button_style():
    """Built as a function, not a module-level string constant, for the
    same live-rescaling reason build_stylesheet() in main.py is a
    function -- see that module's comment. Re-called on every scale
    change (see _TitleBar._apply_scale)."""
    return (
        f"QToolButton {{ border: none; padding: {sp(4)}px {sp(8)}px; "
        f"border-radius: {sp(3)}px; }} "
        "QToolButton:hover { background-color: #a83a3a; color: white; }"
    )


class _TitleBar(QWidget):
    """
    Stands in for the OS title bar: shows a name and a close button, and is
    itself the drag handle (press-and-drag anywhere on it moves the window,
    same as dragging a native title bar would).

    When show_title=False, the name label is skipped entirely (not just
    hidden -- never constructed) so the bar collapses down to just the
    close button, still draggable via any of its remaining empty space.
    """

    def __init__(self, title, on_close, show_title=True):
        super().__init__()
        self.setFixedHeight(sp(34))
        self._drag_offset = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(sp(10), 0, sp(6), 0)

        if show_title:
            # No explicit px font-size -- 15px was previously hardcoded
            # here, which (like main.py's old QWidget rule) would have
            # silently pinned this label's size regardless of
            # text_scale. font-weight only; size comes from the scaled
            # app-wide default font (see scaling.py), just bumped via a
            # relative point-size offset so the title still reads as
            # slightly larger than body text at any scale.
            name_label = QLabel(title)
            title_font = name_label.font()
            title_font.setPointSizeF(title_font.pointSizeF() * 1.15)
            title_font.setBold(True)
            name_label.setFont(title_font)
            layout.addWidget(name_label)
            self._title_label = name_label
        else:
            self._title_label = None

        layout.addStretch()

        close_button = QToolButton()
        close_button.setText("\u2715")  # ✕
        close_button.setStyleSheet(_close_button_style())
        close_button.clicked.connect(on_close)
        layout.addWidget(close_button)
        self._close_button = close_button

        # Live rescaling: bar height, margins, and the close button's own
        # padding/border-radius (baked into its QSS string) all need to
        # be reapplied when ui_scale changes -- the title label's font
        # size is relative to the app default font and updates for free
        # via text_scale, so it needs no explicit handling here.
        scale_manager.scale_changed.connect(self._apply_scale)

    def _apply_scale(self):
        self.setFixedHeight(sp(34))
        self.layout().setContentsMargins(sp(10), 0, sp(6), 0)
        self._close_button.setStyleSheet(_close_button_style())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().pos()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None


class FramelessDialog(QDialog):
    """
    Base class: frameless window + custom title bar + click-outside-closes.
    Subclasses build their real content into self.content_layout (already
    margined) rather than setting their own top-level layout on the dialog.
    """

    def __init__(self, title, parent=None, show_title=True):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)

        # Remembered so the click-outside-closes check in eventFilter() can
        # tell "a click landed in the actual main window" apart from "a
        # click landed inside this dialog" or "inside a popup menu this
        # dialog opened."
        self._app_window = parent.window() if parent is not None else None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(_TitleBar(title, self.close, show_title=show_title))

        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(12, 8, 12, 12)
        outer.addLayout(self.content_layout)

        QApplication.instance().installEventFilter(self)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.MouseButtonPress and self._app_window is not None
                and isinstance(watched, QWidget) and watched.window() is self._app_window):
            self.close()
        return super().eventFilter(watched, event)
