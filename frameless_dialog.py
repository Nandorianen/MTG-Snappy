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

SCREEN-SAFE AT HIGH SCALE -- THREE PIECES, ALL LIVE HERE SO EVERY
FRAMELESS DIALOG GETS THEM FOR FREE:
1. resize() is overridden to clamp whatever size a subclass asks for
   (CardDetailDialog's sp(900)x sp(560), OptionsDialog's sp(760)x
   sp(500), ...) to the CURRENT screen's available geometry (minus a
   margin) before applying it -- a high ui_scale/text_scale on a small
   screen can no longer push a dialog's edges (or its close button)
   off-screen where they'd be unreachable. Every subclass's existing
   `self.resize(...)` call is intercepted transparently; no subclass
   needed to change.
2. self.content_layout (where every subclass builds its real content)
   now lives inside a QScrollArea rather than being added straight to
   the dialog -- so content that's still too big for the CLAMPED size
   from point 1 scrolls (both directions, Qt's default
   ScrollBarAsNeeded policy) instead of being silently clipped or
   forcing the window bigger than the screen.
3. _grow_to_fit_content() grows the window to match what its OWN content
   actually needs (up to the same screen clamp from point 1) instead of
   staying pinned at a subclass's design-time sp(W)/sp(H) guess -- that
   guess was tuned around a "normal" text_scale, so at a HIGHER text
   scale the real content can outgrow it well before the screen does,
   which used to show scrollbars for space that was genuinely free on
   the desktop. Run once synchronously on showEvent (before any
   subclass's own deferred singleShot(0) post-show work, e.g.
   CardDetailDialog's column-locking -- see _grow_to_fit_content's own
   docstring for why synchronous-at-showEvent specifically), and again,
   debounced, on every scale_changed while the dialog is already open
   (e.g. a user resizing an already-open Options dialog via its own
   sliders).
   Point 2 is what makes point 3 not load-bearing: even if a screen were
   somehow too small for the growth this computes, resize()'s own clamp
   (point 1) still applies, and the scroll area (point 2) is still there
   as the real fallback. Growing to fit content is a NICETY on top of
   that -- avoiding a scrollbar when the desktop plainly has room -- not
   a second, independent safety mechanism.
"""

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton,
    QApplication, QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, QEvent, QTimer

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

    # Floor for the screen-clamp in resize() below -- keeps an extreme
    # low ui_scale combined with a small screen from clamping a dialog
    # down to something too cramped to actually use.
    _MIN_CLAMPED_WIDTH = 320
    _MIN_CLAMPED_HEIGHT = 200
    # Reserved border around a maximally-clamped dialog so it still shows
    # a sliver of desktop/taskbar at the screen's edges rather than
    # touching every edge exactly.
    _SCREEN_CLAMP_MARGIN = 40

    # Small safety margin added on top of the MEASURED content size in
    # _grow_to_fit_content -- QWidget.sizeHint() and the real pixel size a
    # QScrollArea ultimately settles on aren't always identical to the
    # last pixel (scrollbar reservation, layout rounding), and landing
    # a few pixels short would defeat the whole point by still showing a
    # scrollbar for a sliver of overflow. Erring slightly larger costs
    # nothing visible; landing exactly on the boundary risks the bug this
    # exists to fix.
    _GROW_BUFFER = 24

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
        self._title_bar = _TitleBar(title, self.close, show_title=show_title)
        outer.addWidget(self._title_bar)

        # Real content lives on a plain QWidget, built via self.content_
        # layout exactly as every subclass already expects -- the
        # QScrollArea wrapping below is invisible to subclasses, which
        # still just add widgets/layouts to self.content_layout.
        self._content_widget = QWidget()
        self.content_layout = QVBoxLayout(self._content_widget)
        self.content_layout.setContentsMargins(12, 8, 12, 12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)  # content grows to fill a larger dialog; only scrolls once it can't shrink further
        scroll.setFrameShape(QFrame.NoFrame)  # no extra bezel -- this app draws its own borders via QSS elsewhere
        scroll.setWidget(self._content_widget)
        outer.addWidget(scroll, stretch=1)

        QApplication.instance().installEventFilter(self)

        # Grows to fit content once it's already open and a scale change
        # happens (e.g. dragging Options' own sliders while Options is
        # the window being resized) -- debounced via a plain singleShot
        # rather than reacting synchronously, so it runs AFTER whatever
        # else is connected to scale_changed (a subclass's own formula-
        # driven _apply_dialog_scale, if it has one) has already set its
        # preferred size for the new scale; this only tops that up
        # further if the actual content still needs more room. A no-op,
        # cheap check while the dialog is hidden (isVisible() False) --
        # a freshly (re)opened dialog gets sized correctly from scratch
        # via showEvent below instead.
        scale_manager.scale_changed.connect(self._queue_grow_to_fit_content)

    def showEvent(self, event):
        """
        Grows the window to fit its own content, synchronously, before
        anything else runs off this show -- see the class docstring's
        "SCREEN-SAFE AT HIGH SCALE" point 3. Deliberately synchronous
        (not deferred via QTimer.singleShot the way the scale_changed
        path above is): QWidget.sizeHint() is a pure, recursive
        computation over the layout tree's own preferred sizes -- unlike
        reading a widget's real .width()/.height() after an actual layout
        pass (see e.g. StatField.set_text()'s own "self.width() may be
        stale" comment in card_detail_popup.py, a case where THAT
        distinction matters), sizeHint() doesn't need Qt to have actually
        rendered anything yet, so it's safe to read right here. Running
        it synchronously (not queued) also matters for ordering: some
        subclasses queue their OWN post-show work via singleShot(0) during
        __init__ (CardDetailDialog's _settle_after_first_layout, which
        measures/locks pixel widths off the dialog's CURRENT size) -- a
        synchronous resize during showEvent is guaranteed to complete
        before any singleShot(0) queued earlier in __init__ gets its turn
        on the event loop, so those subclasses never race this.
        """
        super().showEvent(event)
        self._grow_to_fit_content()

    def _queue_grow_to_fit_content(self):
        if self.isVisible():
            QTimer.singleShot(0, self._grow_to_fit_content)

    def _grow_to_fit_content(self):
        """
        If what's actually built into content_layout needs more room than
        the window currently has (typically: a subclass's design-time
        sp(W)/sp(H) guess, tuned around a "normal" text_scale, no longer
        covering the real content at a HIGHER text_scale), grows the
        window to fit -- rather than leaving the QScrollArea wrapping
        content_layout to show scrollbars for room that's genuinely free
        on the desktop. Grows ONLY (never shrinks below whatever size is
        already set -- a subclass's own design-time size is a floor, not
        just a starting suggestion) and is itself still subject to
        resize()'s own screen-clamp, so this still falls back to real
        scrolling once even the SCREEN doesn't have room for it.
        """
        content_hint = self._content_widget.sizeHint()
        # _title_bar.height() (not .sizeHint()) -- setFixedHeight() locks
        # the bar's REAL height immediately at construction; its
        # sizeHint() is a separate, layout-derived value that isn't
        # guaranteed to match that fixed height exactly, so reading the
        # actual enforced height is the reliable number here.
        title_height = self._title_bar.height()
        target_width = max(self.width(), content_hint.width() + self._GROW_BUFFER)
        target_height = max(self.height(), content_hint.height() + title_height + self._GROW_BUFFER)
        if target_width > self.width() or target_height > self.height():
            self.resize(target_width, target_height)

    def resize(self, width, height=None):
        """
        Clamps the requested size to the CURRENT screen's available
        geometry (minus _SCREEN_CLAMP_MARGIN, floored at _MIN_CLAMPED_*)
        before applying it -- see this class's own docstring ("SCREEN-SAFE
        AT HIGH SCALE") for why. Overriding resize() itself (rather than
        adding a separate clamp-and-resize helper) is what makes every
        existing subclass call site -- CardDetailDialog's `self.resize(
        sp(900), sp(560))`, OptionsDialog's `self.resize(sp(760),
        sp(500))`, etc. -- get this for free with no changes needed at
        those call sites.

        Accepts either resize(w, h) or resize(QSize), matching both
        forms QWidget.resize() itself supports and both forms already in
        use across this codebase.
        """
        if height is None:
            size = width
            width, height = size.width(), size.height()
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            width = max(self._MIN_CLAMPED_WIDTH, min(width, avail.width() - self._SCREEN_CLAMP_MARGIN))
            height = max(self._MIN_CLAMPED_HEIGHT, min(height, avail.height() - self._SCREEN_CLAMP_MARGIN))
        super().resize(width, height)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.MouseButtonPress and self._app_window is not None
                and isinstance(watched, QWidget) and watched.window() is self._app_window):
            self.close()
        return super().eventFilter(watched, event)
