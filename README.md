# whisper-ear

Local audio transcription and macOS dictation using `faster-whisper`.

## What It Does

- Transcribe audio/video files to JSON or TXT.
- Record microphone dictation with a toggle hotkey.
- Transcribe locally on CPU.
- Paste dictated text into the active app.
- Run from shell, hotkey launcher, or macOS menu bar app.

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

Use the whisper-ear dictation daemon for simple text output from a WAV file:

```bash
python3 dictated.py transcribe /tmp/whisper-test-en.wav
```

This prints text to stdout and uses the dictation settings in `config.json`.

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
bin/whisper-ear-app
```

Adds a `W` menu bar item.
The terminal stays open while the app runs. Press `Ctrl-C` in that terminal to quit.
Hotkey/menu actions show a small floating status window with current state.
App usage logs go to stdout. With `devpt`, use `devpt logs whisper-ear-app`.
The app registers the hotkey with macOS, so the active app should not receive the Space press.

Hotkey:

```text
Option+Shift+Space
```

## Main Files

| File | Purpose |
|---|---|
| `transcribe.py` | File transcription CLI |
| `dictate.py` | One-shot WAV transcription |
| `dictated.py` | Dictation daemon, keeps model loaded and serves socket RPC |
| `bin/dictate` | Toggle record/stop/paste entry point |
| `whisper_ear/` | Shared package for config, runtime paths, recording, daemon client, paste, and audio levels |
| `whisper_ear_app.py` | PyObjC macOS menu bar app |
| `bin/whisper-ear-app` | Launcher for the menu bar app |
| `bin/wisper-app` | Compatibility launcher for the old app command |
| `bin/f-whisper` | Wrapper for file transcription |
| `config.json` | Local app configuration |
| `config.example.json` | Default config template |

## Architecture

Dictation runtime state lives under:

```text
$TMPDIR/whisper-ear/
```

The daemon communicates over a per-user Unix socket:

```text
$TMPDIR/whisper-ear/dictated.sock
```

Recording state is session-based (`current-session.json` plus `audio-<session>.wav`), and start/stop operations are serialized with `recording.lock`.

See [Architecture](docs/architecture.md) and [Architecture SOT](docs/architecture/README.md).

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

Use this to bias transcription. This is not LLM cleanup or semantic rewriting.

```bash
export DICTATE_INITIAL_PROMPT="Transcribe natural speech in the spoken language. Do not translate. Do not summarize. Do not rewrite meaning. Preserve technical terms, names, acronyms, commands, file paths, URLs, and code words. Add normal punctuation, capitalization, and paragraph breaks when obvious. Use clear written grammar while keeping the speaker's intent unchanged."
export DICTATE_HOTWORDS="whisper-ear WhisperEar Whisper faster-whisper CTranslate2 Silero VAD PyObjC AppKit Carbon Hammerspoon"
python3 dictated.py stop
bin/dictate
```

## Dictation VAD

Live dictation uses faster-whisper Silero-VAD with short-clip defaults in `config.json`:

```json
{
  "dictation": {
    "vad_parameters": {
      "threshold": 0.45,
      "min_speech_duration_ms": 150,
      "min_silence_duration_ms": 500,
      "speech_pad_ms": 250
    }
  }
}
```

Restart the daemon after changes:

```bash
python3 dictated.py stop
```

## Model Warmup

Recording starts before the STT model is loaded. By default, `bin/dictate` asks the daemon to warm the model 5 seconds after recording starts:

```json
{
  "daemon": {
    "load_model_on_start": false,
    "warm_model_on_recording_start": true,
    "warm_model_delay_seconds": 5
  }
}
```

Short clips avoid unnecessary CPU load; longer clips hide most model load time behind recording.

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

PyObjC is needed for `whisper_ear_app.py`. It is already available in the current miniforge Python.

## More Docs

- [Architecture](docs/architecture.md)
- [Architecture Source Of Truth](docs/architecture/README.md)
- [Dictation](docs/dictation.md)
- [Configuration](docs/configuration.md)
- [Transcription](docs/transcription.md)
- [Changelog](CHANGELOG.md)
- [Legacy transcription README](TRANSCRIBE_README.md)
