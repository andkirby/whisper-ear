#!/usr/bin/env python3
"""
Wisper menu bar prototype for macOS.

Runs bin/dictate from a menu bar app and listens for Option+Shift+Space.
"""

import os
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
    NSEvent,
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
)
from Foundation import NSObject
from PyObjCTools import AppHelper


ROOT = Path(__file__).resolve().parent
DICTATE = ROOT / "bin" / "dictate"
DICTATED = ROOT / "dictated.py"
CONFIG = ROOT / "config.json"
PYTHON = str(Path.home() / "miniforge3" / "bin" / "python3")


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
        NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSKeyDownMask, self.handle_key_event
        )
        NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSKeyDownMask, self.handle_local_key_event
        )

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
        self._show_popover("Transcribing..." if stopping else "Recording...")
        try:
            result = self._run_command([str(DICTATE)])
            message = self._clean_output(result.stdout.strip() or "Done")
            self.log_command_result("dictate", result.stdout, message)
            self._show_popover(message)
            self._notify("Wisper", message)
        except Exception as exc:
            self.log(f"dictation error {exc}")
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
