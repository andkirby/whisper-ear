# Wisper Architecture

## System overview

```mermaid
graph TB
    subgraph menu["Menu bar app"]
        A["wisper_app.py — PyObjC menu bar"]
        B["float_window.py — Voice level overlay"]
    end

    subgraph hotkey["Hotkey"]
        C["Carbon hotkey — Option+Space"]
        D["AppKit monitor — fallback"]
    end

    subgraph shell["Shell"]
        E["bin/dictate — toggle script"]
        F["sox rec — mic recording"]
    end

    subgraph daemon["Daemon"]
        G["dictated.py — background process"]
        H["faster-whisper — base model, int8"]
    end

    I["/tmp/dictate_audio.wav"]
    J["Active app — cursor position"]
    K["config.json — hotkey, model, daemon"]

    C -->|pressed| A
    D -->|fallback| A
    A -->|1st press| E
    A -->|2nd press| E
    K -.->|reads| A
    A -->|status and dot| B
    E -->|start| F
    F -->|writes| I
    E -->|transcribe request| G
    G -->|uses| H
    G -->|reads| I
    E -->|pbcopy + CMD+V| J
    B -.->|reads tail| I
```

## Dictation flow (step by step)

```mermaid
sequenceDiagram
    participant User
    participant App as wisper_app.py
    participant Shell as bin/dictate
    participant Sox as sox rec
    participant Daemon as dictated.py
    participant WAV as /tmp/dictate_audio.wav
    participant Target as Active app

    User->>App: Option+Space (1st press)
    App->>App: is_recording = true
    App->>Shell: run bin/dictate
    Shell->>Sox: start rec -r 48000 -c 1
    Sox->>WAV: writes 32-bit PCM
    App->>App: float shows "Listening" + pulsing dot

    Note over App,WAV: Background: float_window.py reads WAV tail for voice level

    User->>App: Option+Space (2nd press)
    App->>App: is_recording = false
    App->>App: float shows "Transcribing..."
    App->>Shell: run bin/dictate
    Shell->>Sox: kill (SIGTERM)
    Shell->>Daemon: write request.json
    Daemon->>WAV: read audio
    Daemon->>Daemon: faster-whisper transcribe
    Daemon->>Daemon: write response.json
    Shell->>Shell: read response, pbcopy
    Shell->>Target: osascript CMD+V
    App->>App: float shows result for 1.8s
```

## Daemon lifecycle (model loading)

```mermaid
stateDiagram-v2
    [*] --> Loading: app start / first dictation

    Loading --> Loaded: model ready (~0.8s)
    Loaded --> Transcribing: request received
    Transcribing --> Loaded: response sent

    Loaded --> Unloaded: idle timeout (5 min default)
    Unloaded --> Loading: new request (reload ~0.8s)

    Loaded --> [*]: SIGTERM / app stop
    Unloaded --> [*]: SIGTERM / app stop
```

### Auto-unload rules

| Model | `keep_loaded_models` | Behavior |
|---|---|---|
| `tiny` | ✅ yes | Always in RAM, never unloads |
| `base` | ✅ yes | Always in RAM, never unloads |
| `small` | ❌ no | Unloads after 5min idle, reloads on demand |
| `medium` | ❌ no | Unloads after 5min idle, reloads on demand |
| `large-v3-turbo` | ❌ no | Unloads after 5min idle, reloads on demand |

Configured in `config.json`:
```json
{
  "daemon": {
    "unload_timeout_minutes": 5,
    "keep_loaded_models": ["tiny", "base"]
  }
}
```

## State management (what lives where)

```mermaid
graph TB
    subgraph mem["In memory - wisper_app.py"]
        A["is_recording: bool"]
        B["float window — position, dot, label"]
        C["config dict — hotkey, model, daemon"]
    end

    subgraph fs["/tmp - filesystem protocol"]
        D["dictate_audio.wav — 48kHz 32-bit mono"]
        E["dictate_recording — PID lockfile"]
        F["dictated/request.json — file path + language"]
        G["dictated/response.json — transcribed text"]
        H["dictated/status.json — state + model + pid"]
        I["dictated/daemon.pid — daemon PID"]
        J["dictated/daemon.log — timestamped events"]
    end

    subgraph proc["Daemon process"]
        K["dictated.py — polling loop"]
        L["WhisperModel — base, CPU, int8"]
    end

    A -->|manages| E
    K -->|polls| F
    K -->|writes| G
    K -->|writes| H
    K -->|uses| L
    L -.->|reads| D
```

### Communication protocol

The app and daemon communicate via files in `/tmp/dictated/`:

```
bin/dictate                           dictated.py
    │                                     │
    │  write /tmp/dictated/request.json   │
    │ ──────────────────────────────────> │
    │  {"file": "/tmp/dictate_audio.wav"} │
    │                                     │ load model if unloaded
    │                                     │ transcribe audio
    │  read /tmp/dictated/response.json   │
    │ <────────────────────────────────── │
    │  {"text": "Hello world"}            │
    │                                     │
    │  pbcopy + CMD+V into active app     │
```

## Voice level visualization

```mermaid
graph LR
    A["sox rec - writes WAV"] -->|growing file| B["/tmp/dictate_audio.wav"]
    B -->|reads last 0.15s| C["RMS calculation - 32-bit PCM samples"]
    C -->|level 0..1| D["callAfter - main thread"]
    D --> E["dot size: 6-28px"]
    D --> F["color: red to green"]
    D --> G["label: Waiting / Listening"]
```

Key detail: reads **raw bytes** from file tail (skipping 44-byte WAV header), not via `wave.open()`. Sox writes a placeholder header with ~2GB frame count that breaks `wave`.

## Process lifecycle

```mermaid
graph TB
    subgraph User actions
        Start[bin/wiser-app] 
        Hotkey[Option+Space]
        Quit[Quit menu]
    end

    subgraph Processes
        App[wiser_app.py<br/>menu bar app]
        Daemon[dictated.py<br/>background daemon]
        Rec[sox rec<br/>mic capture]
    end

    Start -->|launches| App
    App -->|auto-starts if needed| Daemon
    Hotkey -->|1st press| Rec
    Hotkey -->|2nd press| Daemon
    Quit -->|terminates| App

    Note1[Daemon survives app quit<br/>must stop via menu or CLI]
    Note2[Recording state is in-memory<br/>no stale state after restart]
```

## Memory usage

| Component | RAM | When |
|---|---|---|
| `wiser_app.py` | ~30 MB | While app is running |
| `dictated.py` (daemon) | ~20 MB | Always (survives app quit) |
| Whisper `base` model | ~145 MB | While loaded (pinned) |
| Whisper `small` model | ~488 MB | While loaded (auto-unloads) |
| `sox rec` | ~5 MB | During recording only |
| `/tmp/dictate_audio.wav` | disk only | During recording |
