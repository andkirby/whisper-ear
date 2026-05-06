# Architecture Source Of Truth

This directory holds the implementation-level architecture contracts for whisper-ear.
The top-level `docs/architecture.md` is the overview; files here are the source
of truth for specific subsystem behavior.

## Documents

| Document | Purpose |
|---|---|
| `daemon-ipc.md` | Contract for communication with the Whisper daemon. |
| `runtime-state.md` | Defines which process owns each piece of mutable state. |
| `dictation-flow.md` | Correct end-to-end control flow for hotkey dictation. |

## Rules

- One owner for each mutable state.
- UI state is derived from controller or daemon state where possible.
- The daemon owns model lifecycle only.
- Recording and paste behavior stay outside the daemon.
- Runtime files are implementation details, not user-facing API.

