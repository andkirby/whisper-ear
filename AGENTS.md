# AGENTS.md — Wisper Project

> Source of truth for AI agents working in this repo.

## What this project does

Local audio transcription and dictation using **faster-whisper** (CTranslate2 backend). Main modes:

1. **File transcription** (`transcribe.py`) — transcribe audio/video files to JSON/TXT
2. **Live dictation** (`bin/dictate` + `dictated.py`) — hotkey/menu → record mic → transcribe → paste into active app
3. **macOS menu bar app** (`wisper_app.py` + `float_window.py` + `bin/wisper-app`) — PyObjC menu bar app with float overlay

## Repository layout

```
wisper/
├── AGENTS.md              ← you are here
├── TRANSCRIBE_README.md   ← user-facing docs for transcribe.py
├── transcribe.py          ← file transcription (JSON/TXT output)
├── dictate.py             ← one-shot transcription (stdout, standalone fallback)
├── dictated.py            ← dictation daemon (keeps Whisper model loaded in memory)
├── wisper_app.py          ← macOS PyObjC menu bar app (hotkey, menu, delegates to bin/dictate)
├── float_window.py        ← float overlay (voice level dot, status text, draggable, position persistence)
├── config.json            ← local app config
├── config.example.json    ← default config template
├── bin/
│   ├── f-whisper          ← CLI wrapper for transcribe.py (add to PATH)
│   ├── dictate            ← toggle-record shell script (hotkey/menu target)
│   └── wisper-app         ← launcher for wisper_app.py
├── docs/
│   ├── dictation.md       ← dictation architecture and setup guide
│   ├── configuration.md   ← app config reference
│   └── transcription.md   ← transcription reference
├── models--*/             ← cached HuggingFace model (large-v3-turbo)
├── cards/                 ← (project-local data)
├── vtt/                   ← (project-local data)
└── .venv/                 ← Python virtualenv (has faster-whisper)
```

## Dependencies

| Dependency | Purpose | Install |
|---|---|---|
| `faster-whisper` | Transcription engine (CTranslate2) | `pip install faster-whisper` |
| `sox` | Mic recording via `rec` command | `brew install sox` |
| `pyobjc` | macOS menu bar app + float window | already available in miniforge |
| Python 3.8+ | Runtime | System Python via miniforge |

Check: `python3 -c "from faster_whisper import WhisperModel; print('OK')"`

## Architecture

### Dictation flow

```
Hotkey (Option+Space) ─→ wisper_app.py (Carbon/AppKit monitor)
  │
  ├─ 1st press: bin/dictate → sox rec starts writing /tmp/dictate_audio.wav
  │              float_window shows pulsing dot + "Waiting…" / "Listening"
  │
  └─ 2nd press: bin/dictate → sox stops
                dictated.py daemon transcribes WAV → text
                pbcopy + CMD+V paste into active app
                float_window shows "✓ result" for 1.8s
```

### Module responsibilities

| File | Responsibility |
|---|---|
| `wisper_app.py` | Menu bar app, Carbon hotkey, config, logging. Delegates dictation to `bin/dictate`. |
| `float_window.py` | Float overlay window. Voice-level dot (background thread reads raw PCM from WAV tail), status text, draggable with position persistence. |
| `dictated.py` | Daemon. Loads Whisper model once, listens for file requests via `/tmp/dictated/`. |
| `dictate.py` | Standalone one-shot transcriber (loads model each call). Only used without the daemon. |
| `bin/dictate` | Shell toggle script. Manages recording lockfile, calls daemon for transcription, handles pbcopy+paste. |
| `bin/wisper-app` | Launcher script for `wisper_app.py`. |

### Voice level visualization

The float window reads live audio levels during recording:

1. **Background thread** in `float_window.py` reads the last 0.15s of raw PCM from `/tmp/dictate_audio.wav` (which sox is writing)
2. Computes RMS of 32-bit signed int samples
3. Marshals UI update to main thread via `AppHelper.callAfter`
4. Dot size scales 6–28px, color shifts red→green based on volume
5. Label switches between "Waiting…" (silence) and "Listening" (voice detected)

**Key detail**: We read raw bytes from the file tail (skipping the 44-byte WAV header), not via `wave.open()`. Sox writes a placeholder header with ~2GB frame count — `wave` can't handle that.

## Key decisions

- **CPU-only, int8 quantization** — no GPU required, works on any Mac
- **large-v3-turbo** for file transcription (quality), **base** for dictation (speed)
- **Silero-VAD v6** always on — skips silence, improves accuracy
- **Toggle recording** — single hotkey starts/stops, no hold-to-talk
- **Paste via System Events** — uses `osascript` to CMD+V into the active app
- **Daemon keeps model in memory** — `dictated.py` avoids ~0.8s model load on each dictation
- **Daemon launched via `subprocess.Popen`** — not `os.fork()` (deadlocks with CTranslate2 threads)
- **Carbon hotkey first** — menu app registers the shortcut with macOS so the foreground app should not receive the keypress; AppKit monitor is fallback only
- **No system notifications** — float overlay is the only UI feedback (avoids screen capture of notifications)
- **No popover** — removed in favor of float window
- **Voice level via raw PCM** — background thread reads file tail, not `wave.open()` (which breaks with sox's placeholder header)
- **ObjCPointerWarning suppressed** — `CGColor()` on `NSColor` triggers a harmless warning, suppressed via `warnings.filterwarnings`
- **JSON config** — menu app reads `config.json` for hotkey, model, prompt, and hotwords

## Running

### Transcribe a file
```bash
python3 transcribe.py audio.mp4
python3 transcribe.py video.webm --language de --model large-v3-turbo
```

### Live dictation
```bash
# Setup check
bin/dictate --check

# Manual test
bin/dictate   # press once to start
bin/dictate   # press again to stop+paste
```

### Menu bar app
```bash
bin/wisper-app
```

Adds a `W` menu item, listens for **Option+Space** (configurable in `config.json`). Shows a draggable float overlay with live voice level. macOS may require Microphone, Accessibility, and Input Monitoring permissions.

### Dictation prompt context
```bash
export DICTATE_INITIAL_PROMPT="Transcribe natural speech. Preserve the spoken language. Do not translate. Do not rewrite meaning."
export DICTATE_HOTWORDS="Wisper faster-whisper Hammerspoon"
python3 dictated.py stop
bin/dictate
```

## Conventions

- Output files go next to the input file by default
- `bin/` scripts are self-contained CLI entry points
- Python scripts are importable but primarily CLI tools
- No tests currently — this is a utility project, not a library
- File encodings are UTF-8

## Model choices

| Model | Speed | Quality | Size | Use case |
|---|---|---|---|---|
| `tiny` | Fastest | OK | ~75MB | Testing |
| `base` | Very fast | Good | ~145MB | **Dictation** default |
| `small` | Fast | Very good | ~488MB | Better dictation quality |
| `medium` | Medium | Great | ~769MB | Quality-critical |
| `large-v3-turbo` | Very fast | Great | ~809MB | **File transcription** (default) |
| `distil-large-v3.5` | Fast | Great | ~780MB | Speed+quality |
| `large-v3` | Slow | Best | ~1.5GB | Maximum quality |

## Temporary files

| Path | Purpose | Lifespan |
|---|---|---|
| `/tmp/dictate_audio.wav` | Recorded audio (48kHz mono, 32-bit) | Deleted after transcription |
| `/tmp/dictate_recording` | PID lockfile for toggle | Deleted after stop |
| `/tmp/dictated/daemon.pid` | Daemon PID | Deleted on stop |
| `/tmp/dictated/ready` | Signals model loaded | Deleted on stop |
| `/tmp/dictated/request.json` | Transcription request | Deleted after pickup |
| `/tmp/dictated/response.json` | Transcription result | Deleted after read |

## PyObjC pitfalls (lessons learned)

- `@objc.python_method` methods can't be used as `AppHelper.callLater` targets — they're invisible to the ObjC runtime
- `AppHelper.callAfter` works for dispatching to main thread from background threads
- `os.fork()` deadlocks with CTranslate2 (uses threads internally) — use `subprocess.Popen` instead
- `CALayer.setBackgroundColor_` requires `CGColor()`, not `NSColor` — the `ObjCPointerWarning` is harmless, suppress it
- UI updates must happen on the main thread — use `AppHelper.callAfter` from background threads
