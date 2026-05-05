# Dictation — Live Mic → Text → Paste

> Global hotkey dictation using `bin/dictate` + `dictated.py` + `float_window.py`.

## How it works

```
Option+Space (press 1) → sox records mic to /tmp/dictate_audio.wav
                         float overlay shows voice-level dot + "Waiting…" / "Listening"
Option+Space (press 2) → sox stops → dictated.py daemon transcribes → pbcopy → CMD+V paste
                         float overlay shows "✓ result" for 1.8s
```

**Toggle mode**: one hotkey, press to start, press again to stop. Text appears at your cursor.

## Files

| File | Purpose |
|---|---|
| `bin/dictate` | Shell script — toggle record/stop, calls dictated.py daemon, pastes result |
| `bin/wisper-app` | macOS menu bar launcher |
| `dictate.py` | Standalone one-shot transcriber (used without daemon) |
| `dictated.py` | Python daemon — keeps the Whisper model loaded between dictations |
| `wisper_app.py` | PyObjC menu bar app with Carbon hotkey, delegates to bin/dictate |
| `float_window.py` | Float overlay — voice level dot, status text, draggable, position persistence |

## Setup

### 1. Install dependencies

```bash
brew install sox              # mic recording
pip install faster-whisper    # transcription engine
```

### 2. Verify

```bash
# Test transcriber directly
rec -r 48000 -c 1 /tmp/test.wav    # speak, then Ctrl+C
python3 dictate.py /tmp/test.wav

# Test hotkey dependencies without recording
bin/dictate --check

# Test full toggle flow
bin/dictate   # press 1 → "🎤 Recording…"
# speak...
bin/dictate   # press 2 → text pasted
```

### 3. Run the menu bar app

```bash
bin/wisper-app
```

Adds a `W` item to the macOS menu bar. Listens for **Option+Space** (configurable in `config.json`).

Features:
- **Float overlay**: draggable status pill with live voice-level dot
  - Red tiny dot = silence ("Waiting…")
  - Green growing dot = voice detected ("Listening")
  - Position remembered between sessions
- **Menu**: Toggle Dictation, Check Setup, Stop Daemon, Quit
- **Carbon hotkey**: registers with macOS so foreground app doesn't receive the keypress
- **Auto-starts daemon**: if `dictated.py` isn't running, starts it automatically

macOS may require Microphone, Accessibility, and Input Monitoring permissions.

### 4. Alternative hotkey options

#### Hammerspoon

```lua
-- ~/.hammerspoon/init.lua
local wisper = os.getenv("HOME") .. "/home/wisper"
hs.hotkey.bind({"cmd", "shift"}, "d", function()
    hs.execute("cd " .. wisper .. " && bin/dictate")
end)
```

#### macOS Shortcuts

1. Open **Shortcuts** app → New Shortcut
2. Add **"Run Shell Script"** action
3. Paste: `cd "$HOME/home/wisper" && bin/dictate`
4. Shortcut settings → **Add Keyboard Shortcut** (e.g. ⌘⇧D)

## Architecture

```
bin/dictate (bash)
  ├─ START:  rec (sox) → writes /tmp/dictate_audio.wav, PID saved to /tmp/dictate_recording
  └─ STOP:   kill rec → sleep 0.3 (flush) → python3 dictated.py transcribe → pbcopy → osascript CMD+V

dictated.py (python daemon, keeps model in memory)
  Main loop polls /tmp/dictated/request.json
  → faster-whisper transcribes → writes /tmp/dictated/response.json

float_window.py (pyobjc)
  Background thread reads raw PCM from WAV file tail
  → computes RMS → marshals dot size/color update to main thread
  → dot: 6-28px, red→green based on volume
  → label: "Waiting…" / "Listening" based on voice detection threshold
```

### Why `base` model for dictation?

- **Speed**: `base` transcribes in ~0.5-2s for typical dictation clips vs ~3-8s for `large-v3-turbo`
- **Good enough**: single-speaker dictation is an easy task for `base`
- **Override**: run `DICTATE_MODEL=large-v3-turbo bin/dictate` or edit config if you need higher quality

### Voice level reading

The float window reads audio levels in real-time:
- Background thread reads last 0.15s of raw PCM bytes from `/tmp/dictate_audio.wav`
- Skips `wave.open()` (sox writes placeholder header) — reads raw 32-bit signed int samples
- Computes RMS, normalizes to 0–1 range
- Smoothing: 30% old / 70% new for fast response
- Speaking threshold: level > 0.02

## Latency breakdown

| Step | Time |
|---|---|
| Stop recording (sox flush) | ~300ms |
| Transcription (`base` model, daemon) | ~0.5-2s |
| Clipboard + paste | ~100ms |
| **Total** | **~1-3s** |

## Troubleshooting

| Problem | Fix |
|---|---|
| No mic input | System Settings → Privacy → Microphone → enable Terminal/Hammerspoon |
| "rec: command not found" | `brew install sox` |
| Hotkey works in Terminal but not Hammerspoon/Shortcuts | Run `bin/dictate --check`; the script resolves Homebrew/miniforge paths explicitly |
| Paste doesn't work | Check System Settings → Privacy → Accessibility → enable the trigger app |
| Slow transcription | Use smaller model: set `DICTATE_MODEL=tiny` for `bin/dictate` or edit `dictated.py` |
| Empty output | Check the WAV was recorded: `ls -la /tmp/dictate_audio.wav` |
| Dot doesn't react to voice | Check `/tmp/dictate_audio.wav` exists during recording and grows in size |
| Daemon won't start | Try `python3 dictated.py serve` for foreground logs |

## Customization

### Change model for dictation

In `config.json`:
```json
{
  "dictation": {
    "model": "small"
  }
}
```

Or via environment variable:
```bash
DICTATE_MODEL=small bin/dictate
```

Then restart daemon: `python3 dictated.py stop`

### Add Whisper prompt context

In `config.json`:
```json
{
  "dictation": {
    "initial_prompt": "Transcribe natural speech. Preserve the spoken language.",
    "hotwords": "Wisper faster-whisper CTranslate2 Hammerspoon"
  }
}
```

This is passed to Whisper as `initial_prompt` and `hotwords`. It is not LLM post-processing.

Then restart daemon: `python3 dictated.py stop`

### Change hotkey

In `config.json`:
```json
{
  "hotkey": {
    "modifiers": ["option"],
    "key": "space"
  }
}
```

Supported modifiers: `command`, `option`, `control`, `shift`.
Supported keys: `space`, `a`–`z`, `0`–`9`.

Restart the menu bar app after changing.

### Change recording quality

Edit `bin/dictate`:
```bash
rec -r 48000 -c 1 -q "$WAVFILE"    # 48kHz native Mac rate (default)
rec -r 16000 -c 1 -q "$WAVFILE"    # 16kHz (may warn on some hardware)
```
