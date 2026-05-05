#!/usr/bin/env python3
"""
Read script.md aloud using Kokoro TTS.
Skips headings (lines starting with #) and [Pause] markers.
Streams audio sentence by sentence and prints each sentence as it plays.

Usage:
  python read_script.py                  # reads script.md, plays audio
  python read_script.py --save out.wav   # saves to file instead of playing
  python read_script.py --speed 1.1      # adjust speed (default 1.0)
  python read_script.py --voice af_heart # change voice (default af_heart)
"""

import re
import sys
import argparse
import subprocess
import tempfile
import textwrap
from pathlib import Path

SCRIPT_MD = Path(__file__).parent / "script.md"
SAMPLE_RATE = 24000
TERM_WIDTH = 72


def clean_sentences(md_path: Path) -> list[str]:
    """Return a flat list of sentences, headings and [stage directions] removed."""
    lines = md_path.read_text(encoding="utf-8").splitlines()
    paragraphs = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        stripped = re.sub(r"\[.*?\]", "", stripped).strip()
        if stripped:
            paragraphs.append(stripped)

    # Split paragraphs into individual sentences
    sentences = []
    for para in paragraphs:
        # Split on sentence-ending punctuation followed by whitespace or end
        parts = re.split(r'(?<=[.!?])\s+', para)
        for part in parts:
            part = part.strip()
            if part:
                sentences.append(part)
    return sentences


def print_sentence(index: int, total: int, text: str) -> None:
    bar_width = 20
    filled = int(bar_width * index / total)
    bar = "█" * filled + "░" * (bar_width - filled)
    pct = f"{index}/{total}"
    prefix = f"  [{bar}] {pct}  "
    indent = " " * len(prefix)
    wrapped = textwrap.fill(text, width=TERM_WIDTH, subsequent_indent=indent)
    print(f"\033[2m{prefix}\033[0m\033[1m{wrapped}\033[0m")


def play_wav(path: str) -> None:
    subprocess.run(["afplay", path], check=False)


def main():
    parser = argparse.ArgumentParser(description="Read script.md with Kokoro TTS")
    parser.add_argument("--file", default=str(SCRIPT_MD), help="Markdown file to read")
    parser.add_argument("--voice", default="af_heart", help="Kokoro voice (default: af_heart)")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed (default: 1.0)")
    parser.add_argument("--save", metavar="OUTPUT.wav", help="Save concatenated WAV instead of playing")
    args = parser.parse_args()

    sentences = clean_sentences(Path(args.file))
    if not sentences:
        print("Nothing to read after filtering.", file=sys.stderr)
        sys.exit(1)

    total = len(sentences)
    print(f"Voice: {args.voice}  Speed: {args.speed}  Sentences: {total}\n")

    import warnings
    warnings.filterwarnings("ignore")

    from kokoro import KPipeline
    import soundfile as sf
    import numpy as np

    pipeline = KPipeline(lang_code="a")

    # Generate all audio first, printing progress as each sentence is processed
    print("Generating audio...")
    all_audio = []
    for i, sentence in enumerate(sentences, 1):
        print_sentence(i, total, sentence)
        chunks = list(pipeline(sentence, voice=args.voice, speed=args.speed))
        for _, _, audio in chunks:
            all_audio.append(audio)
    combined = np.concatenate(all_audio)

    if args.save:
        sf.write(args.save, combined, SAMPLE_RATE)
        print(f"\nSaved to {args.save}")
    else:
        print("\nPlaying...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, combined, SAMPLE_RATE)
            play_wav(tmp.name)
        print("\033[2mDone.\033[0m")


if __name__ == "__main__":
    main()
