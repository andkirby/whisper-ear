# Wisper

Local audio transcription and macOS dictation using `faster-whisper`.

## What It Does

- Transcribe audio/video files to JSON or TXT.
- Record microphone dictation.
- Transcribe locally on CPU.
- Paste dictated text into the active app.
- Run from shell, hotkey launcher, or Python menu bar prototype.

## Quick Start

### File Transcription

```bash
python3 transcribe.py audio.mp4
```

Output goes next to the input file.

Use the wrapper from the repo root:

```bash
bin/f-whisper ~/audio.mp4
```

### Dictation

Press once to record:

```bash
bin/dictate
```

Press again to stop, transcribe, and paste.

Check setup:

```bash
bin/dictate --check
```

### Menu Bar Prototype

```bash
bin/wisper-app
```

Adds a `W` menu bar item.
The terminal stays open while the app runs. Press `Ctrl-C` in that terminal to quit.
Hotkey/menu actions show a small popover on the `W` item with current state.

Hotkey:

```text
Option+Shift+Space
```

## Main Files

| File | Purpose |
|---|---|
| `transcribe.py` | File transcription CLI |
| `dictate.py` | One-shot WAV transcription |
| `dictated.py` | Dictation daemon, keeps model loaded |
| `bin/dictate` | Toggle record/stop/paste script |
| `wisper_app.py` | PyObjC macOS menu bar prototype |
| `bin/wisper-app` | Launcher for the menu bar app |
| `bin/f-whisper` | Wrapper for file transcription |
| `config.json` | Local app configuration |
| `config.example.json` | Default config template |

## Configuration

Edit:

```text
config.json
```

Default hotkey:

```text
Option+Shift+Space
```

See [Configuration](docs/configuration.md).

## Models

Dictation default:

```text
base
```

Better dictation quality:

```bash
DICTATE_MODEL=small bin/dictate
```

Highest practical quality:

```bash
DICTATE_MODEL=large-v3-turbo bin/dictate
```

File transcription default:

```text
large-v3-turbo
```

## Whisper Prompt Context

Use this to bias transcription. This is not LLM cleanup.

```bash
export DICTATE_INITIAL_PROMPT="Transcribe natural speech. Preserve the spoken language. Fix obvious word-boundary errors, names, titles, and capitalization when context makes it clear. Do not translate. Do not rewrite meaning."
export DICTATE_HOTWORDS="Жак Звонарь Фонарь Wisper faster-whisper Hammerspoon"
python3 dictated.py stop
bin/dictate
```

## macOS Permissions

May be needed:

- Microphone, for recording.
- Accessibility, for paste.
- Input Monitoring, for menu bar hotkey.

## Dependencies

```bash
brew install sox
pip install faster-whisper
```

PyObjC is needed for `wisper_app.py`. It is already available in the current miniforge Python.

## More Docs

- [Dictation](docs/dictation.md)
- [Configuration](docs/configuration.md)
- [Transcription](docs/transcription.md)
- [Legacy transcription README](TRANSCRIBE_README.md)
