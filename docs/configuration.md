# Configuration

whisper-ear reads app settings from:

```text
config.json
```

Copy from:

```text
config.example.json
```

## Default

```json
{
  "hotkey": {
    "modifiers": ["option", "shift"],
    "key": "space"
  },
  "dictation": {
    "model": "base",
    "initial_prompt": "",
    "hotwords": "",
    "vad_parameters": {
      "threshold": 0.45,
      "min_speech_duration_ms": 150,
      "min_silence_duration_ms": 500,
      "speech_pad_ms": 250
    }
  },
  "logging": {
    "enabled": true,
    "verbose": false,
    "log_transcripts": false
  }
}
```

## Hotkey

Default:

```text
Option+Shift+Space
```

Supported modifiers:

```text
command
option
control
shift
```

Supported keys:

```text
space
a-z
0-9
```

Examples.

Command+Shift+D:

```json
{
  "hotkey": {
    "modifiers": ["command", "shift"],
    "key": "d"
  }
}
```

Option+Space:

```json
{
  "hotkey": {
    "modifiers": ["option"],
    "key": "space"
  }
}
```

## Dictation

Set model:

```json
{
  "dictation": {
    "model": "small"
  }
}
```

Good choices:

- `base`: fastest default.
- `small`: better dictation quality.
- `large-v3-turbo`: best practical quality, slower.

Add Whisper context:

```json
{
  "dictation": {
    "initial_prompt": "Transcribe natural speech. Preserve the spoken language. Do not translate. Do not rewrite meaning.",
    "hotwords": "whisper-ear WhisperEar faster-whisper Hammerspoon Жак Звонарь Фонарь"
  }
}
```

This is passed to Whisper as `initial_prompt` and `hotwords`.

It is not LLM post-processing.

Tune speech detection:

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

These settings are passed to faster-whisper's Silero-VAD. They are tuned for short live dictation clips, so pauses split faster than long-file transcription.

## Logging

Default:

```json
{
  "logging": {
    "enabled": true,
    "verbose": false,
    "log_transcripts": false
  }
}
```

Logs go to app stdout. With `devpt`:

```bash
devpt logs whisper-ear-app
```

Options:

- `enabled`: print lifecycle and action logs.
- `verbose`: also print full command output.
- `log_transcripts`: print final dictated text. Off by default for privacy.

One-off verbose run:

```bash
bin/whisper-ear-app --verbose
```

Quiet run:

```bash
bin/whisper-ear-app --quiet
```

## Apply Changes

Restart the menu bar app after changing `config.json`.

If the model, prompt, or hotwords changed, also stop the daemon:

```bash
python3 dictated.py stop
bin/whisper-ear-app
```
