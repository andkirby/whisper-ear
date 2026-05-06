# Daemon IPC

## Purpose

`dictated.py` keeps the Whisper model warm and transcribes completed audio files.
It should not manage hotkeys, recording, paste behavior, or UI.

## Correct Interface

Use a per-user Unix domain socket:

```text
$TMPDIR/whisper-ear/dictated.sock
```

The runtime directory must be private to the user (`0700`). The daemon should
unlink a stale socket path on startup only after verifying that no live daemon is
serving it.

## Protocol

Use framed JSON over the socket. Newline-delimited JSON is enough because each
connection handles one request and one response.

Request:

```json
{"method":"transcribe","file":"/tmp/whisper-ear/audio-123.wav","language":null}
```

Success response:

```json
{"ok":true,"text":"Hello world"}
```

Error response:

```json
{"ok":false,"error":{"code":"no_speech","message":"No speech detected"}}
```

## Methods

| Method | Owner | Behavior |
|---|---|---|
| `status` | daemon | Returns pid, state, model, keep-loaded flag, and last error. |
| `transcribe` | daemon | Transcribes an existing audio file and returns text or structured error. |
| `shutdown` | daemon | Stops the daemon and cleans runtime socket files. |

## States

```text
starting -> loading -> loaded -> transcribing -> loaded
loaded -> unloaded
unloaded -> loading
any -> stopping
```

The daemon should bind the socket early. While the model is loading, `status`
returns `loading`; `transcribe` may either wait for load or return `loading`
based on client timeout.

## Concurrency

Only one transcription runs at a time. If another transcription request arrives
while the daemon is busy, return:

```json
{"ok":false,"error":{"code":"busy","message":"A transcription is already running"}}
```

Do not use a threaded server for transcription unless `WhisperModel.transcribe`
has been proven safe and useful concurrently.

## Error Codes

| Code | Meaning |
|---|---|
| `invalid_request` | Malformed JSON, missing method, or unsupported method. |
| `file_not_found` | Audio path does not exist or is not a regular file. |
| `busy` | Daemon is already transcribing. |
| `loading` | Model is not ready and request timeout does not allow waiting. |
| `model_load_failed` | Whisper model failed to load. |
| `transcription_failed` | Faster-whisper raised during transcription. |
| `no_speech` | Transcription completed but produced no text. |
| `timeout` | Client or daemon timed out. |
| `shutting_down` | Daemon is stopping. |

## Files Kept

| File | Purpose |
|---|---|
| `dictated.sock` | Primary IPC endpoint. |
| `daemon.pid` | Advisory process discovery for CLI/menu startup. |
| `daemon.log` | Debug log. |

The daemon contract does not include request, response, or status JSON files.
