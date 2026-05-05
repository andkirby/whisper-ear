#!/usr/bin/env python3
"""
Audio transcription using faster-whisper with Silero-VAD v6

Transcribes video/audio files to text with timestamps.
Uses VAD to skip silence automatically.

Usage:
  python transcribe.py <audio_file>
  python transcribe.py video.mp4 --model large-v3-turbo  # fastest with good quality
  python transcribe.py audio.mp3 --model distil-large-v3.5 --output result.txt
  python transcribe.py video.webm --model large-v3  # best quality, slower
  python transcribe.py video.webm --word-timestamps  # disable word timestamps
"""

import sys
import argparse
import json
from pathlib import Path
from faster_whisper import WhisperModel


def transcribe_file(audio_path, model_name="large-v3-turbo", output_file=None, language=None, word_timestamps=False, output_format='json'):
    """Transcribe audio file using faster-whisper"""
    audio_path = Path(audio_path)

    if not audio_path.exists():
        print(f"Error: File not found: {audio_path}")
        return False

    print(f"Loading model: {model_name}")
    print(f"Audio file: {audio_path}")
    print(f"File size: {audio_path.stat().st_size / 1024 / 1024:.2f} MB")
    print()

    # Determine default output path if not specified
    if output_file is None:
        output_file = audio_path.parent / f"{audio_path.stem}.{output_format}"
        print(f"Output: {output_file}")
        print()

    # Initialize model with VAD enabled
    # compute_type="int8" is slower but uses less memory
    # compute_type="float16" is faster but requires more memory
    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8"
    )

    if word_timestamps:
        print("Word timestamps: ENABLED")

    # Detect language if not specified
    if language is None:
        print("Detecting language...")
        segments, info = model.transcribe(
            str(audio_path),
            vad_filter=True,  # This uses Silero-VAD v6
            vad_parameters={
                "threshold": 0.5,  # Speech threshold
                "min_speech_duration_ms": 250,  # Min speech chunk
                "min_silence_duration_ms": 2000,  # Min silence to split
                "speech_pad_ms": 400,
            }
        )
        detected_lang = info.language
        language_probability = info.language_probability
        print(f"Detected language: {detected_lang} ({language_probability:.2%})")
    else:
        print(f"Using specified language: {language}")
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
        )

    print()

    # Collect segments for output
    all_segments = []
    total_duration = 0
    full_text = ""

    print("Transcribing...")
    print("-" * 60)

    for segment in segments:
        start = segment.start
        end = segment.end
        text = segment.text.strip()

        seg_data = {
            "id": segment.id,
            "seek": segment.seek,
            "start": start,
            "end": end,
            "text": text,
            "tokens": segment.tokens,
            "temperature": segment.temperature if segment.temperature is not None else 0,
            "avg_logprob": segment.avg_logprob,
            "compression_ratio": segment.compression_ratio,
            "no_speech_prob": segment.no_speech_prob,
            "words": []
        }

        if segment.words:
            print(f"[{start:05.1f}s -> {end:05.1f}s] {text}")
            for word in segment.words:
                word_text = word.word.strip()
                word_start = word.start
                word_end = word.end
                word_prob = word.probability
                seg_data["words"].append({
                    "word": word_text,
                    "start": word_start,
                    "end": word_end,
                    "probability": word_prob
                })
                print(f"  [{word_start:05.1f}s -> {word_end:05.1f}s] {word_text} ({word_prob:.4f})")
        else:
            print(f"[{start:05.1f}s -> {end:05.1f}s] {text}")

        all_segments.append(seg_data)
        total_duration = max(total_duration, end)
        full_text += text + " "

    print("-" * 60)
    print(f"Done! Transcribed {len(all_segments)} segments")
    print(f"Total duration: {total_duration:.1f}s ({total_duration/60:.1f} minutes")
    print()

    # Always write to file (default or specified)
    output_path = Path(output_file)
    
    if output_format == 'json':
        with open(output_path, 'w', encoding='utf-8') as f:
                result = {
                    "text": full_text.strip(),
                    "segments": all_segments,
                    "language": detected_lang if 'detected_lang' in locals() else language
                }
                json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"✓ Saved to: {output_path}")
    else:
        # Text format
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# Transcription from: {audio_path.name}\n")
            f.write(f"# Model: {model_name}\n")
            f.write(f"# Language: {detected_lang if 'detected_lang' in locals() else language}\n")
            f.write(f"# Segments: {len(all_segments)}\n")
            f.write(f"# Total duration: {total_duration:.1f}s\n")
            f.write("# " + "=" * 50 + "\n\n")

            for seg in all_segments:
                minutes = int(seg["start"] // 60)
                seconds = int(seg["start"] % 60)
                timestamp = f"{minutes:02d}:{seconds:02d}"
                f.write(f"{timestamp}\n{seg['text']}\n\n")

        print(f"✓ Saved to: {output_path}")



    return True


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio/video files")
    parser.add_argument("input_file", help="Audio or video file to transcribe")
    parser.add_argument("--model", default="large-v3-turbo",
                        choices=["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3", "large-v3-turbo", "distil-large-v3", "distil-large-v3.5"],
                        help="Whisper model to use (default: large-v3-turbo)")
    parser.add_argument("--output", "-o", help="Output text file")
    parser.add_argument("--language", "-l", help="Language code (e.g., en, de, ru)")
    parser.add_argument("--word-timestamps", action="store_true", help="Extract word-level timestamps")
    parser.add_argument("--format", "-f", choices=['txt', 'json'], default='json', help="Output format (default: json)")

    args = parser.parse_args()
    
    # Ensure output format matches file extension if specified
    if args.output and args.output.endswith('.json'):
        args.format = 'json'
    elif args.output and args.output.endswith('.txt'):
        args.format = 'txt'

    print("Faster-Whisper Transcription")
    print("=" * 50)

    transcribe_file(
        args.input_file,
        model_name=args.model,
        output_file=args.output,
        language=args.language,
        word_timestamps=args.word_timestamps,
        output_format=args.format
    )


if __name__ == "__main__":
    main()
