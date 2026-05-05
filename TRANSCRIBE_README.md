# Faster-Whisper Transcription Tool

## What's this about?

A Python script that transcribes audio/video files using faster-whisper with Silero-VAD v6. It's a faster alternative to the original OpenAI Whisper, with support for new turbo models.

**Key advantages:**
- 4-8x faster than original Whisper (uses CTranslate2)
- Built-in Silero-VAD v6 for speech/silence detection
- Supports `large-v3-turbo` (8x faster) and `distil-large-v3.5` (5x faster)
- Word-level timestamps support (backward compatible with Whisper)
- JSON output by default
- Less memory usage

## How to use?

### Quick start (recommended)

faster-whisper is installed globally in your miniforge environment. Just use Python 3:

```bash
python3 transcribe.py audio.mp4
# Output: audio.json (same directory, JSON format)
```

### With .venv (isolated environment)

First install faster-whisper in the virtual environment:

```bash
cd .
source .venv/bin/activate
pip install faster-whisper
python transcribe.py audio.mp4
```

### Examples

```bash
# Basic usage (no word timestamps, matches Whisper default)
python3 transcribe.py audio.mp4

# With word timestamps
python3 transcribe.py audio.mp4 --word-timestamps

# With custom output file
python3 transcribe.py audio.mp4 --output result.txt

# Text output instead of JSON
python3 transcribe.py audio.mp4 --format txt

# Specify model (default: large-v3-turbo)
python3 transcribe.py audio.mp4 --model large-v3-turbo
python3 transcribe.py audio.mp4 --model distil-large-v3.5
python3 transcribe.py audio.mp4 --model large-v3

# Specify language (improves accuracy)
python3 transcribe.py audio.mp4 --language ru  # Russian
python3 transcribe.py audio.mp4 --language en  # English
python3 transcribe.py audio.mp4 --language de  # German
```

## Using from the repo root

### Option 1: f-whisper binary (recommended)

A wrapper script is provided at `bin/f-whisper`:

```bash
# Add this repo's bin directory to PATH
export PATH="$(pwd)/bin:$PATH"

# Then use the wrapper
f-whisper ~/videos/my_video.mp4
f-whisper video.mp4 --output result.json
f-whisper audio.mp4 --language ru --word-timestamps
```

### Option 2: Direct Python

```bash
python3 transcribe.py ~/videos/my_video.mp4
```

Note: `f-whisper` wrapper automatically finds the right Python with faster-whisper installed.

## Model choices

| Model | Speed | Quality | Size | Use case |
|-------|-------|---------|------|----------|
| large-v3-turbo | Very fast (8x) | Good | 809MB | Default, most use cases |
| distil-large-v3.5 | Fast (5x) | Good | 780MB | Speed-critical |
| large-v3 | Slow | Best | 1550MB | Production quality |
| medium | Medium | Very Good | 769MB | Balanced |

## Defaults

- **Output format**: JSON
- **Word timestamps**: Disabled (use `--word-timestamps` to enable)
- **Model**: large-v3-turbo
- **Output location**: Same directory as input (same filename, .json extension)

## Output format

Matches original Whisper JSON format with full transcription and segments:

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

## Params support

- `--model`: Model choice
- `--output` / `-o`: Output file
- `--format` / `-f`: txt or json
- `--language` / `-l`: Language code
- `--word-timestamps` / `-w`: Enable word-level timestamps
- `--vad_filter`: Enabled by default (Silero-VAD v6)

Missing features from original Whisper:
- Translation mode (task=translate)
- Multiple output formats (SRT/VTT/TSV)
- Advanced decoding params (beam search, temperature, etc.)

Use original `.venv/bin/whisper` if you need those features.

## Requirements

**Option 1: Global (recommended)**
- Python 3.8+ (already installed in miniforge)
- `faster-whisper 1.2.1` (already installed)
- Model downloads automatically on first run

**Option 2: Virtual environment**
- Python 3.8+ in .venv
- `pip install faster-whisper` in .venv
- Model downloads automatically on first run
