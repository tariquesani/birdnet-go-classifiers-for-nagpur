#!/usr/bin/env python3
"""
Xeno-canto Downloader for BirdNET-Go Classifier Training
─────────────────────────────────────────────────────────
Downloads recordings for any species from Xeno-canto.
Raw files are kept by default. Slicing into 3-second clips
is opt-in via --slice.

Usage:
    pip install requests tqdm
    pip install pydub   # only needed if using --slice

    # Download raw recordings for a species:
    python xeno_canto_download.py --species "Passer domesticus"

    # With common name (used for output folder):
    python xeno_canto_download.py --species "Passer domesticus" --common "House Sparrow"

    # Filter by country:
    python xeno_canto_download.py --species "Passer domesticus" --country India

    # Also slice into 3-second training clips:
    python xeno_canto_download.py --species "Passer domesticus" --slice

    # Slice only — skip downloading (if raw files already present):
    python xeno_canto_download.py --species "Passer domesticus" --slice --no-download

Output structure (raw only):
    downloads/
    └── Passer domesticus/
        ├── XC12345.mp3
        ├── XC67890.mp3
        └── ...

Output structure (with --slice):
    downloads/
    └── Passer domesticus/
        ├── XC12345.mp3          <- raw kept by default
        └── clips/
            ├── XC12345_clip0000.wav
            ├── XC12345_clip0001.wav
            └── ...
"""

import os
import sys
import time
import random
import argparse
import requests
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable

# ── Optional pydub (only needed for --slice) ──────────────────────────────────
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_MAX_RECORDINGS  = 150
DEFAULT_QUALITY         = "A,B"
DEFAULT_OUTPUT_DIR      = Path("downloads")
DEFAULT_CLIPS_PER_FILE  = 5
DEFAULT_CLIP_DURATION_S = 3
DELAY_BETWEEN_REQUESTS  = 1.0   # seconds — be polite to the Xeno-canto API
# ─────────────────────────────────────────────────────────────────────────────


# ── Xeno-canto API ────────────────────────────────────────────────────────────

def fetch_recordings(species: str, quality_grades: list, country: str = "") -> list:
    """Query Xeno-canto API v2 and return all matching recording metadata."""
    query = f'"{species}"'
    for grade in quality_grades:
        query += f' q:{grade}'
    if country:
        query += f' cnt:"{country}"'

    recordings = []
    page = 1

    print(f"\n🔍  Querying Xeno-canto for: {species}")
    if country:
        print(f"    Country filter : {country}")
    print(f"    Quality filter : {', '.join(quality_grades)}")

    while True:
        url = (
            f"https://xeno-canto.org/api/2/recordings"
            f"?query={requests.utils.quote(query)}&page={page}"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  ⚠  API request failed (page {page}): {e}")
            break

        data      = resp.json()
        num_pages = int(data.get("numPages", 1))
        recs      = data.get("recordings", [])
        recordings.extend(recs)

        print(f"    Page {page}/{num_pages} — {len(recs)} recordings")

        if page >= num_pages:
            break
        page += 1
        time.sleep(DELAY_BETWEEN_REQUESTS)

    print(f"✅  Total found : {len(recordings)}")
    return recordings


def select_recordings(recordings: list, max_count: int) -> list:
    """Shuffle for variety then cap."""
    random.shuffle(recordings)
    selected = recordings[:max_count]
    print(f"🎲  Selected    : {len(selected)} (shuffled, capped at {max_count})")
    return selected


# ── Download ──────────────────────────────────────────────────────────────────

def download_recording(rec: dict, dest_dir: Path) -> Path | None:
    """
    Download a single recording to dest_dir.
    Skips if file already exists (safe to re-run).
    Returns the local path, or None on failure.
    """
    file_url = rec.get("file")
    if not file_url:
        return None

    if file_url.startswith("//"):
        file_url = "https:" + file_url

    xc_id = rec.get("id", "unknown")
    ext   = Path(file_url.split("?")[0]).suffix or ".mp3"
    dest  = dest_dir / f"XC{xc_id}{ext}"

    if dest.exists():
        return dest   # already downloaded

    try:
        r = requests.get(file_url, stream=True, timeout=60)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return dest
    except Exception as e:
        print(f"  ⚠  Failed XC{xc_id}: {e}")
        return None


# ── Slicing ───────────────────────────────────────────────────────────────────

def slice_to_clips(src_path: Path, clips_dir: Path, xc_id: str,
                   clip_dur_s: int, num_clips: int) -> int:
    """
    Cut num_clips evenly-spaced clips of clip_dur_s seconds from src_path.
    Saves WAV files to clips_dir. Returns count of clips saved.
    """
    if not PYDUB_AVAILABLE:
        print("  ⚠  pydub not installed — cannot slice. Run: pip install pydub")
        return 0

    try:
        audio = AudioSegment.from_file(str(src_path))
        audio = audio.set_channels(1).set_frame_rate(48000).set_sample_width(2)
    except Exception as e:
        print(f"  ⚠  Could not decode {src_path.name}: {e}")
        return 0

    total_ms = len(audio)
    clip_ms  = clip_dur_s * 1000
    saved    = 0

    if total_ms < clip_ms:
        # Too short — pad and save once
        padded   = audio + AudioSegment.silent(duration=clip_ms - total_ms + 100)
        out_path = clips_dir / f"XC{xc_id}_clip0000.wav"
        padded[:clip_ms].export(str(out_path), format="wav")
        return 1

    usable_ms = total_ms - clip_ms
    step      = usable_ms // num_clips

    for i in range(num_clips):
        start = i * step
        end   = start + clip_ms
        if end > total_ms:
            break
        clip     = audio[start:end]
        out_path = clips_dir / f"XC{xc_id}_clip{i:04d}.wav"
        clip.export(str(out_path), format="wav")
        saved += 1

    return saved


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Download Xeno-canto recordings for any species",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # ── Required ──
    parser.add_argument(
        "--species", "-s", required=True,
        help='Scientific name, e.g. "Passer domesticus"'
    )

    # ── Optional metadata ──
    parser.add_argument(
        "--common", "-c", default="",
        help='Common name for display only, e.g. "House Sparrow"'
    )
    parser.add_argument(
        "--country", default="",
        help='Filter by country name, e.g. "India"'
    )
    parser.add_argument(
        "--quality", default=DEFAULT_QUALITY,
        help=f'Comma-separated quality grades (default: {DEFAULT_QUALITY})'
    )
    parser.add_argument(
        "--max", type=int, default=DEFAULT_MAX_RECORDINGS,
        help=f"Max recordings to download (default: {DEFAULT_MAX_RECORDINGS})"
    )

    # ── Output ──
    parser.add_argument(
        "--output", "-o", default=str(DEFAULT_OUTPUT_DIR),
        help=f"Base output directory (default: {DEFAULT_OUTPUT_DIR})"
    )

    # ── Download control ──
    parser.add_argument(
        "--no-download", action="store_true",
        help="Skip downloading — useful if raw files already exist and you just want to slice"
    )

    # ── Slicing (opt-in) ──
    parser.add_argument(
        "--slice", action="store_true",
        help="Slice downloaded recordings into 3-second training clips"
    )
    parser.add_argument(
        "--clips", type=int, default=DEFAULT_CLIPS_PER_FILE,
        help=f"Number of 3-s clips to cut per recording (default: {DEFAULT_CLIPS_PER_FILE}, only used with --slice)"
    )

    args = parser.parse_args()

    # ── Resolve paths ──
    quality_grades = [q.strip() for q in args.quality.split(",")]
    output_base    = Path(args.output)
    species_dir    = output_base / args.species      # e.g. downloads/Passer domesticus/
    clips_dir      = species_dir / "clips"

    display_name = f"{args.species}" + (f" ({args.common})" if args.common else "")

    # ── Print plan ──
    print(f"\n{'─'*55}")
    print(f"🐦  Species     : {display_name}")
    print(f"📁  Raw output  : {species_dir.resolve()}")
    if args.slice:
        print(f"✂️   Clips output : {clips_dir.resolve()}")
    if args.country:
        print(f"🌍  Country     : {args.country}")
    print(f"⭐  Quality     : {', '.join(quality_grades)}")
    print(f"🔢  Max recs    : {args.max}")
    if args.no_download:
        print(f"⏭️   Downloading : SKIPPED")
    print(f"{'─'*55}")

    # ── Create dirs ──
    species_dir.mkdir(parents=True, exist_ok=True)
    if args.slice:
        if not PYDUB_AVAILABLE:
            print("\n⚠  --slice requires pydub:  pip install pydub")
            sys.exit(1)
        clips_dir.mkdir(parents=True, exist_ok=True)

    # ── Fetch + download ──
    downloaded_paths = []

    if not args.no_download:
        recordings = fetch_recordings(args.species, quality_grades, args.country)
        selected   = select_recordings(recordings, args.max)

        print(f"\n⬇️   Downloading recordings …\n")
        for rec in tqdm(selected, unit="rec"):
            path = download_recording(rec, species_dir)
            if path:
                downloaded_paths.append((rec.get("id", "unknown"), path))
            time.sleep(0.2)

        print(f"\n✅  Downloaded : {len(downloaded_paths)} files")
        print(f"    Saved to   : {species_dir.resolve()}")
    else:
        # Collect existing raw files for slicing
        supported = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus"}
        for f in sorted(species_dir.iterdir()):
            if f.suffix.lower() in supported and f.name.startswith("XC"):
                xc_id = f.stem.lstrip("XC")
                downloaded_paths.append((xc_id, f))
        print(f"\n📂  Found {len(downloaded_paths)} existing raw file(s) in {species_dir}")

    # ── Slice (opt-in) ──
    if args.slice:
        if not downloaded_paths:
            print("\n⚠  No files to slice.")
        else:
            print(f"\n✂️   Slicing into {DEFAULT_CLIP_DURATION_S}-second clips …\n")
            total_clips = 0
            for xc_id, raw_path in tqdm(downloaded_paths, unit="file"):
                n = slice_to_clips(
                    raw_path, clips_dir, xc_id,
                    DEFAULT_CLIP_DURATION_S, args.clips
                )
                total_clips += n

            print(f"\n✅  Clips saved : {total_clips} × {DEFAULT_CLIP_DURATION_S}s WAV")
            print(f"    Saved to    : {clips_dir.resolve()}")

    # ── Summary ──
    print(f"\n{'─'*55}")
    print(f"📋  Next steps:")
    if not args.slice:
        print(f"   • Slice raw files into training clips:")
        print(f"     python xeno_canto_download.py --species \"{args.species}\" --slice --no-download")
        print(f"   • Or use slice_my_recordings.py on the raw folder:")
        print(f"     python slice_my_recordings.py --input \"{species_dir}\" --review")
    training_dir = clips_dir if args.slice else species_dir
    print(f"   • Train with BirdNET-Analyzer:")
    print(f"     python -m birdnet_analyzer.train \\")
    print(f"       --i \"{training_dir.resolve()}\" \\")
    print(f"       --o \"{args.species.replace(' ', '_')}_Classifier\" \\")
    print(f"       --epochs 100 \\")
    print(f"       --model_save_mode append \\")
    print(f"       --model_format tflite \\")
    print(f"       --upsampling_ratio 0.5 \\")
    print(f"       --mixup")
    print(f"{'─'*55}\n")


if __name__ == "__main__":
    main()
