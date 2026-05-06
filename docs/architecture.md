# whisper-ear Architecture

## System Overview

```mermaid
graph TB
    subgraph menu["Menu bar app"]
        A["whisper_ear_app.py - PyObjC menu bar"]
        B["float_window.py - voice level overlay"]
    end

    subgraph cli["Dictation controller"]
        C["bin/dictate"]
        D["whisper_ear.dictate_cli"]
        E["whisper_ear.recording"]
        F["sox rec"]
    end

    subgraph daemon["Daemon"]
        G["dictated.py - socket RPC server"]
        H["faster-whisper - configurable model, int8"]
    end

    I["$TMPDIR/whisper-ear/current-session.json"]
    J["$TMPDIR/whisper-ear/audio-<session>.wav"]
    K["$TMPDIR/whisper-ear/dictated.sock"]
    L["Active app - cursor position"]
    M["config.json"]

    A -->|hotkey/menu| C
    C --> D
    D --> E
    E --> F
    F -->|writes| J
    E -->|records session| I
    D -->|warmup RPC| K
    D -->|transcribe RPC| K
    K --> G
    G --> H
    G -->|reads| J
    D -->|pbcopy + Cmd+V| L
    B -.->|reads session audio tail| J
    M -.-> A
    M -.-> G
```

## Dictation Flow

```mermaid
sequenceDiagram
    participant User
    participant App as whisper_ear_app.py
    participant CLI as bin/dictate
    participant Rec as sox rec
    participant Runtime as $TMPDIR/whisper-ear
    participant Daemon as dictated.py
    participant Target as Active app

    User->>App: hotkey press
    App->>App: show Listening
    App->>CLI: run asynchronously
    CLI->>Runtime: acquire recording.lock
    CLI->>Rec: start recorder
    CLI->>Runtime: write current-session.json
    CLI->>Daemon: warmup RPC with 5s delay

    User->>App: hotkey press
    App->>App: show Transcribing
    App->>CLI: run asynchronously
    CLI->>Runtime: acquire recording.lock
    CLI->>Rec: stop recorder
    CLI->>Daemon: transcribe RPC over dictated.sock
    Daemon->>Daemon: faster-whisper transcribe
    Daemon-->>CLI: text or structured error
    CLI->>Target: pbcopy + Cmd+V
    CLI->>Runtime: cleanup session/audio
    App->>App: show result or error
```

## Daemon Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Unloaded: start
    [*] --> Loading: start with load_model_on_start
    Loading --> Loaded: model ready
    Unloaded --> Loading: warmup / transcribe
    Loaded --> Transcribing: transcribe request
    Transcribing --> Loaded: response sent
    Loaded --> Unloaded: idle timeout
    Loaded --> Stopping: shutdown
    Unloaded --> Stopping: shutdown
    Stopping --> [*]
```

Default startup binds the socket and reports `state=unloaded` without loading
the STT model. `bin/dictate` schedules `warmup(delay_seconds=5)` after recording
starts, so longer recordings hide most model load time while short recordings
avoid immediate CPU load.

### Auto-Unload Rules

| Model | `keep_loaded_models` | Behavior |
|---|---|---|
| `tiny` | yes | Always in RAM, never unloads |
| `base` | yes | Always in RAM, never unloads |
| `small` | no | Unloads after idle timeout |
| `medium` | no | Unloads after idle timeout |
| `large-v3-turbo` | no | Unloads after idle timeout |

## Runtime State

```text
$TMPDIR/whisper-ear/
├── dictated.sock
├── daemon.pid
├── daemon.log
├── recording.lock
├── current-session.json
└── audio-<session-id>.wav
```

| State | Owner |
|---|---|
| Hotkey and overlay state | `whisper_ear_app.py` |
| Recording session and lock | `whisper_ear.recording` |
| Audio file path | `current-session.json` |
| Model lifecycle | `dictated.py` |
| Daemon status | `status` RPC |
| Paste behavior | `whisper_ear.dictate_cli` / `whisper_ear.paste` |

## Daemon IPC

The daemon uses newline-delimited JSON over a per-user Unix domain socket.

Request:

```json
{"method":"transcribe","file":"/tmp/whisper-ear/audio-123.wav","language":null}
```

Success:

```json
{"ok":true,"text":"Hello world"}
```

Error:

```json
{"ok":false,"error":{"code":"no_speech","message":"No speech detected"}}
```

Supported methods:

| Method | Behavior |
|---|---|
| `status` | Return pid, state, model, keep-loaded flag, and last error. |
| `warmup` | Schedule model loading after an optional delay. |
| `transcribe` | Transcribe an existing audio file. |
| `shutdown` | Stop daemon and clean socket/pid files. |

Only one transcription runs at a time. Extra transcription requests receive
`busy`; status requests can still respond.

## Voice Level Visualization

```mermaid
graph LR
    A["sox rec"] -->|growing WAV| B["audio-<session>.wav"]
    C["current-session.json"] --> D["float_window.py"]
    D -->|reads last 0.15s| B
    D --> E["RMS 32-bit PCM"]
    E --> F["callAfter main thread"]
    F --> G["dot size/color + label"]
```

Key detail: audio levels read raw bytes from the file tail, skipping the 44-byte
WAV header. `wave.open()` is avoided because SoX writes a placeholder header
while recording.

## Memory Usage

| Component | RAM | When |
|---|---|---|
| `whisper_ear_app.py` | ~30 MB | While app is running |
| `dictated.py` | ~20 MB plus model | While daemon is running |
| Whisper `base` model | ~145 MB | Default dictation model |
| Whisper `large-v3-turbo` model | ~809 MB | Default file transcription model |
| `sox rec` | ~5 MB | During recording only |
| Runtime WAV | disk only | During recording/transcription |
