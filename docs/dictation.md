# Dictation — Live Mic → Text → Paste

> Global hotkey dictation using `bin/dictate` + `dictated.py`.

## How it works

```
⌘⇧D (press 1) → sox records mic to /tmp/dictate_audio.wav
⌘⇧D (press 2) → sox stops → dictated.py daemon transcribes → pbcopy → CMD+V paste into active app
```

**Toggle mode**: one hotkey, press to start, press again to stop. Text appears at your cursor.

## Files

| File | Purpose |
|---|---|
| `bin/dictate` | Shell script — toggle record/stop, calls dictated.py daemon, pastes result |
| `bin/wisper-app` | macOS menu bar launcher for the Python prototype |
| `dictate.py` | Python — transcribes a WAV file, outputs plain text to stdout |
| `dictated.py` | Python daemon — keeps the Whisper model loaded between dictations |
| `wisper_app.py` | PyObjC menu bar app with Option+Shift+Space monitor |

## Setup

### 1. Install dependencies

```bash
brew install sox              # mic recording
pip install faster-whisper    # transcription engine
```

### 2. Verify

```bash
# Test transcriber directly
rec -r 48000 -c 1 /tmp/test.wav    # speak, then Ctrl+C
python3 dictate.py /tmp/test.wav

# Test hotkey dependencies without recording
bin/dictate --check

# Test full toggle flow
bin/dictate   # press 1 → "Recording…" notification
# speak...
bin/dictate   # press 2 → text pasted + notification
```

### 3. Bind a global hotkey

#### Option A: Python menu bar app prototype

```bash
bin/wisper-app
```

This adds a `W` item to the macOS menu bar. It has:

- `Toggle Dictation`
- `Check Setup`
- `Stop Daemon`
- `Quit`

It also listens for `Option+Shift+Space` while running. macOS may require Accessibility or Input Monitoring permission for the Python process.
The terminal stays open while the app runs. Press `Ctrl-C` in that terminal to quit.
Hotkey/menu actions show a small popover on the `W` item with current state.
While recording, a small floating status window stays visible.
App usage logs go to stdout. With `devpt`, use `devpt logs wisper-app`.
The app registers the hotkey with macOS Carbon first. That consumes the shortcut, so the active app should not receive the Space press. If Carbon registration fails, it falls back to AppKit monitoring, which may not consume the key.

Change the hotkey in `config.json`. See [Configuration](configuration.md).

To launch it in the background:

```bash
nohup bin/wisper-app >/tmp/wisper-app.log 2>&1 &
```

#### Option B: Hammerspoon

```lua
-- ~/.hammerspoon/init.lua
local wisper = os.getenv("HOME") .. "/home/wisper"
hs.hotkey.bind({"cmd", "shift"}, "d", function()
    hs.execute("cd " .. wisper .. " && bin/dictate")
end)
```

#### Option C: macOS Shortcuts

1. Open **Shortcuts** app → New Shortcut
2. Add **"Run Shell Script"** action
3. Paste: `cd "$HOME/home/wisper" && bin/dictate`
4. Shortcut settings → **Add Keyboard Shortcut** (e.g. ⌘⇧D)

#### Option D: Raycast

Create a Script Command pointing to `bin/dictate`, bind a hotkey in Raycast settings.

## Architecture

```
bin/dictate (bash)
  ├─ START:  rec (sox) → writes /tmp/dictate_audio.wav, PID saved to /tmp/dictate_recording
  └─ STOP:   kill rec → sleep 0.3 (flush) → python3 dictated.py transcribe → pbcopy → osascript CMD+V

dictated.py (python daemon)
  faster-whisper (base model, CPU, int8) → Silero-VAD → plain text response
```

### Why `base` model for dictation?

- **Speed**: `base` transcribes in ~0.5-2s for typical dictation clips vs ~3-8s for `large-v3-turbo`
- **Good enough**: single-speaker dictation is an easy task for `base`
- **Override**: run `DICTATE_MODEL=large-v3-turbo bin/dictate` or edit the daemon default if you need higher quality

### Temporary files

| Path | Purpose | Lifespan |
|---|---|---|
| `/tmp/dictate_audio.wav` | Recorded audio | Deleted after transcription |
| `/tmp/dictate_recording` | PID lockfile | Deleted after stop |

## Latency breakdown

| Step | Time |
|---|---|
| Stop recording (sox flush) | ~300ms |
| Transcription (`base` model) | ~0.5-2s |
| Clipboard + paste | ~100ms |
| **Total** | **~1-3s** |

## Troubleshooting

| Problem | Fix |
|---|---|
| No mic input | System Settings → Privacy → Microphone → enable Terminal/Hammerspoon |
| "rec: command not found" | `brew install sox` |
| Hotkey works in Terminal but not Hammerspoon/Shortcuts | Run `bin/dictate --check`; the script resolves Homebrew/miniforge paths explicitly |
| Paste doesn't work | Check System Settings → Privacy → Accessibility → enable the trigger app |
| Slow transcription | Use smaller model: set `DICTATE_MODEL=tiny` for `bin/dictate` or edit `dictated.py` |
| Empty output | Check the WAV was recorded: `ls -la /tmp/dictate_audio.wav` |

## Customization

### Change model for dictation

For the daemon flow, set `DICTATE_MODEL` before launching `bin/dictate`:

```bash
DICTATE_MODEL=small bin/dictate
```

Or edit the default in `dictated.py`:
```python
MODEL_NAME = os.environ.get("DICTATE_MODEL", "small")  # was "base"
```

### Add Whisper prompt context

`faster-whisper` can receive decoder context. This is not LLM post-processing; it nudges Whisper during transcription.

```bash
export DICTATE_INITIAL_PROMPT="This is personal dictation. Preserve the speaker's wording. Use clear punctuation and capitalization."
export DICTATE_HOTWORDS="Wisper faster-whisper CTranslate2 Hammerspoon Raycast"
python3 dictated.py stop
bin/dictate
```

`DICTATE_INITIAL_PROMPT` is useful for style/context. `DICTATE_HOTWORDS` is useful for names, tools, project terms, and uncommon words.

For a hotkey launcher, set the variables in the launcher command:

```lua
local wisper = os.getenv("HOME") .. "/home/wisper"
hs.hotkey.bind({"cmd", "shift"}, "d", function()
    hs.execute('cd ' .. wisper .. ' && DICTATE_INITIAL_PROMPT="This is concise personal dictation." bin/dictate')
end)
```

### Change recording quality

Edit `bin/dictate`:
```bash
rec -r 48000 -c 1 -q "$WAVFILE"    # 48kHz native Mac rate (faster-whisper resamples internally)
rec -r 16000 -c 1 -q "$WAVFILE"    # 16kHz (may warn on some hardware)
```
