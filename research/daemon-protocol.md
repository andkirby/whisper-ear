# Daemon Communication Protocol

## Current approach: file polling

The app (`wisper_app.py`) communicates with the daemon (`dictated.py`) via files in `/tmp/dictated/`:

```
/tmp/dictated/
├── request.json    ← client writes, daemon polls every 50ms
├── response.json   ← daemon writes, client polls every 50ms
├── status.json     ← daemon writes, client reads
├── daemon.pid      ← daemon writes on start
└── ready           ← daemon writes after model load
```

### Request/response cycle

```
bin/dictate                          dictated.py
    │                                    │
    │  write request.json ──────────────>│  (daemon polls, picks up)
    │  {"file": "/tmp/audio.wav"}        │
    │                                    │  load model if needed
    │                                    │  transcribe
    │  poll response.json <─────────────│  write response.json
    │  {"text": "Hello world"}           │
    │                                    │
```

## Problems

### 1. Stale response race condition (FIXED)

If the client times out reading `response.json`, the file stays on disk. The next request reads the **previous** transcription instead of waiting for the new one.

Scenario:
1. Recording A → daemon transcribes → client times out → `response.json` has A's text
2. Recording B → client writes `request.json` → immediately reads stale `response.json`
3. **Result: B gets A's text**

Current fix: request ID matching. Each request gets `"{pid}_{timestamp_ms}"`, daemon echoes it back, client only accepts matching responses.

This patches the symptom but doesn't fix the underlying cause (shared mutable files).

### 2. CPU waste from polling

The daemon loop runs `time.sleep(0.05)` checking for `request.json` — 20 polls/second even when completely idle. Similarly, the client polls `response.json` every 50ms waiting for transcription.

On a Mac laptop this prevents CPU from reaching deepest idle state.

### 3. No concurrent request support

Only one `request.json` / `response.json` file pair. If two hotkey presses arrive close together (e.g. rapid toggle), they collide. The second request overwrites `request.json` before the daemon reads the first.

### 4. No proper error propagation

The client can't distinguish between:
- Daemon crashed mid-transcription → empty response
- No speech detected → empty response
- Model failed to load → empty response

All three look the same: `wait_for_response()` returns `""`.

### 5. Crash leaves stale state

If `bin/dictate` crashes after writing `request.json` but before reading `response.json`, both files linger. The daemon processes the stale request on next loop, writes a response nobody reads, which then poisons the next request (see problem 1).

If the daemon crashes, `daemon.pid` and `status.json` remain on disk, making the client think it's still running.

### 6. Startup synchronization is fragile

`cmd_start()` launches the daemon and polls for `ready` file for up to 30 seconds. If the daemon takes too long to load the model, the client gives up — but the daemon is still starting up and will eventually write `ready`. State mismatch.

## Proposed solution: Unix domain socket

Replace file polling with a Unix domain socket at `/tmp/dictated/socket`.

### Protocol

JSON-RPC over a single socket connection. One connection per request.

```
bin/dictate                          dictated.py (daemon)
    │                                    │
    │── connect ────────────────────────>│  accept()
    │── {"method":"transcribe",          │
    │    "file":"/tmp/audio.wav"} ──────>│
    │                                    │  transcribe...
    │<── {"text":"Hello world"} ─────────│
    │── close ──────────────────────────>│
```

Status queries:

```
wisper_app.py                        dictated.py (daemon)
    │                                    │
    │── connect ────────────────────────>│
    │── {"method":"status"} ────────────>│
    │<── {"model":"base","state":"loaded"}│
    │── close ──────────────────────────>│
```

### Why this is better

| Aspect | File polling | Unix socket |
|---|---|---|
| Race conditions | Shared files, stale state | Connection-scoped, no shared state |
| CPU when idle | 20 polls/sec | `accept()` blocks, zero CPU |
| Concurrent requests | Collide on same files | Separate connections, serialized by daemon |
| Error propagation | Empty string = everything | Structured `{"error": "reason"}` |
| Stale state on crash | Files linger | Kernel cleans up on process exit |
| Coordination files | 5+ files | 1 socket file + pid file |
| Startup sync | Poll `ready` file for 30s | Socket `connect()` fails until ready |

### What stays as files

- `daemon.pid` — needed to check if daemon is running without connecting (e.g. menu app startup)
- `status.json` — optional, for quick status reads without socket overhead
- `daemon.log` — log file, unchanged

### Implementation notes

Python's `socketserver` or manual `socket` + `select` in the daemon loop. The daemon already runs a `while True` loop — replace `if REQUEST_FILE.exists()` with `accept()` + `recv()`.

Client side: `socket.connect()` + `sendall()` + `recv()`. Simpler than the current write-poll-cleanup dance.

Keep backward compatibility: if socket doesn't exist, fall back to file protocol (or just start the daemon which creates the socket).
