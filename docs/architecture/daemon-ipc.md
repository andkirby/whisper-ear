# Daemon IPC

## Purpose

`dictated.py` owns Whisper model lifecycle and transcribes completed audio
files. It can start unloaded, warm the model after a delay, and keep selected
models resident between dictations. It should not manage hotkeys, recording,
paste behavior, or UI.

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

Warmup request:

```json
{"method":"warmup","delay_seconds":5}
```

Success response:

```json
{"ok":true,"text":"Hello world"}
```

Warmup response:

```json
{"ok":true,"state":"unloaded","warmup_started":true,"delay_seconds":5}
```

Error response:

```json
{"ok":false,"error":{"code":"no_speech","message":"No speech detected"}}
```

## Methods

| Method | Owner | Behavior |
|---|---|---|
| `status` | daemon | Returns pid, state, model, keep-loaded flag, and last error. |
| `warmup` | daemon | Schedules model loading after optional `delay_seconds`; returns immediately. |
| `transcribe` | daemon | Transcribes an existing audio file and returns text or structured error. |
| `shutdown` | daemon | Stops the daemon and cleans runtime socket files. |

## States

```text
starting -> loading -> loaded -> transcribing -> loaded
starting -> unloaded
loaded -> unloaded
unloaded -> loading
any -> stopping
```

The daemon should bind the socket early. By default startup reaches `unloaded`
without loading the model. `warmup` or `transcribe` moves `unloaded -> loading`.
While the model is loading, `status` returns `loading`; `transcribe` may wait
for load based on client timeout.

Repeated `warmup` calls are idempotent while a warmup thread is already running
or the model is already loaded.

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
