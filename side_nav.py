"""
side_nav.py
-----------
The left-hand tab strip. Deliberately built as plain checkable QPushButtons
in a QButtonGroup rather than QTabWidget/QTabBar -- Qt's built-in tab widgets
are designed to sit ABOVE their content as a horizontal strip; getting them
to behave as a narrow VERTICAL sidebar fights the widget rather than using
it. A button group gives the same "exactly one active at a time" behavior
with layout that matches what you actually want.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QButtonGroup
from PySide6.QtCore import Signal

# (internal key, display label) -- the key is what gets emitted on view_changed
# and is what main.py uses to decide which widget to show in the QStackedWidget.
TABS = [
    ("tags", "Tag Database"),
    ("inventory", "Inventory"),
    ("wishlist", "Wishlist"),
]


class SideNav(QWidget):
    view_changed = Signal(str)  # emits one of the keys above

    def __init__(self):
        super().__init__()
        self.setFixedWidth(140)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

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
        self.buttons["tags"].setChecked(True)  # default tab on startup

    def _on_clicked(self, key):
        self.view_changed.emit(key)

    def select_tab(self, key):
        """Called by main.py's Ctrl+1/2/3 shortcuts to switch tabs programmatically."""
        button = self.buttons.get(key)
        if button and not button.isChecked():
            button.setChecked(True)
            self._on_clicked(key)
