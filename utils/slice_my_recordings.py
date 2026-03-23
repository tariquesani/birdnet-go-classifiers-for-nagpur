#!/usr/bin/env python3
"""
Personal Recording Slicer for BirdNET-Go Classifier Training
─────────────────────────────────────────────────────────────
Slices your own audio files into 3-second WAV clips ready for
BirdNET-Analyzer training.

Usage:
    pip install pydub tqdm
    # Also requires ffmpeg: sudo apt install ffmpeg  (Linux) or brew install ffmpeg (Mac)

    # Slice a folder of recordings:
    python slice_my_recordings.py --input my_recordings/ --label "Passer domesticus_House Sparrow"

    # Slice a single file:
    python slice_my_recordings.py --input sparrow_garden.mp3 --label "Passer domesticus_House Sparrow"

    # Slice with interactive review (play each clip, keep Y/N/R):
    python slice_my_recordings.py --input my_recordings/ --review

    # Slice as Background (ambient/noise clips):
    python slice_my_recordings.py --input ambient/ --label Background

Supported input formats: WAV, MP3, FLAC, OGG, M4A, AAC, AIFF, OPUS
"""

import os
import sys
import tempfile
import argparse
import platform
import subprocess
from pathlib import Path

try:
    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent
except ImportError:
    print("❌  pydub is required.  Install with:  pip install pydub")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable


# ── Cross-platform audio playback ─────────────────────────────────────────────

def _play_clip(clip: AudioSegment):
    """Play a pydub AudioSegment, trying multiple backends gracefully."""

    # 1. Try pydub's built-in play (uses simpleaudio or pyaudio if installed)
    try:
        from pydub.playback import play
        play(clip)
        return
    except Exception:
        pass

    # 2. Fall back to writing a temp WAV and using the OS player
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        clip.export(tmp_path, format="wav")
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["afplay", tmp_path], check=True)
        elif system == "Windows":
            subprocess.run(
                ["powershell", "-c", f'(New-Object Media.SoundPlayer "{tmp_path}").PlaySync()'],
                check=True
            )
        else:  # Linux / other
            # Try common players in order
            for player in ["aplay", "paplay", "ffplay"]:
                if subprocess.run(["which", player], capture_output=True).returncode == 0:
                    args = [player, tmp_path]
                    if player == "ffplay":
                        args = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp_path]
                    subprocess.run(args, check=True)
                    break
            else:
                print("  ⚠  No audio player found. Install simpleaudio: pip install simpleaudio")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def prompt_keep(clip: AudioSegment, clip_label: str) -> bool | None:
    """
    Play clip, then ask Y / N / R.
    Returns True (keep), False (discard), or loops on R (replay).
    Returns None if the user wants to quit early (Q).
    """
    while True:
        print(f"\n  ▶  Playing: {clip_label}")
        _play_clip(clip)
        try:
            answer = input("  Keep? [Y/n/r/q]  (Y=keep  N=discard  R=replay  Q=quit): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n⚠  Interrupted.")
            return None

        if answer in ("", "y"):
            return True
        elif answer == "n":
            return False
        elif answer == "r":
            continue          # replay
        elif answer == "q":
            return None       # signal caller to stop
        else:
            print("  Please enter Y, N, R, or Q.")

# ── Configuration ─────────────────────────────────────────────────────────────
CLIP_DURATION_MS    = 3000      # BirdNET expects exactly 3 seconds
SUPPORTED_FORMATS   = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".aiff", ".opus"}
OUTPUT_BASE         = Path("training_data")

# Silence filtering (optional — see --skip-silent flag)
SILENCE_THRESH_DBFS = -40       # dBFS below which a chunk is "silent"
MIN_SOUND_MS        = 300       # ms of non-silent audio required to keep a clip
# ─────────────────────────────────────────────────────────────────────────────


def load_audio(path: Path) -> AudioSegment | None:
    """Load any supported audio file, return AudioSegment or None on failure."""
    ext = path.suffix.lower().lstrip(".")
    fmt_map = {"m4a": "mp4", "aac": "mp4", "opus": "ogg"}
    fmt = fmt_map.get(ext, ext)
    try:
        audio = AudioSegment.from_file(str(path), format=fmt)
        # Normalise to mono 48kHz 16-bit — BirdNET's preferred format
        audio = audio.set_channels(1).set_frame_rate(48000).set_sample_width(2)
        return audio
    except Exception as e:
        print(f"  ⚠  Could not load {path.name}: {e}")
        return None


def is_silent_clip(clip: AudioSegment) -> bool:
    """Return True if the clip contains no meaningful audio."""
    nonsilent = detect_nonsilent(clip, min_silence_len=50,
                                 silence_thresh=SILENCE_THRESH_DBFS)
    total_sound_ms = sum(end - start for start, end in nonsilent)
    return total_sound_ms < MIN_SOUND_MS


def slice_file(src_path: Path, dest_dir: Path,
               skip_silent: bool, overlap_ms: int,
               review: bool = False) -> tuple[int, int, bool]:
    """
    Slice a single audio file into 3-second clips.
    In review mode, plays each clip and asks Y/N/R before saving.
    Returns (clips_saved, clips_skipped, quit_requested).
    """
    audio = load_audio(src_path)
    if audio is None:
        return 0, 0, False

    total_ms  = len(audio)
    step_ms   = CLIP_DURATION_MS - overlap_ms
    stem      = src_path.stem
    total_clips = (total_ms - CLIP_DURATION_MS) // step_ms + 1

    saved = skipped = 0
    start = 0
    idx   = 0

    def process_clip(clip, label):
        nonlocal saved, skipped
        if skip_silent and is_silent_clip(clip):
            skipped += 1
            return True   # continue

        if review:
            result = prompt_keep(clip, label)
            if result is None:
                return False  # quit signal
            if not result:
                skipped += 1
                return True   # discarded, continue

        out_name = f"{stem}_clip{idx:04d}.wav"
        clip.export(str(dest_dir / out_name), format="wav")
        saved += 1
        return True

    while start + CLIP_DURATION_MS <= total_ms:
        clip  = audio[start : start + CLIP_DURATION_MS]
        ts    = f"{start//1000}s–{(start+CLIP_DURATION_MS)//1000}s"
        label = f"{src_path.name}  [{ts}]  ({idx+1}/{total_clips})"

        if not process_clip(clip, label):
            return saved, skipped, True   # user quit

        start += step_ms
        idx   += 1

    # Handle the tail: if there's a leftover chunk >= 1.5 s, pad it to 3 s
    remainder_ms = total_ms - start
    if remainder_ms >= 1500:
        tail    = audio[start:]
        padding = AudioSegment.silent(duration=CLIP_DURATION_MS - len(tail))
        clip    = tail + padding
        ts      = f"{start//1000}s–end (padded)"
        label   = f"{src_path.name}  [{ts}]  ({idx+1}/{total_clips})"

        if not process_clip(clip, label):
            return saved, skipped, True

    return saved, skipped, False


def collect_audio_files(input_path: Path) -> list[Path]:
    """Return all supported audio files under input_path."""
    if input_path.is_file():
        if input_path.suffix.lower() in SUPPORTED_FORMATS:
            return [input_path]
        else:
            print(f"❌  Unsupported format: {input_path.suffix}")
            sys.exit(1)
    elif input_path.is_dir():
        files = sorted([
            p for p in input_path.rglob("*")
            if p.suffix.lower() in SUPPORTED_FORMATS
        ])
        return files
    else:
        print(f"❌  Path not found: {input_path}")
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Slice personal audio recordings into 3-second BirdNET training clips"
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Path to a single audio file or folder of audio files"
    )
    parser.add_argument(
        "--label", "-l", default="Passer domesticus_House Sparrow",
        help='Output folder label, e.g. "Passer domesticus_House Sparrow" or "Background" '
             '(default: "Passer domesticus_House Sparrow")'
    )
    parser.add_argument(
        "--output", "-o", default=str(OUTPUT_BASE),
        help=f"Base output directory (default: {OUTPUT_BASE})"
    )
    parser.add_argument(
        "--overlap", type=int, default=0,
        help="Overlap between consecutive clips in milliseconds (default: 0). "
             "Use e.g. 1500 to get a 50%% sliding window for more clips."
    )
    parser.add_argument(
        "--skip-silent", action="store_true",
        help="Discard clips that contain mostly silence (recommended)"
    )
    parser.add_argument(
        "--review", action="store_true",
        help="Play each clip and prompt Y/N/R before saving (Y=keep, N=discard, R=replay, Q=quit)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without writing any files"
    )
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_base = Path(args.output)
    dest_dir    = output_base / args.label

    if not args.dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    audio_files = collect_audio_files(input_path)

    if not audio_files:
        print(f"❌  No supported audio files found in: {input_path}")
        sys.exit(1)

    print(f"\n🎵  Found {len(audio_files)} audio file(s) to process")
    print(f"📂  Output label : {args.label}")
    print(f"📁  Output dir   : {dest_dir.resolve()}")
    if args.overlap:
        print(f"🔀  Overlap       : {args.overlap} ms")
    if args.skip_silent:
        print(f"🔇  Silent clips  : will be discarded")
    if args.review:
        print(f"👂  Review mode   : ON  (Y=keep  N=discard  R=replay  Q=quit)")
        try:
            import simpleaudio  # noqa: F401
        except ImportError:
            print("   ℹ  Tip: install simpleaudio for best playback: pip install simpleaudio")
    if args.dry_run:
        print(f"🔍  DRY RUN — no files will be written\n")
    print()

    total_saved = total_skipped = 0
    aborted = False

    for audio_file in tqdm(audio_files, unit="file", disable=args.review):
        if args.dry_run:
            audio = load_audio(audio_file)
            if audio:
                duration_s = len(audio) / 1000
                est_clips  = int(duration_s // 3)
                print(f"  {audio_file.name} — {duration_s:.1f}s → ~{est_clips} clips")
            continue

        if args.review:
            print(f"\n{'─'*55}")
            print(f"📄  File: {audio_file.name}")

        saved, skipped, quit_requested = slice_file(
            audio_file, dest_dir,
            skip_silent=args.skip_silent,
            overlap_ms=args.overlap,
            review=args.review
        )
        total_saved   += saved
        total_skipped += skipped

        if quit_requested:
            print(f"\n⚠  Review quit by user after {total_saved} clips saved.")
            aborted = True
            break

    if args.dry_run:
        return

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'─'*55}")
    print(f"✅  Done!")
    print(f"   Clips saved   : {total_saved}")
    if total_skipped:
        print(f"   Clips skipped : {total_skipped}  (silent)")
    print(f"   Saved to      : {dest_dir.resolve()}")

    print(f"\n📋  Next steps:")
    print(f"   1. Optionally run the Xeno-canto downloader to add more clips:")
    print(f"      python download_house_sparrow.py --country India")
    print(f"   2. Add ambient/noise clips to:  {output_base.resolve()}/Background/")
    print(f"   3. Train with BirdNET-Analyzer:")
    print(f"      python -m birdnet_analyzer.train \\")
    print(f"        --i \"{output_base.resolve()}\" \\")
    print(f"        --o \"HouseSparrow_Classifier\" \\")
    print(f"        --epochs 100 \\")
    print(f"        --model_save_mode append \\")
    print(f"        --model_format tflite \\")
    print(f"        --upsampling_ratio 0.5 \\")
    print(f"        --mixup")
    print(f"{'─'*55}\n")


if __name__ == "__main__":
    main()
