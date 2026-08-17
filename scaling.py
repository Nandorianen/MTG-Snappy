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

WHY BOTH SCALES START AT A FLAT 1.0/1.0, NOT AN OS-DETECTED VALUE (a real
attempt, retracted -- see NOTES.md's "Scaling infrastructure" entry for
the full story): Qt6 (which PySide6 wraps) performs MANDATORY automatic
high-DPI scaling -- every widget's geometry is expressed in
device-independent pixels, and Qt itself multiplies that by the OS's own
display-scale setting (via QScreen.devicePixelRatio()) at render time,
completely transparently, before any of this app's own code ever runs.
That's why the app already looks correctly sized on e.g. a 125%-scaled
Windows display with ZERO code here -- Qt already did it. A first attempt
at this feature tried seeding ui_scale/text_scale from
QScreen.logicalDotsPerInch(), on the theory that it would reflect the
OS's chosen scale the way it did in the pre-Qt6 world -- verified,
on a real Windows 10 + 125%-scale + PySide6 machine, to read back
essentially the 96 DPI baseline instead (Qt6's mandatory scaling has
already "spent" the real scale factor on devicePixelRatio(), leaving
logicalDotsPerInch() normalized). Reading devicePixelRatio() directly
instead would fix THAT symptom but introduce a worse one: Qt has already
applied it once, automatically; multiplying our OWN ui_scale/text_scale
by it too would double-scale everything. There is no signal this module
can read that reflects "what the OS wants" without either being already
neutralized (what happened here) or already applied (which would
compound) -- under Qt6's scaling model, "match the OS's own display
scale" is not this module's job at all; ui_scale/text_scale exist purely
as a SEPARATE, user-controlled zoom LAYERED ON TOP of whatever Qt/the OS
already established (the same relationship a browser's own Ctrl+/Ctrl-
zoom has to the OS's display scale), so 1.0/1.0 -- "no additional zoom"
-- is the only starting value that's actually correct here.

CTRL+WHEEL: ui_scale and text_scale move TOGETHER, one notch per wheel
click (adjust_combined) -- a single combined "zoom," matching the
familiar browser/OS Ctrl+wheel convention, rather than needing a second
modifier to reach one axis independently from the mouse. Splitting them
apart is what the Options dialog's two separate sliders are for. See
main.py's MainWindow.eventFilter for where this is actually caught
(extends the same app-level-eventFilter pattern this codebase already
uses for Tab interception, digit shortcuts, etc. -- see NOTES.md's
debugging-lessons #4).

RAPID INPUT IS COALESCED, NOT APPLIED ONE-FOR-ONE -- TWO SEPARATE INPUT
SOURCES, ONE SHARED FIX: both a fast Ctrl+wheel scroll AND dragging an
Options slider can fire many events in a fraction of a second (a laptop
trackpad's scroll gesture synthesizes a stream of small wheel events to
simulate smooth scrolling; QSlider fires valueChanged continuously while
being dragged, not just on release). Reacting to EVERY one of those
events -- calling set_ui_scale()/set_text_scale()/adjust_combined()
directly, as the first version of this file did -- applies the full,
genuinely expensive scale-change pass (main.py rebuilds and reapplies
the ENTIRE app-wide QSS string, then every scale-aware widget across the
app re-runs its own _apply_*_scale on top of that) once per event, which
is what made both a fast wheel-scroll and a slider drag feel like the
app had frozen -- not a PySide/Qt rendering limit, just the accumulated
cost of re-polishing every styled widget in the app many times over in a
handful of milliseconds. queue_wheel_delta()/queue_ui_scale()/
queue_text_scale() below record the latest requested change and share
ONE debounce timer (_flush_timer, SCALE_FLUSH_INTERVAL_MS) that applies
everything pending in a single pass once input actually PAUSES, rather
than reacting to every individual event -- so a slider drag applies
nothing expensive at all while the mouse is still moving (only the cheap
percent-label text updates live, see options_dialog.py), and a fast
wheel flick still lands on the same final value via one coalesced update
instead of many redundant ones.

WHY A LAPTOP TRACKPAD GESTURE USED TO DRIFT OFF THE 10% GRID (103%, 129%,
147%, ...): the wheel handler used to divide each individual event's raw
angleDelta().y() by 120 (Qt's "one notch = 120 units" convention for a
real detented mouse wheel) and apply that fraction directly. A physical
wheel's clicks land on clean 120-unit multiples; a trackpad's synthesized
scroll events mostly don't, so summing fractional per-event steps drifted
off WHEEL_STEP's clean 10% increments. Fixed by accumulating the RAW
angle units across events (queue_wheel_delta) and only ever converting a
WHOLE multiple of 120 into an actual step (see _flush_pending below) --
any leftover remainder stays queued toward the next flush instead of
being applied fractionally, so the result is always an exact multiple of
WHEEL_STEP regardless of how oddly the input events happened to be sliced.
"""

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication

# Clamp range for both scales -- generous enough to be genuinely useful
# (a 4K-on-a-14"-laptop user going small, a low-vision user going large)
# without letting a runaway scroll/slider produce an unusably tiny or
# huge interface.
MIN_SCALE = 0.7
MAX_SCALE = 2.0

# One Ctrl+wheel "notch" (one discrete scroll step) or one Options-slider
# increment moves either scale by this much -- both controls deliberately
# share the same 10% grid (see options_dialog.py's slider setSingleStep/
# setPageStep calls) rather than two different step sizes for what's
# conceptually one setting.
WHEEL_STEP = 0.10

# Qt's own convention: one physical "notch" on a standard detented mouse
# wheel reports as 120 units of QWheelEvent.angleDelta() (eighths of a
# degree). Used to convert ACCUMULATED raw wheel units into whole
# WHEEL_STEP increments -- see queue_wheel_delta and this module's own
# docstring for why raw units are accumulated rather than each event's
# delta being divided and applied individually.
WHEEL_UNITS_PER_STEP = 120

# How long the shared debounce timer waits, after the MOST RECENT queued
# change (a wheel event or a slider tick), before actually applying
# whatever's pending -- see this module's own docstring ("RAPID INPUT IS
# COALESCED..."). ~50ms is short enough that a single deliberate notch or
# a brief pause mid-drag still feels immediate (well under normal human
# perception of "instant"), while being long enough that a fast wheel
# flick or a continuous slider drag applies nothing expensive until input
# actually settles, rather than once per individual event.
SCALE_FLUSH_INTERVAL_MS = 50

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
        # Coalescing state, shared by all three queue_*() entry points
        # below (wheel + both Options sliders) -- see this module's own
        # docstring ("RAPID INPUT IS COALESCED..."). _pending_wheel_units
        # accumulates RAW angleDelta() units (not pre-divided into
        # steps -- see queue_wheel_delta); _pending_ui_scale/_pending_
        # text_scale hold an ABSOLUTE target value (or None if that axis
        # has nothing pending) since a slider reports "go to this exact
        # position," not a relative delta. One shared timer is enough for
        # all three -- whichever axis actually changed gets exactly one
        # scale_changed emission per flush regardless of which queue_*()
        # call(s) triggered it.
        self._pending_wheel_units = 0.0
        self._pending_ui_scale = None
        self._pending_text_scale = None
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_pending)

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

    def queue_wheel_delta(self, angle_delta_y):
        """
        The Ctrl+wheel entry point (called from main.py's MainWindow.
        eventFilter) -- takes the RAW QWheelEvent.angleDelta().y() value,
        NOT a pre-divided step count. Accumulates raw units across events
        and defers converting them into an actual step until _flush_
        pending runs -- see this module's own docstring for why applying
        each event's own delta/120 fraction directly (the previous
        approach) is what caused a laptop trackpad's scroll gesture to
        drift off the clean 10% grid.
        """
        self._pending_wheel_units += angle_delta_y
        self._flush_timer.start(SCALE_FLUSH_INTERVAL_MS)

    def queue_ui_scale(self, value):
        """
        Debounced counterpart to set_ui_scale() -- used by Options' own
        Interface-scale slider (options_dialog.py's _on_ui_scale_slider_
        changed) instead of calling set_ui_scale() directly on every
        single valueChanged tick. QSlider fires valueChanged CONTINUOUSLY
        while being dragged, not just on release -- calling set_ui_scale()
        straight from that handler applied the full expensive scale-
        change pass once per pixel of mouse movement, which is what made
        dragging the slider feel like it froze the app. This just records
        the latest requested absolute value; _flush_pending applies
        whatever's pending once dragging actually pauses. The slider's own
        percent-value LABEL still updates immediately and directly (see
        options_dialog.py) -- only the expensive app-wide rescale is
        deferred, so the number shown still tracks the slider live even
        though the interface itself catches up a beat later.
        """
        self._pending_ui_scale = value
        self._flush_timer.start(SCALE_FLUSH_INTERVAL_MS)

    def queue_text_scale(self, value):
        """Debounced counterpart to set_text_scale() -- see
        queue_ui_scale's docstring; same reasoning for the Text-scale
        slider."""
        self._pending_text_scale = value
        self._flush_timer.start(SCALE_FLUSH_INTERVAL_MS)

    def _flush_pending(self):
        """
        Applies everything accumulated since the last flush, in one pass,
        via the SAME public setters a direct (non-debounced) caller would
        use -- coalescing only changes WHEN these run, not what they do.
        Wheel units are converted to whole steps first (see
        WHEEL_UNITS_PER_STEP); any remainder that hasn't yet crossed a
        full step is left in _pending_wheel_units for the NEXT flush to
        keep accumulating, rather than being discarded -- this is what
        keeps a trackpad's many small deltas eventually landing on a
        clean step instead of losing the "in-between" scroll motion each
        time nothing crossed the threshold yet. Wheel and slider input are
        never realistically pending at the same moment in practice (they
        come from two different physical actions a person doesn't do
        simultaneously), so no ordering guarantee is needed between them.
        """
        whole_steps = int(self._pending_wheel_units / WHEEL_UNITS_PER_STEP)
        self._pending_wheel_units -= whole_steps * WHEEL_UNITS_PER_STEP
        if whole_steps:
            self.adjust_combined(whole_steps)

        if self._pending_ui_scale is not None:
            value, self._pending_ui_scale = self._pending_ui_scale, None
            self.set_ui_scale(value)

        if self._pending_text_scale is not None:
            value, self._pending_text_scale = self._pending_text_scale, None
            self.set_text_scale(value)

    def reset(self):
        """Back to 1.0x / 1.0x -- wired to a Reset button in Options
        alongside the two sliders. Also discards anything still pending
        from queue_wheel_delta/queue_ui_scale/queue_text_scale and stops
        the shared flush timer -- without this, a Reset click landing
        mid-drag or mid-flick could be silently overridden a moment later
        by a stale flush still in flight."""
        self._flush_timer.stop()
        self._pending_wheel_units = 0.0
        self._pending_ui_scale = None
        self._pending_text_scale = None
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

    Deliberately does NOT try to seed ui_scale/text_scale from any OS
    display-scale reading -- see this module's own docstring ("WHY BOTH
    SCALES START AT A FLAT 1.0/1.0...") for a real attempt at that and
    why it was retracted: Qt6's own mandatory automatic high-DPI scaling
    already matches the OS's chosen display scale before this app's code
    ever runs, so there is nothing left here for OUR axes to detect and
    apply without risking double-scaling.
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
