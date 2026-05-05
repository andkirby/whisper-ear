# AGENTS.md — Wisper Project

> Source of truth for AI agents working in this repo.

## What this project does

Local audio transcription and dictation using **faster-whisper** (CTranslate2 backend). Main modes:

1. **File transcription** (`transcribe.py`) — transcribe audio/video files to JSON/TXT
2. **Live dictation** (`bin/dictate` + `dictated.py`) — hotkey/menu → record mic → transcribe → paste into active app
3. **macOS menu bar prototype** (`wisper_app.py` + `bin/wisper-app`) — PyObjC wrapper around dictation

## Repository layout

```
wisper/
├── AGENTS.md              ← you are here
├── README.md              ← project overview and quick start
├── TRANSCRIBE_README.md   ← user-facing docs for transcribe.py
├── transcribe.py          ← file transcription (JSON/TXT output)
├── dictate.py             ← one-shot transcription (stdout)
├── dictated.py            ← dictation daemon (keeps Whisper model loaded)
├── wisper_app.py          ← macOS PyObjC menu bar prototype
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
| `pyobjc` | macOS menu bar prototype | already available in miniforge |
| Python 3.8+ | Runtime | System Python via miniforge |

Check: `python3 -c "from faster_whisper import WhisperModel; print('OK')"`

## Key decisions

- **CPU-only, int8 quantization** — no GPU required, works on any Mac
- **large-v3-turbo** for file transcription (quality), **base** for dictation (speed)
- **Silero-VAD v6** always on — skips silence, improves accuracy
- **Toggle recording** — single hotkey starts/stops, no hold-to-talk
- **Paste via System Events** — uses `osascript` to CMD+V into the active app
- **Whisper prompt context** — optional `DICTATE_INITIAL_PROMPT` and `DICTATE_HOTWORDS`; no LLM/API post-processing
- **Python app first** — `wisper_app.py` is a fast macOS prototype, not a packaged app yet
- **Carbon hotkey first** — menu app registers the shortcut with macOS so the foreground app should not receive the keypress; AppKit monitor is fallback only
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

### Menu bar prototype
```bash
bin/wisper-app
```

It adds a `W` menu item and listens for `Option+Shift+Space`. macOS may require Microphone, Accessibility, and Input Monitoring permissions.

Bind `bin/dictate` to a global hotkey or run `bin/wisper-app` (see `docs/dictation.md`).

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
