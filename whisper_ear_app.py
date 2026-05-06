#!/usr/bin/env python3
"""
WhisperEar menu bar prototype for macOS.

Runs bin/dictate from a menu bar app and listens for Option+Shift+Space.
"""

import json
import os
import ctypes
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import objc
import warnings
warnings.filterwarnings("ignore", category=objc.ObjCPointerWarning)

from AppKit import (
    NSAlert,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSEvent,
    NSKeyDownMask,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

from float_window import FloatWindow
from whisper_ear.config import load_config as load_whisper_ear_config
from whisper_ear.recording import cleanup_stale_recording
from whisper_ear.runtime_paths import paths as runtime_paths

ROOT = Path(__file__).resolve().parent
DICTATE = ROOT / "bin" / "dictate"
DICTATED = ROOT / "dictated.py"
CONFIG = ROOT / "config.json"
PYTHON = str(Path.home() / "miniforge3" / "bin" / "python3")

AVAILABLE_MODELS = [
    ("tiny", "Tiny (~75 MB)"),
    ("base", "Base (~145 MB)"),
    ("small", "Small (~488 MB)"),
    ("medium", "Medium (~769 MB)"),
    ("large-v3-turbo", "Large v3 Turbo (~809 MB)"),
    ("distil-large-v3.5", "Distil Large v3.5 (~780 MB)"),
    ("large-v3", "Large v3 (~1.5 GB)"),
]


def fourcc(value):
    return int.from_bytes(value.encode("ascii"), byteorder="big")


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


CARBON = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
CARBON_CALLBACK = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)
CARBON.GetApplicationEventTarget.restype = ctypes.c_void_p
CARBON.InstallEventHandler.argtypes = [
    ctypes.c_void_p,
    CARBON_CALLBACK,
    ctypes.c_uint32,
    ctypes.POINTER(EventTypeSpec),
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
]
CARBON.RegisterEventHotKey.argtypes = [
    ctypes.c_uint32,
    ctypes.c_uint32,
    EventHotKeyID,
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_void_p),
]

CARBON_KEY_CODES = {
    "space": 49,
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "9": 25,
    "7": 26,
    "8": 28,
    "0": 29,
    "o": 31,
    "u": 32,
    "i": 34,
    "p": 35,
    "l": 37,
    "j": 38,
    "k": 40,
    "n": 45,
    "m": 46,
}

CARBON_MODIFIERS = {
    "command": 1 << 8,
    "shift": 1 << 9,
    "option": 1 << 11,
    "control": 1 << 12,
}


class WhisperEarApp(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        self.config = self.load_config()
        self.verbose = "--verbose" in sys.argv or self.config.get("logging", {}).get("verbose", False)
        self.quiet = "--quiet" in sys.argv

        # Clean up stale recording state from previous session
        self._cleanup_stale_recording()

        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.status_item.button().setTitle_("W")
        self.status_item.setMenu_(self.build_menu())
        self.float = FloatWindow.alloc().initWithConfig_(CONFIG)
        self.float.setConfig_(self.config)
        self.is_recording = False
        self.dictation_busy = False
        self.install_hotkey_monitor()
        model = self.config.get('dictation', {}).get('model', 'base')
        self.log(
            f"ready hotkey={self.hotkey_label(self.config.get('hotkey', {}))} "
            f"model={model}",
            force=True,
        )
        self.float.show(f"Ready — {model}", mode="done", timeout=2.0)
        self._schedule_daemon_status_refresh()

        # Startup log with full status
        daemon_cfg = self.config.get("daemon", {})
        keep = daemon_cfg.get("keep_loaded_models", ["tiny", "base"])
        timeout_min = daemon_cfg.get("unload_timeout_minutes", 5)
        pinned = "pinned" if model in keep else f"unloads after {timeout_min}m"
        daemon_running = runtime_paths().pid.exists()
        daemon_state = "running" if daemon_running else "not running"
        self.log(f"model={model} ({pinned}) daemon={daemon_state}", force=True)

    @objc.python_method
    def build_menu(self):
        menu = NSMenu.alloc().init()

        hotkey = self.config.get("hotkey", {})
        toggle = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Toggle Dictation ({self.hotkey_label(hotkey)})",
            "toggleDictation:",
            self.menu_key(hotkey.get("key", "space")),
        )
        toggle.setKeyEquivalentModifierMask_(self.modifier_mask(hotkey.get("modifiers", [])))
        toggle.setTarget_(self)
        menu.addItem_(toggle)

        menu.addItem_(NSMenuItem.separatorItem())

        # Model selection submenu
        model_menu = NSMenu.alloc().init()
        self.model_menu_items = {}
        current_model = self.config.get("dictation", {}).get("model", "base")
        for model_id, model_label in AVAILABLE_MODELS:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                model_label, "selectModel:", ""
            )
            item.setTarget_(self)
            item.setRepresentedObject_(model_id)
            item.setState_(1 if model_id == current_model else 0)
            model_menu.addItem_(item)
            self.model_menu_items[model_id] = item

        model_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Model", None, ""
        )
        model_parent.setSubmenu_(model_menu)
        menu.addItem_(model_parent)

        menu.addItem_(NSMenuItem.separatorItem())

        # Daemon status line (updated periodically)
        self.daemon_status_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Daemon: checking…", "refreshDaemonStatus:", ""
        )
        self.daemon_status_item.setTarget_(self)
        menu.addItem_(self.daemon_status_item)

        # Start/Stop daemon — toggles dynamically
        self.daemon_toggle_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Stop Daemon", "toggleDaemon:", ""
        )
        self.daemon_toggle_item.setTarget_(self)
        menu.addItem_(self.daemon_toggle_item)

        check = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Check Setup", "checkSetup:", ""
        )
        check.setTarget_(self)
        menu.addItem_(check)

        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "quit:", "q"
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        return menu

    @objc.python_method
    def load_config(self):
        return load_whisper_ear_config(CONFIG)

    @objc.python_method
    def hotkey_label(self, hotkey):
        names = {
            "command": "Cmd",
            "option": "Opt",
            "control": "Ctrl",
            "shift": "Shift",
        }
        parts = [names.get(m, m) for m in hotkey.get("modifiers", [])]
        key = hotkey.get("key", "space")
        parts.append("Space" if key == "space" else str(key).upper())
        return "+".join(parts)

    @objc.python_method
    def menu_key(self, key):
        return " " if key == "space" else str(key)[:1].lower()

    @objc.python_method
    def modifier_mask(self, modifiers):
        mask = 0
        for modifier in modifiers:
            if modifier == "command":
                mask |= NSEventModifierFlagCommand
            elif modifier == "option":
                mask |= NSEventModifierFlagOption
            elif modifier == "control":
                mask |= NSEventModifierFlagControl
            elif modifier == "shift":
                mask |= NSEventModifierFlagShift
        return mask

    @objc.python_method
    def install_hotkey_monitor(self):
        try:
            self.install_carbon_hotkey()
            self.log("hotkey backend=carbon")
            return
        except Exception as exc:
            self.log(f"hotkey backend=appkit fallback reason={exc}")

        NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSKeyDownMask, self.handle_key_event
        )
        NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSKeyDownMask, self.handle_local_key_event
        )

    @objc.python_method
    def install_carbon_hotkey(self):
        hotkey = self.config.get("hotkey", {})
        key = hotkey.get("key", "space")
        key_code = CARBON_KEY_CODES.get(key)
        if key_code is None:
            raise ValueError(f"unsupported key: {key}")

        modifiers = 0
        for modifier in hotkey.get("modifiers", []):
            if modifier not in CARBON_MODIFIERS:
                raise ValueError(f"unsupported modifier: {modifier}")
            modifiers |= CARBON_MODIFIERS[modifier]

        def handler(next_handler, event, user_data):
            self.log("hotkey carbon")
            AppHelper.callAfter(self.toggleDictation_, None)
            return 0

        self._carbon_callback = CARBON_CALLBACK(handler)
        event_spec = EventTypeSpec(fourcc("keyb"), 5)
        self._carbon_handler_ref = ctypes.c_void_p()
        target = CARBON.GetApplicationEventTarget()
        status = CARBON.InstallEventHandler(
            target,
            self._carbon_callback,
            1,
            ctypes.byref(event_spec),
            None,
            ctypes.byref(self._carbon_handler_ref),
        )
        if status != 0:
            raise RuntimeError(f"InstallApplicationEventHandler status={status}")

        hotkey_id = EventHotKeyID(fourcc("WSPR"), 1)
        self._carbon_hotkey_ref = ctypes.c_void_p()
        status = CARBON.RegisterEventHotKey(
            key_code,
            modifiers,
            hotkey_id,
            target,
            0,
            ctypes.byref(self._carbon_hotkey_ref),
        )
        if status != 0:
            raise RuntimeError(f"RegisterEventHotKey status={status}")

    @objc.python_method
    def handle_local_key_event(self, event):
        if self.is_hotkey(event):
            self.log("hotkey local")
            self.toggleDictation_(None)
            return None
        return event

    @objc.python_method
    def handle_key_event(self, event):
        if self.is_hotkey(event):
            self.log("hotkey global")
            self.toggleDictation_(None)

    @objc.python_method
    def is_hotkey(self, event):
        hotkey = self.config.get("hotkey", {})
        expected_modifiers = set(hotkey.get("modifiers", []))
        expected_key = hotkey.get("key", "space")
        flags = event.modifierFlags()
        actual = {
            "command": bool(flags & NSEventModifierFlagCommand),
            "option": bool(flags & NSEventModifierFlagOption),
            "control": bool(flags & NSEventModifierFlagControl),
            "shift": bool(flags & NSEventModifierFlagShift),
        }
        for modifier, enabled in actual.items():
            if enabled != (modifier in expected_modifiers):
                return False
        key = event.charactersIgnoringModifiers()
        if expected_key == "space":
            return key == " "
        return key.lower() == expected_key.lower()

    @objc.python_method
    def _cleanup_stale_recording(self):
        """Kill any orphaned rec process from a previous session."""
        pid = cleanup_stale_recording()
        if pid is not None:
            self.log(f"cleaned up orphaned recording (PID {pid})", force=True)

    @objc.python_method
    def _run_command(self, args):
        env = os.environ.copy()
        env["PATH"] = (
            f"{Path.home()}/miniforge3/bin:/opt/homebrew/bin:/usr/local/bin:"
            "/usr/bin:/bin:/usr/sbin:/sbin"
        )
        dictation = self.config.get("dictation", {})
        if dictation.get("model"):
            env["DICTATE_MODEL"] = dictation["model"]
        if dictation.get("initial_prompt"):
            env["DICTATE_INITIAL_PROMPT"] = dictation["initial_prompt"]
        if dictation.get("hotwords"):
            env["DICTATE_HOTWORDS"] = dictation["hotwords"]
        env["DICTATE_CONFIG"] = str(CONFIG)
        daemon = self.config.get("daemon", {})
        transcription_timeout = daemon.get("transcription_timeout_seconds", 180)
        try:
            timeout = max(120.0, float(transcription_timeout) + 30.0)
        except (TypeError, ValueError):
            timeout = 210.0
        return subprocess.run(
            args,
            cwd=str(ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )

    def toggleDictation_(self, sender):
        if self.dictation_busy:
            self.log("dictation ignored: command already running")
            self.float.show("Busy", mode="error", timeout=1.2)
            return
        stopping = self.is_recording
        self.is_recording = not self.is_recording
        self.dictation_busy = True
        self.log("dictation stop requested" if stopping else "dictation start requested")
        self.status_item.button().setTitle_("..." if stopping else "REC")
        self.float.show(
            "Transcribing..." if stopping else "Listening",
            mode="transcribing" if stopping else "recording",
        )

        def worker():
            try:
                result = self._run_command([str(DICTATE)])
                AppHelper.callAfter(self._finish_dictation_command, stopping, result.stdout, None)
            except Exception as exc:
                AppHelper.callAfter(self._finish_dictation_command, stopping, "", exc)

        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def _finish_dictation_command(self, stopping, output, error):
        try:
            if error is not None:
                self.log(f"dictation error {error}")
                self.is_recording = False
                self.float.show(f"Error: {error}", mode="error", timeout=2.5)
                return
            message = self._clean_output(output.strip() or "Done")
            self.log_command_result("dictate", output, message)
            if stopping:
                self.float.show(message, mode="done", timeout=1.8)
            else:
                self.float.show("Listening", mode="recording")
        finally:
            self.dictation_busy = False
            self.status_item.button().setTitle_("W")

    def selectModel_(self, sender):
        model_id = sender.representedObject()
        if isinstance(model_id, str):
            self._switch_model(model_id)

    @objc.python_method
    def _switch_model(self, model_id):
        self.config = self.load_config()
        current = self.config.get("dictation", {}).get("model", "base")
        if model_id == current:
            return

        self.log(f"switching model: {current} → {model_id}")

        # Update in-memory config
        self.config.setdefault("dictation", {})["model"] = model_id

        # Persist to config.json
        try:
            config_path = Path(CONFIG)
            config_path.write_text(
                json.dumps(self.config, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            self.log(f"config write error: {exc}")
            self.float.show(f"Config error: {exc}", mode="error", timeout=2.5)
            return

        # Update menu checkmarks
        for mid, item in self.model_menu_items.items():
            item.setState_(1 if mid == model_id else 0)

        # Restart daemon if running (MODEL_NAME is a startup-time global)
        self._restart_daemon_for_model_switch()

        # Update float window and status bar
        self.float.show(f"Model: {model_id}", mode="done", timeout=1.5)
        self._refresh_daemon_status()
        self.log(f"model switched to {model_id}", force=True)

    @objc.python_method
    def _restart_daemon_for_model_switch(self):
        pid_file = runtime_paths().pid
        if not pid_file.exists():
            return
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            self.log("restarting daemon for model switch")
            self._run_command([PYTHON, str(DICTATED), "stop"])
            self._start_daemon()
        except (ProcessLookupError, ValueError, OSError):
            pass

    def checkSetup_(self, sender):
        try:
            self.log("check setup")
            result = self._run_command([str(DICTATE), "--check"])
            self.log_command_result("check", result.stdout, "shown in alert")
            self._alert("whisper-ear setup", result.stdout.strip())
        except Exception as exc:
            self.log(f"check setup error {exc}")
            self._alert("whisper-ear setup error", str(exc))

    def toggleDaemon_(self, sender):
        """Toggle daemon start/stop based on current state."""
        status_file = runtime_paths().pid
        if status_file.exists():
            try:
                pid = int(status_file.read_text().strip())
                os.kill(pid, 0)
                # Running — stop it
                self.log("stopping daemon")
                result = self._run_command([PYTHON, str(DICTATED), "stop"])
                self.log_command_result("stop daemon", result.stdout, result.stdout.strip())
            except (ProcessLookupError, ValueError, OSError):
                # Stale PID — start it
                self._start_daemon()
        else:
            self._start_daemon()
        self._refresh_daemon_status()

    @objc.python_method
    def _start_daemon(self):
        self.log("starting daemon")
        result = self._run_command([PYTHON, str(DICTATED), "start"])
        self.log_command_result("start daemon", result.stdout, result.stdout.strip())

    def refreshDaemonStatus_(self, sender):
        self._refresh_daemon_status()

    @objc.python_method
    def _refresh_daemon_status(self):
        """Update daemon status line and toggle button in the menu."""
        model = self.config.get("dictation", {}).get("model", "base")

        daemon_alive = False
        pid_file = runtime_paths().pid
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 0)
                daemon_alive = True
            except (ProcessLookupError, ValueError, OSError):
                daemon_alive = False

        if not daemon_alive:
            self.daemon_status_item.setTitle_(f"○ {model} — not running")
            self.daemon_toggle_item.setTitle_("Start Daemon")
            self.status_item.button().setToolTip_(f"{model} — daemon not running")
            return

        try:
            result = self._run_command([PYTHON, str(DICTATED), "status"])
            output = result.stdout.strip()
            state = "unknown"
            if "state=" in output:
                state = output.split("state=", 1)[1].split(",", 1)[0].split(")", 1)[0]
            keep = "keep_loaded=yes" in output
            timeout = self.config.get("daemon", {}).get("unload_timeout_minutes", 5)

            if state == "loaded":
                if keep:
                    label = f"● {model} — loaded (pinned)"
                else:
                    label = f"● {model} — loaded (unloads {timeout}m idle)"
            elif state == "unloaded":
                label = f"○ {model} — sleeping (reload on demand)"
            else:
                label = f"◌ {model} — {state}"
        except Exception:
            label = f"● {model} — loading…"

        self.daemon_status_item.setTitle_(label)
        self.daemon_toggle_item.setTitle_("Stop Daemon")
        self.status_item.button().setToolTip_(label)

    def _schedule_daemon_status_refresh(self):
        """Poll daemon status every 10s."""
        self._refresh_daemon_status()
        AppHelper.callLater(10.0, self._schedule_daemon_status_refresh)

    def quit_(self, sender):
        self.log("quit")
        NSApplication.sharedApplication().terminate_(self)

    # ── Helpers ────────────────────────────────────────────

    @objc.python_method
    def _clean_output(self, text):
        text = self._strip_ansi(text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return "Done"
        return lines[-1]

    @objc.python_method
    def log(self, message, force=False):
        logging_config = self.config.get("logging", {})
        if self.quiet or (not force and not logging_config.get("enabled", True)):
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}", flush=True)

    @objc.python_method
    def log_command_result(self, action, output, message):
        clean = self._strip_ansi(output)
        if self.verbose:
            self.log(f"{action} output: {clean.strip() or '(empty)'}")
        if self.config.get("logging", {}).get("log_transcripts", False):
            self.log(f"{action} result: {message}")
        else:
            self.log(f"{action} result length={len(message)}")

    @objc.python_method
    def _strip_ansi(self, text):
        result = []
        i = 0
        while i < len(text):
            if text[i] == "\033":
                i += 1
                while i < len(text) and text[i] != "m":
                    i += 1
            else:
                result.append(text[i])
            i += 1
        return "".join(result)

    @objc.python_method
    def _alert(self, title, message):
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.runModal()

    @objc.python_method
    def _escape(self, text):
        return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


NSEventModifierFlagCommand = 1 << 20
NSEventModifierFlagOption = 1 << 19
NSEventModifierFlagControl = 1 << 18
NSEventModifierFlagShift = 1 << 17


def main():
    if "--help" in sys.argv:
        print("Usage: bin/whisper-ear-app [--verbose] [--quiet]")
        print("  --verbose  Print command output and detailed logs")
        print("  --quiet    Disable app logs")
        return
    signal.signal(signal.SIGTERM, handle_exit_signal)
    AppHelper.installMachInterrupt()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = WhisperEarApp.alloc().init()
    app.setDelegate_(delegate)
    print("whisper-ear app running. Look for W in the macOS menu bar. Press Ctrl-C here to quit.", flush=True)
    AppHelper.runEventLoop()


def handle_exit_signal(signum, frame):
    print("\nwhisper-ear app quitting.", flush=True)
    app = NSApplication.sharedApplication()
    app.terminate_(None)
    sys.exit(0)


if __name__ == "__main__":
    main()
