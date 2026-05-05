#!/usr/bin/env python3
"""
Wisper menu bar prototype for macOS.

Runs bin/dictate from a menu bar app and listens for Option+Shift+Space.
"""

import os
import ctypes
import json
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import objc
from AppKit import (
    NSAlert,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSFloatingWindowLevel,
    NSKeyDownMask,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPopover,
    NSStatusBar,
    NSTextField,
    NSView,
    NSViewController,
    NSVariableStatusItemLength,
    NSScreen,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorTransient,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSObject
from PyObjCTools import AppHelper


ROOT = Path(__file__).resolve().parent
DICTATE = ROOT / "bin" / "dictate"
DICTATED = ROOT / "dictated.py"
CONFIG = ROOT / "config.json"
PYTHON = str(Path.home() / "miniforge3" / "bin" / "python3")


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


class WisperApp(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        self.config = self.load_config()
        self.verbose = "--verbose" in sys.argv or self.config.get("logging", {}).get("verbose", False)
        self.quiet = "--quiet" in sys.argv
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.status_item.button().setTitle_("W")
        self.status_item.setMenu_(self.build_menu())
        self.popover = None
        self.float_window = None
        self.float_label = None
        self.install_hotkey_monitor()
        self.log(
            f"ready hotkey={self.hotkey_label(self.config.get('hotkey', {}))} "
            f"model={self.config.get('dictation', {}).get('model', 'base')}"
        )

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

        check = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Check Setup", "checkSetup:", ""
        )
        check.setTarget_(self)
        menu.addItem_(check)

        stop = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Stop Daemon", "stopDaemon:", ""
        )
        stop.setTarget_(self)
        menu.addItem_(stop)

        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "quit:", "q"
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        return menu

    @objc.python_method
    def load_config(self):
        defaults = {
            "hotkey": {"modifiers": ["option", "shift"], "key": "space"},
            "dictation": {"model": "base", "initial_prompt": "", "hotwords": ""},
            "logging": {"enabled": True, "verbose": False, "log_transcripts": False},
        }
        if not CONFIG.exists():
            return defaults
        try:
            with CONFIG.open("r", encoding="utf-8") as f:
                data = json.load(f)
            defaults.update(data)
            defaults["hotkey"] = {**{"modifiers": ["option", "shift"], "key": "space"}, **data.get("hotkey", {})}
            defaults["dictation"] = {**{"model": "base", "initial_prompt": "", "hotwords": ""}, **data.get("dictation", {})}
            defaults["logging"] = {**{"enabled": True, "verbose": False, "log_transcripts": False}, **data.get("logging", {})}
            return defaults
        except Exception:
            return defaults

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
    def is_recording(self):
        lockfile = Path("/tmp/dictate_recording")
        if not lockfile.exists():
            return False
        try:
            pid = int(lockfile.read_text().strip())
            os.kill(pid, 0)
            return True
        except Exception:
            return False

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
        return subprocess.run(
            args,
            cwd=str(ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )

    def toggleDictation_(self, sender):
        stopping = self.is_recording()
        self.log("dictation stop requested" if stopping else "dictation start requested")
        self.status_item.button().setTitle_("..." if stopping else "REC")
        self._show_float("Transcribing..." if stopping else "Listening", "transcribing" if stopping else "recording")
        self._show_popover("Transcribing..." if stopping else "Recording...")
        try:
            result = self._run_command([str(DICTATE)])
            message = self._clean_output(result.stdout.strip() or "Done")
            self.log_command_result("dictate", result.stdout, message)
            if stopping:
                self._show_float(message, "done", timeout=1.8)
            else:
                self._show_float("Listening", "recording")
            self._show_popover(message)
            self._notify("Wisper", message)
        except Exception as exc:
            self.log(f"dictation error {exc}")
            self._show_float(f"Error: {exc}", "error", timeout=2.5)
            self._show_popover(f"Error: {exc}")
            self._notify("Wisper error", str(exc))
        finally:
            self.status_item.button().setTitle_("W")

    def checkSetup_(self, sender):
        try:
            self.log("check setup")
            result = self._run_command([str(DICTATE), "--check"])
            self.log_command_result("check", result.stdout, "shown in alert")
            self._alert("Wisper setup", result.stdout.strip())
        except Exception as exc:
            self.log(f"check setup error {exc}")
            self._alert("Wisper setup error", str(exc))

    def stopDaemon_(self, sender):
        self.log("stop daemon")
        result = self._run_command([PYTHON, str(DICTATED), "stop"])
        self.log_command_result("stop daemon", result.stdout, result.stdout.strip())
        self._notify("Wisper", result.stdout.strip())

    def quit_(self, sender):
        self.log("quit")
        NSApplication.sharedApplication().terminate_(self)

    @objc.python_method
    def _show_popover(self, message, timeout=1.8):
        if self.popover is not None:
            self.popover.close()

        label = NSTextField.labelWithString_(message[:160])
        label.setFrame_(NSMakeRect(14, 12, 260, 42))
        label.setLineBreakMode_(0)

        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 288, 66))
        view.addSubview_(label)

        controller = NSViewController.alloc().init()
        controller.setView_(view)

        self.popover = NSPopover.alloc().init()
        self.popover.setContentViewController_(controller)
        self.popover.showRelativeToRect_ofView_preferredEdge_(
            self.status_item.button().bounds(), self.status_item.button(), 3
        )
        AppHelper.callLater(timeout, self._close_popover)

    @objc.python_method
    def _show_float(self, message, mode, timeout=None):
        if self.float_window is None:
            self._build_float_window()

        marker = {
            "recording": "●",
            "transcribing": "⋯",
            "done": "✓",
            "error": "!",
        }.get(mode, "●")
        self.float_label.setStringValue_(f"{marker} {message[:80]}")
        self.float_window.orderFrontRegardless()

        if timeout is not None:
            AppHelper.callLater(timeout, self._close_float)

    @objc.python_method
    def _build_float_window(self):
        width = 260
        height = 54
        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + screen.size.width - width - 28
        y = screen.origin.y + screen.size.height - height - 28

        self.float_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self.float_window.setLevel_(NSFloatingWindowLevel)
        self.float_window.setOpaque_(False)
        self.float_window.setBackgroundColor_(NSColor.clearColor())
        self.float_window.setHasShadow_(True)
        self.float_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorTransient
            | NSWindowCollectionBehaviorIgnoresCycle
        )

        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        view.setWantsLayer_(True)
        view.layer().setCornerRadius_(12)
        view.layer().setBackgroundColor_(NSColor.blackColor().colorWithAlphaComponent_(0.82).CGColor())

        self.float_label = NSTextField.labelWithString_("● Listening")
        self.float_label.setTextColor_(NSColor.whiteColor())
        self.float_label.setFrame_(NSMakeRect(16, 15, width - 32, 24))
        view.addSubview_(self.float_label)

        self.float_window.setContentView_(view)

    @objc.python_method
    def _close_float(self):
        if self.float_window is not None:
            self.float_window.orderOut_(None)

    @objc.python_method
    def _close_popover(self):
        if self.popover is not None:
            self.popover.close()
            self.popover = None

    @objc.python_method
    def _clean_output(self, text):
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
    def _notify(self, title, message):
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{self._escape(message[:180])}" with title "{self._escape(title)}"',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

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
        print("Usage: bin/wisper-app [--verbose] [--quiet]")
        print("  --verbose  Print command output and detailed logs")
        print("  --quiet    Disable app logs")
        return
    signal.signal(signal.SIGTERM, handle_exit_signal)
    AppHelper.installMachInterrupt()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = WisperApp.alloc().init()
    app.setDelegate_(delegate)
    print("Wisper app running. Look for W in the macOS menu bar. Press Ctrl-C here to quit.", flush=True)
    AppHelper.runEventLoop()


def handle_exit_signal(signum, frame):
    print("\nWisper app quitting.", flush=True)
    app = NSApplication.sharedApplication()
    app.terminate_(None)
    sys.exit(0)


if __name__ == "__main__":
    main()
