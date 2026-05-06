# Changelog

## Milestone 1 - whisper-ear foundation

Date: 2026-05-06

- Renamed the app identity to `whisper-ear`.
- Added `whisper_ear/` shared package for config, runtime paths, recording sessions, daemon client, paste, and audio-level helpers.
- Replaced daemon file polling with Unix socket JSON RPC at `$TMPDIR/whisper-ear/dictated.sock`.
- Moved recording runtime state to `$TMPDIR/whisper-ear/`.
- Added session-based recording metadata and a recording lock.
- Kept `bin/dictate` and added `bin/whisper-ear-app`.
- Kept `bin/wisper-app` as a compatibility launcher.
- Made menu app dictation calls run off the AppKit event loop.
- Added focused pytest coverage for config, runtime paths, audio levels, daemon client, and recording session behavior.
- Added architecture source-of-truth docs under `docs/architecture/`.

