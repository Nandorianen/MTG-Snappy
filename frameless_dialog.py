"""
frameless_dialog.py
--------------------
Shared base for popup windows that shouldn't pretend to be their own
separate application: no OS title bar, a thin custom title bar (name +
close button, draggable), and auto-close on a genuine click in the main
app window. Originally built just for CardDetailDialog; pulled out here so
TagApplyDialog can share the exact same (slightly fiddly to get right)
click-outside-closes logic instead of duplicating it.

See _TitleBar and FramelessDialog.eventFilter for the two tricky bits:
dragging without a native title bar, and telling "a click in the real main
window" apart from "a click inside this dialog" or "inside a transient
popup menu this dialog opened" (a QMenu's own `.window()` is the menu
itself, not the main window, so choosing a dropdown option never
accidentally closes the dialog mid-click).
"""

from PySide6.QtWidgets import QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QApplication
from PySide6.QtCore import Qt, QEvent


class _TitleBar(QWidget):
    """
    Stands in for the OS title bar: shows a name and a close button, and is
    itself the drag handle (press-and-drag anywhere on it moves the window,
    same as dragging a native title bar would).
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


class FramelessDialog(QDialog):
    """
    Base class: frameless window + custom title bar + click-outside-closes.
    Subclasses build their real content into self.content_layout (already
    margined) rather than setting their own top-level layout on the dialog.
    """

    def __init__(self, title, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)

        # Remembered so the click-outside-closes check in eventFilter() can
        # tell "a click landed in the actual main window" apart from "a
        # click landed inside this dialog" or "inside a popup menu this
        # dialog opened."
        self._app_window = parent.window() if parent is not None else None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(_TitleBar(title, self.close))

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
