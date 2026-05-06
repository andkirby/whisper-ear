import struct

from whisper_ear.audio_levels import read_wav_tail_level, rms_level_from_pcm_i32


def test_rms_level_from_pcm_i32_returns_zero_for_tiny_input():
    assert rms_level_from_pcm_i32(struct.pack("<i", 1000)) == 0.0


def test_rms_level_from_pcm_i32_scales_known_samples():
    raw = struct.pack("<200i", *([200_000_000] * 200))

    assert rms_level_from_pcm_i32(raw) == 1.0


def test_read_wav_tail_level_skips_header(tmp_path):
    wav_path = tmp_path / "audio.wav"
    header = b"0" * 44
    raw = struct.pack("<200i", *([100_000_000] * 200))
    wav_path.write_bytes(header + raw)

    level = read_wav_tail_level(wav_path)

    assert 0.49 < level < 0.51

