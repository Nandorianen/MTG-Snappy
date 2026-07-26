"""
card_popover.py
----------------
The "separate view created on mouseover and/or click" you asked for --
currently just text plus a placeholder art swatch, since we don't have real
images yet. Kept as its own class for the same reason CardDetailPanel was
separate before: when real images arrive, only this file needs to change.

Qt.ToolTip as a window flag (passed to the constructor below) tells the OS
window manager to treat this as a transient, no-taskbar-entry, always-on-top
floating panel -- the same category of window a native tooltip uses. That's
the right category for "appears near the cursor, disappears when you move
away," which is different from a normal application window.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt

from mock_data import swatch_for_card


class CardPopover(QWidget):
    def __init__(self):
        # Passing `None` as parent + Qt.ToolTip as the window flag: no parent
        # means it isn't embedded inside another widget's layout (it floats
        # independently); Qt.ToolTip governs how the OS treats the window
        # (no border chrome, no taskbar icon, closes if it loses relevance).
        super().__init__(None, Qt.ToolTip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.art_box = QFrame()
        self.art_box.setFixedSize(160, 223)  # placeholder, same MTG-ish aspect ratio as before
        layout.addWidget(self.art_box)

        self.name_label = QLabel()
        self.name_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)

        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        self.text_label.setFixedWidth(200)
        layout.addWidget(self.text_label)

        # Popover's own background/border, independent of the main window's
        # stylesheet, since Qt.ToolTip windows sometimes don't inherit the
        # parent application's stylesheet consistently across platforms.
        self.setStyleSheet("""
            QWidget { background-color: #2b2d31; color: #e3e3e3; border: 1px solid #4a4d54; }
        """)

    def show_card(self, card, global_pos):
        self.name_label.setText(card["name"])
        self.text_label.setText(card["oracle_text"])
        swatch = swatch_for_card(card)
        self.art_box.setStyleSheet(f"background-color: {swatch}; border-radius: 6px; border: none;")
        self.move(global_pos)
        self.show()
        self.raise_()
