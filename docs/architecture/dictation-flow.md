# Dictation Flow

## Purpose

This document defines the correct end-to-end flow for hotkey dictation.

## Component Responsibilities

| Component | Responsibility |
|---|---|
| `whisper_ear_app.py` | Hotkey, menu status, float overlay updates. |
| Dictation controller | Start/stop recorder, call daemon, paste text, cleanup runtime files. |
| `dictated.py` | Warm/load model on request, keep model loaded, transcribe completed audio files. |
| `float_window.py` | Render overlay and read live WAV tail for voice level. |

## Start Recording

```mermaid
sequenceDiagram
    participant User
    participant App as whisper_ear_app.py
    participant Controller as dictation controller
    participant Sox as sox rec
    participant Daemon as dictated.py
    participant Runtime as $TMPDIR/whisper-ear

    User->>App: hotkey press
    App->>Controller: start recording
    Controller->>Runtime: acquire recording.lock
    Controller->>Sox: spawn recorder
    Controller->>Runtime: write current-session.json
    Controller->>Daemon: warmup(delay_seconds=5)
    Controller-->>App: recording started
    App->>App: show Listening
```

## Stop And Transcribe

```mermaid
sequenceDiagram
    participant User
    participant App as whisper_ear_app.py
    participant Controller as dictation controller
    participant Sox as sox rec
    participant Daemon as dictated.py
    participant Target as Active app

    User->>App: hotkey press
    App->>Controller: stop recording
    App->>App: show Transcribing
    Controller->>Sox: terminate recorder
    Controller->>Daemon: transcribe(audio_path)
    Daemon-->>Controller: text or structured error
    Controller->>Target: pbcopy + Cmd+V
    Controller-->>App: result
    App->>App: show result or error
```

## UI Thread Rule

The menu app must not block the AppKit event loop while transcription runs.
Long-running controller calls should run in a background thread or subprocess,
then update the UI on the main thread.

## Result Handling

| Result | UI behavior | Paste behavior |
|---|---|---|
| Text returned | Show short result | Paste text |
| `no_speech` | Show no speech | Do not paste |
| `busy` | Show busy | Do not paste |
| Other error | Show error | Do not paste |
