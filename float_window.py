#!/usr/bin/env python3
"""
Float window — draggable, pulsing status overlay for whisper-ear.

Shows a small semi-transparent pill in the corner with:
  - A pulsing red dot while recording
  - Status text (listening / transcribing / done / error)
  - Draggable — remembers position in config

Usage from WhisperEarApp:
    self.float = FloatWindow.alloc().initWithConfig_(config_path)
    self.float.setConfig_(config_dict)
    self.float.show("Listening", mode="recording")
    self.float.show("✓ Done", mode="done", timeout=1.8)
    self.float.close()
"""

import json
import threading
from pathlib import Path

import objc

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSMakeRect,
    NSScreen,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorTransient,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

from whisper_ear.audio_levels import read_wav_tail_level
from whisper_ear.recording import active_session


WIDTH = 280
HEIGHT = 54
DOT_SIZE = 20
DOT_MIN = 6
DOT_MAX = 28
DOT_MARGIN = 16
LABEL_LEFT = DOT_MARGIN + DOT_MAX + 6  # 50px
PULSE_INTERVAL = 0.08  # seconds between ticks


class FloatWindow(NSObject):
    """Managed floating status window with pulsing indicator."""

    def init(self):
        self = objc.super(FloatWindow, self).init()
        if self is None:
            return None
        self._config_path = None
        self._config = {}
        self._window = None
        self._label = None
        self._dot = None
        self._pulse_timer = None
        self._pulse_phase = 0.0
        self._last_level = 0.0
        self._is_speaking = False
        return self

    def initWithConfig_(self, config_path):
        self = self.init()
        if self is None:
            return None
        self._config_path = Path(config_path)
        return self

    def setConfig_(self, config):
        self._config = config

    # ── Public API (Python-only) ───────────────────────────

    @objc.python_method
    def show(self, message, mode="recording", timeout=None):
        """Show the float window with a status message.

        Modes: "recording" (pulsing dot), "transcribing", "done", "error".
        Timeout: auto-close after N seconds (None = stay visible).
        """
        if self._window is None:
            self._build()

        if mode == "recording":
            self._start_pulse()
        elif self._pulse_timer is not None:
            self._stop_pulse()

        marker = {
            "recording": "",
            "transcribing": "⋯",
            "done": "✓",
            "error": "!",
        }.get(mode, "")

        text = f"{marker} {message[:90]}".strip() if marker else message[:90]
        self._label.setStringValue_(text)
        self._window.orderFrontRegardless()

        if timeout is not None:
            AppHelper.callLater(timeout, self.close)

    @objc.python_method
    def close(self):
        """Hide the float window and save position."""
        self._stop_pulse()
        if self._window is not None:
            self._save_origin()
            self._window.orderOut_(None)

    # ── NSWindowDelegate ───────────────────────────────────

    def windowDidMove_(self, notification):
        """Save position when user drags."""
        self._save_origin()

    # ── Build ──────────────────────────────────────────────

    @objc.python_method
    def _build(self):
        x, y = self._saved_origin()

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, WIDTH, HEIGHT),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(NSFloatingWindowLevel)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setHasShadow_(True)
        self._window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorTransient
            | NSWindowCollectionBehaviorIgnoresCycle
        )
        self._window.setMovableByWindowBackground_(True)

        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, HEIGHT))
        view.setWantsLayer_(True)
        view.layer().setCornerRadius_(12)
        view.layer().setBackgroundColor_(
            NSColor.blackColor().colorWithAlphaComponent_(0.82).CGColor()
        )

        # Pulsing dot
        self._dot = NSView.alloc().initWithFrame_(
            NSMakeRect(DOT_MARGIN, (HEIGHT - DOT_SIZE) / 2, DOT_SIZE, DOT_SIZE)
        )
        self._dot.setWantsLayer_(True)
        self._dot.layer().setCornerRadius_(DOT_SIZE / 2)
        self._dot.layer().setBackgroundColor_(NSColor.systemRedColor().CGColor())
        view.addSubview_(self._dot)

        # Label
        self._label = NSTextField.labelWithString_("Listening")
        self._label.setTextColor_(NSColor.whiteColor())
        self._label.setFrame_(NSMakeRect(LABEL_LEFT, 15, WIDTH - LABEL_LEFT - DOT_MARGIN, 24))
        view.addSubview_(self._label)

        self._window.setContentView_(view)
        self._window.setDelegate_(self)

    # ── Voice level visualization ─────────────────────────

    @objc.python_method
    def _start_pulse(self):
        if self._pulse_timer is not None:
            return
        self._last_level = 0.0
        self._is_speaking = False
        self._pulse_timer = True
        self._pulse_thread = threading.Thread(target=self._pulse_loop, daemon=True)
        self._pulse_thread.start()

    @objc.python_method
    def _stop_pulse(self):
        self._pulse_timer = None
        self._is_speaking = False
        if self._dot is not None:
            AppHelper.callAfter(self._reset_dot)

    def _reset_dot(self):
        if self._dot is not None:
            self._dot.setFrame_(
                NSMakeRect(DOT_MARGIN, (HEIGHT - DOT_SIZE) / 2, DOT_SIZE, DOT_SIZE)
            )
            self._dot.layer().setBackgroundColor_(NSColor.systemRedColor().CGColor())

    @objc.python_method
    def _pulse_loop(self):
        """Background thread: reads mic level, marshals UI updates to main thread."""
        import time
        while self._pulse_timer is not None:
            level = self._read_mic_level()
            self._last_level = self._last_level * 0.3 + level * 0.7
            t = self._last_level
            speaking = t > 0.02
            if speaking != self._is_speaking:
                self._is_speaking = speaking
            AppHelper.callAfter(self._update_dot, t, speaking)
            time.sleep(PULSE_INTERVAL)

    def _update_dot(self, t, speaking):
        """Called on main thread to update the dot and label."""
        if self._dot is None or self._pulse_timer is None:
            return

        # Update label
        self._label.setStringValue_("Listening" if speaking else "Waiting…")

        # Dot size: quiet=DOT_MIN, loud=DOT_MAX
        size = DOT_MIN + (DOT_MAX - DOT_MIN) * t
        cy = HEIGHT / 2
        cx = DOT_MARGIN + DOT_MAX / 2
        self._dot.setFrame_(NSMakeRect(cx - size / 2, cy - size / 2, size, size))

        # Color: dim red (quiet) → bright green (loud)
        r = 1.0 - 0.6 * t
        g = 0.3 + 0.7 * t
        b = 0.1
        a = 0.6 + 0.4 * t
        self._dot.layer().setBackgroundColor_(
            NSColor.colorWithRed_green_blue_alpha_(r, g, b, a).CGColor()
        )

    @objc.python_method
    def _read_mic_level(self):
        """Read raw PCM from the end of the live WAV and return RMS volume 0..1.

        sox writes 48kHz 32-bit signed int PCM after a 44-byte WAV header.
        We skip wave.open() entirely and read raw bytes — much more reliable
        with a file that's being actively written to.
        """
        session = active_session()
        if not session:
            return 0.0
        return read_wav_tail_level(session.audio_path)

    # ── Position persistence ───────────────────────────────

    @objc.python_method
    def _default_origin(self):
        screen = NSScreen.mainScreen().visibleFrame()
        return (
            screen.origin.x + screen.size.width - WIDTH - 28,
            screen.origin.y + screen.size.height - HEIGHT - 28,
        )

    @objc.python_method
    def _saved_origin(self):
        pos = self._config.get("float_window", {}).get("origin")
        if pos and len(pos) == 2:
            return tuple(pos)
        return self._default_origin()

    @objc.python_method
    def _save_origin(self):
        if self._window is None:
            return
        frame = self._window.frame()
        self._config.setdefault("float_window", {})["origin"] = [
            frame.origin.x,
            frame.origin.y,
        ]
        try:
            with self._config_path.open("w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
