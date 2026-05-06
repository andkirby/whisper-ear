# Runtime State Ownership

## Purpose

This document defines where mutable runtime state lives. The goal is to avoid
split-brain behavior between the menu app, shell script, recorder, and daemon.

## Owners

| State | Owner | Storage |
|---|---|---|
| Hotkey registration | `whisper_ear_app.py` | App memory |
| Float window position | `float_window.py` | Config file |
| Float window display mode | `whisper_ear_app.py` | App memory |
| Recording session | dictation controller | Runtime session file and recorder PID |
| Audio file path | dictation controller | Runtime session file |
| Recorder process | dictation controller | Process PID |
| Paste action | dictation controller / CLI | `pbcopy` and System Events |
| Whisper model | `dictated.py` | Daemon memory |
| Daemon lifecycle | `dictated.py` | Socket, pid file, process |
| Daemon status | `dictated.py` | `status` RPC |

## Runtime Directory

Use one private per-user runtime directory:

```text
$TMPDIR/whisper-ear/
```

Expected files:

```text
whisper_ear/
├── dictated.sock
├── daemon.pid
├── daemon.log
├── recording.lock
├── current-session.json
└── audio-<session-id>.wav
```

## Recording Session

`current-session.json` should contain:

```json
{
  "session_id": "20260506-120000-12345",
  "rec_pid": 12345,
  "audio_path": "/tmp/whisper-ear/audio-20260506-120000-12345.wav",
  "started_at": "2026-05-06T12:00:00Z"
}
```

Writes should be atomic: write to a temporary file, then rename.

## Locking

The dictation controller must acquire `recording.lock` before changing recording
state. Rapid hotkey presses should serialize through this lock.

## Cleanup

On startup, `whisper_ear_app.py` may ask the controller to clean stale recording
state. It should not directly own recorder cleanup logic.

The daemon cleans its own socket and pid file on normal shutdown. On startup, it
may remove stale daemon files after checking that no live daemon responds.

