# Transcription Reference

> File-based audio/video transcription using `transcribe.py` (faster-whisper + Silero-VAD v6).

## Quick start

```bash
python3 transcribe.py audio.mp4
# Output: audio.json (same directory)
```

## Usage

```bash
# Basic
python3 transcribe.py audio.mp4

# With word timestamps
python3 transcribe.py audio.mp4 --word-timestamps

# Custom output file
python3 transcribe.py audio.mp4 --output result.txt

# Text output instead of JSON
python3 transcribe.py audio.mp4 --format txt

# Specify model
python3 transcribe.py audio.mp4 --model large-v3-turbo    # default
python3 transcribe.py audio.mp4 --model distil-large-v3.5  # 5x faster
python3 transcribe.py audio.mp4 --model large-v3           # best quality

# Specify language (improves accuracy, skips detection)
python3 transcribe.py audio.mp4 --language ru
python3 transcribe.py audio.mp4 --language en
python3 transcribe.py audio.mp4 --language de
```

## CLI flags

| Flag | Short | Default | Description |
|---|---|---|---|
| `--model` | | `large-v3-turbo` | Whisper model to use |
| `--output` | `-o` | `<input>.json` | Output file path |
| `--format` | `-f` | `json` | Output format: `json` or `txt` |
| `--language` | `-l` | auto-detect | Language code (en, de, ru, etc.) |
| `--word-timestamps` | | off | Enable word-level timestamps |

## Model comparison

| Model | Speed | Quality | Size | Use case |
|---|---|---|---|---|
| `large-v3-turbo` | Very fast (8x) | Good | 809MB | **Default**, most use cases |
| `distil-large-v3.5` | Fast (5x) | Good | 780MB | Speed-critical |
| `large-v3` | Slow | Best | 1550MB | Production quality |
| `medium` | Medium | Very Good | 769MB | Balanced |

## Output formats

### JSON (default)

```json
{
  "text": "Full transcription text...",
  "segments": [
    {
      "id": 0,
      "start": 0.5,
      "end": 2.3,
      "text": "Segment text",
      "words": [{"word": "Segment", "start": 0.5, "end": 0.9, "probability": 0.99}]
    }
  ],
  "language": "en"
}
```

### TXT

Plain text with timestamp headers:
```
00:00
First segment text

00:05
Second segment text
```

## Running from the repo root

### Option A: `f-whisper` binary

```bash
export PATH="$(pwd)/bin:$PATH"
f-whisper ~/videos/my_video.mp4
```

### Option B: Direct Python

```bash
python3 transcribe.py ~/audio.mp4
```

## Architecture

```
Input file → ffmpeg (decode) → faster-whisper (CTranslate2, int8) → Silero-VAD v6 (silence skip) → segments → JSON/TXT
```

- **Device**: CPU only (`device="cpu"`, `compute_type="int8"`)
- **VAD**: Always enabled (Silero-VAD v6, threshold=0.5, min_speech=250ms, min_silence=2000ms)
- **Language detection**: Automatic if `--language` not specified

## Limitations vs OpenAI Whisper

Missing features that the original `whisper` CLI has:
- Translation mode (`task=translate`)
- SRT/VTT/TSV output formats (only JSON and TXT)
- Advanced decoding params (beam search, temperature scheduling, etc.)

Use `.venv/bin/whisper` if you need those features.

## Requirements

- Python 3.8+ (miniforge)
- `faster-whisper` (`pip install faster-whisper`)
- Model downloads automatically on first run to `models--*/` cache
