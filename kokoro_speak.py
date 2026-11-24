#!/usr/bin/env python3
"""Local Kokoro ONNX speech synthesis worker used by modules.voice."""
import sys
import soundfile as sf
from kokoro_onnx import Kokoro

if len(sys.argv) != 6:
    raise SystemExit("usage: kokoro_speak.py MODEL VOICES VOICE OUTPUT_WAV TEXT")
model_path, voices_path, voice, output_path, text = sys.argv[1:]
lang = "en-gb" if voice.startswith(("bf_", "bm_")) else "en-us"
engine = Kokoro(model_path, voices_path)
samples, sample_rate = engine.create(text, voice=voice, speed=1.0, lang=lang)
sf.write(output_path, samples, sample_rate, subtype="PCM_16", format="WAV")
