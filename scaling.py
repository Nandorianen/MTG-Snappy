"""
scaling.py
----------
Central runtime scaling infrastructure -- goal #3 ("full keyboard/UX...
implies working across variable text scaling/DPI too, not just one
reference window size (flagged, not yet acted on)") and goal #4 (UI
scale as part of "maximum customizability"), see PROJECT_CONTEXT.md.

ARCHITECTURE: ONE GLOBAL SIGNAL, NOT A CASCADE OF INDIVIDUAL SETTERS.
`scale_manager` (module-level singleton, below) holds two INDEPENDENT
floats -- `ui_scale` (spacing/icon/fixed-widget sizing) and `text_scale`
(font point size) -- and a single `scale_changed` Qt signal fired
whenever EITHER changes. Every window/dialog/widget that cares about
live-rescaling connects to that ONE signal and re-derives its own sizes
when it fires, rather than each scale-aware widget inventing its own
notification path. Same "one shared authority" shape as SideNav's TABS
list or CardTableModel's filter state feeding both the header checklist
and the Inventory/Wishlist buttons -- applied here to a new axis.

WHY TWO INDEPENDENT SCALES, NOT ONE: a user with fine eyesight but a
cramped high-DPI laptop screen might want smaller text with normal-sized
click targets, or the reverse. Two numbers (rather than one "UI scale"
driving both) is what makes that combination expressible at all -- see
options_dialog.py's Interface tab for the two separate sliders.

WHAT EACH SCALE ACTUALLY DRIVES:
  - text_scale -> QApplication's default font POINT SIZE (_apply_font_
    scale). Qt's own layout system already reflows around a font-size
    change for anything built with layouts + QFontMetrics -- which is
    most of this app -- so this axis is close to "free": no per-widget
    code needed beyond the one setFont() call here.
  - ui_scale   -> every hardcoded PIXEL constant that ISN'T text (icon
    sizes, fixed widget widths, margins/padding baked into QSS strings,
    dialog default sizes, the sort-arrow/filter-dot paint zones in
    CardTableHeader, ...) via the sp()/scaled_font_px() helpers below.
    NOTHING about this axis is automatic: every call site that used to
    write a bare pixel literal needs to call sp(that literal) instead,
    evaluated AT USE TIME (paint/layout time), not once at import time
    -- a module-level `WIDTH = sp(28)` would freeze at whatever scale
    happened to be active when the module first imported, defeating live
    rescaling entirely. See NOTES.md's "Scaling infrastructure" entry
    for the current per-file conversion status; this is a large,
    ongoing pass (established one-feature-at-a-time, like everything
    else in this app -- see PROJECT_CONTEXT.md), not a single mechanical
    find-replace, since not every bare number in this codebase is a
    size (some are counts, indices, sentinel widths, etc).

RUNTIME-ONLY FOR NOW: no persistence -- Options' "real settings store" is
still TODO (PROJECT_CONTEXT.md's Roadmap). Every scale change here takes
effect immediately and is lost on restart; that's an explicit, deliberate
scope cut for this round, not an oversight.

CTRL+WHEEL: ui_scale and text_scale move TOGETHER, one notch per wheel
click (adjust_combined) -- a single combined "zoom," matching the
familiar browser/OS Ctrl+wheel convention, rather than needing a second
modifier to reach one axis independently from the mouse. Splitting them
apart is what the Options dialog's two separate sliders are for. See
main.py's MainWindow.eventFilter for where this is actually caught
(extends the same app-level-eventFilter pattern this codebase already
uses for Tab interception, digit shortcuts, etc. -- see NOTES.md's
debugging-lessons #4).
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

# Clamp range for both scales -- generous enough to be genuinely useful
# (a 4K-on-a-14"-laptop user going small, a low-vision user going large)
# without letting a runaway scroll/slider produce an unusably tiny or
# huge interface.
MIN_SCALE = 0.7
MAX_SCALE = 2.0

# One Ctrl+wheel "notch" (one discrete scroll step -- see
# adjust_combined's use of angleDelta()) moves either scale by this much.
# The Options sliders move continuously instead, in finer steps -- see
# options_dialog.py's _build_ui_page.
WHEEL_STEP = 0.05

# The point size every text_scale multiplier is measured FROM. Read once
# at startup from whatever the platform's own default QFont already
# reports (see init_from_app), rather than hardcoding a guessed number --
# a Windows/macOS/Linux default point size can legitimately differ, and
# "1.0x text scale" should mean "whatever this OS/Qt already considered
# normal," not one specific value baked into this file.
_base_point_size = 9.0  # placeholder until init_from_app() runs at startup


class ScaleManager(QObject):
    """Holds the two current scale factors and notifies listeners of any
    change. See this module's own docstring for the overall design."""

    scale_changed = Signal()

    def __init__(self):
        super().__init__()
        self.ui_scale = 1.0
        self.text_scale = 1.0

    # --- UI (non-text) scaling -------------------------------------------
    def sp(self, px):
        """
        Scales a design-time pixel constant by the current ui_scale,
        rounded to the nearest whole pixel (Qt widget geometry is
        integer-based; fractional pixels aren't meaningful here). THE one
        function every fixed-size/spacing/margin/icon-size constant in
        this app should route through at the point of use, instead of a
        bare literal -- see this module's docstring for why "at the point
        of use" specifically (not once at import time) matters for live
        rescaling. Clamped to a 1px floor so an extreme low ui_scale can
        never collapse something down to 0 (invisible / division-by-zero
        risk in anything that derives further math from it).
        """
        return max(1, round(px * self.ui_scale))

    def set_ui_scale(self, value):
        value = min(MAX_SCALE, max(MIN_SCALE, value))
        if value == self.ui_scale:
            return
        self.ui_scale = value
        self.scale_changed.emit()

    # --- Text scaling ------------------------------------------------------
    def set_text_scale(self, value):
        value = min(MAX_SCALE, max(MIN_SCALE, value))
        if value == self.text_scale:
            return
        self.text_scale = value
        self._apply_font_scale()
        self.scale_changed.emit()

    def _apply_font_scale(self):
        """
        Rewrites QApplication's default font point size. Every widget
        using the default font (true for nearly all of this app -- the
        few explicit setStyleSheet font-weight/color rules scattered
        around don't set an explicit POINT SIZE, so they still inherit
        this) picks the change up automatically the instant it's set;
        Qt re-runs layout for anything sized off font metrics with no
        further code needed here. setPointSizeF (not setPointSize) is
        used so a fractional scale (e.g. 0.85x) doesn't get silently
        rounded away before it ever reaches Qt.
        """
        app = QApplication.instance()
        if app is None:
            return
        font = app.font()
        font.setPointSizeF(_base_point_size * self.text_scale)
        app.setFont(font)

    # --- Combined Ctrl+wheel zoom -----------------------------------------
    def adjust_combined(self, steps):
        """Moves BOTH scales by `steps` wheel notches at once -- see the
        module docstring's CTRL+WHEEL section for why this is one
        combined zoom rather than two independent adjustments. `steps`
        can be negative (wheel down = zoom out)."""
        delta = WHEEL_STEP * steps
        ui_value = min(MAX_SCALE, max(MIN_SCALE, self.ui_scale + delta))
        text_value = min(MAX_SCALE, max(MIN_SCALE, self.text_scale + delta))
        if ui_value == self.ui_scale and text_value == self.text_scale:
            return  # already clamped at the limit in this direction
        self.ui_scale = ui_value
        self.text_scale = text_value
        self._apply_font_scale()
        self.scale_changed.emit()

    def reset(self):
        """Back to 1.0x / 1.0x -- wired to a Reset button in Options
        alongside the two sliders."""
        if self.ui_scale == 1.0 and self.text_scale == 1.0:
            return
        self.ui_scale = 1.0
        self.text_scale = 1.0
        self._apply_font_scale()
        self.scale_changed.emit()


def init_from_app(app):
    """
    Call ONCE, immediately after QApplication is constructed and before
    any window is built (see main.py's main()). Records the platform's
    own real default point size as the 1.0x baseline -- see
    `_base_point_size`'s own comment for why this isn't just hardcoded --
    then applies the manager's current scale on top of it, so app.font()
    is correct from the very first frame rather than needing a later
    scale change to first take effect.
    """
    global _base_point_size
    _base_point_size = app.font().pointSizeF() or 9.0
    scale_manager._apply_font_scale()


# Module-level singleton -- see this module's own docstring for why a
# single shared instance (not a per-window copy) is the right shape.
scale_manager = ScaleManager()


def sp(px):
    """Free-function shorthand for scale_manager.sp(px) -- lets call
    sites `from scaling import sp` instead of importing the manager
    just to reach one method."""
    return scale_manager.sp(px)
