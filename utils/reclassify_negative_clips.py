#!/usr/bin/env python3
"""
Interactive reclassification of false-positive clips under raw_pool/curated.

Expects subfolders whose names start with '-' (see copy_curated.py). Run from the
repo root or from utils/ so imports resolve:

    cd utils && python reclassify_negative_clips.py

Requires: pydub, ffmpeg, prompt_toolkit (optional: simpleaudio for playback).
"""

from __future__ import annotations

import shutil
import sys
from collections import defaultdict
from pathlib import Path

from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion

from copy_curated import (
    load_species_folder_map,
    normalize_species_name,
    resolve_from_script,
)
from slice_my_recordings import SUPPORTED_FORMATS, _play_clip, load_audio

# ===== User-editable paths (relative to this script unless absolute) =====
CURATED_ROOT = r"..\raw_pool\curated"
ARCHIVE_ROOT = r"..\raw_pool\archived"
LABELS_FILE = r".\labels.txt"


class PrefixCompleter(Completer):
    """Complete full strings; spaces are part of the prefix (unlike WordCompleter)."""

    def __init__(self, words: list[str], ignore_case: bool = True) -> None:
        self.words = words
        self.ignore_case = ignore_case

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if self.ignore_case:
            prefix = text.lower()
            for w in self.words:
                if w.lower().startswith(prefix):
                    yield Completion(w, start_position=-len(text))
        else:
            for w in self.words:
                if w.startswith(text):
                    yield Completion(w, start_position=-len(text))


def load_autocomplete_terms(labels_file: Path) -> list[str]:
    terms: set[str] = set()
    with labels_file.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or "_" not in line:
                continue
            scientific_name, rest = line.split("_", 1)
            scientific_name = scientific_name.strip()
            common_name = rest.strip()
            if scientific_name:
                terms.add(scientific_name)
            if common_name:
                terms.add(common_name)
    return sorted(terms)


def load_all_label_lines(labels_file: Path) -> set[str]:
    lines: set[str] = set()
    with labels_file.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line and "_" in line:
                lines.add(line)
    return lines


def load_common_to_lines(labels_file: Path) -> dict[str, list[str]]:
    """Normalized common name -> list of full label lines (may be ambiguous)."""
    bucket: dict[str, list[str]] = defaultdict(list)
    with labels_file.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or "_" not in line:
                continue
            _, rest = line.split("_", 1)
            common_name = rest.strip()
            if common_name:
                bucket[normalize_species_name(common_name)].append(line)
    return dict(bucket)


def resolve_input_to_label_line(
    text: str,
    *,
    canonical_lines: set[str],
    sci_to_line: dict[str, str],
    common_to_lines: dict[str, list[str]],
) -> tuple[str | None, str | None]:
    """
    Map user input to the exact labels.txt line (folder basename for positives).
    Returns (line, error_message). error_message set if unresolved.
    """
    stripped = text.strip()
    if not stripped:
        return None, "Empty input."

    if stripped in canonical_lines:
        return stripped, None

    key = normalize_species_name(stripped)
    if key in sci_to_line:
        return sci_to_line[key], None

    if key in common_to_lines:
        candidates = common_to_lines[key]
        if len(candidates) == 1:
            return candidates[0], None
        return None, (
            f"Common name matches multiple species ({len(candidates)}). "
            "Use the scientific name."
        )

    return None, "Species not found in labels.txt."


def format_folder_display(negative_folder_name: str) -> str:
    """Strip leading '-' and show Scientific / Common when possible."""
    name = negative_folder_name[1:] if negative_folder_name.startswith("-") else negative_folder_name
    if "_" in name:
        sci, rest = name.split("_", 1)
        return f"{sci.strip()} / {rest.strip()}"
    return name


def scientific_slug(label_line: str) -> str:
    scientific = label_line.split("_", 1)[0].strip()
    return "_".join(scientific.lower().split())


def collect_negative_clips(curated_root: Path) -> list[Path]:
    clips: list[Path] = []
    if not curated_root.is_dir():
        return clips
    for sub in sorted(curated_root.iterdir()):
        if not sub.is_dir() or not sub.name.startswith("-"):
            continue
        for path in sorted(sub.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_FORMATS:
                clips.append(path)
    return clips


def prompt_yes_no(message: str) -> bool | None:
    """True yes, False no, None on EOF/quit."""
    try:
        ans = input(f"{message} [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if ans in ("y", "yes"):
        return True
    if ans in ("n", "no", ""):
        return False
    return prompt_yes_no(message)


def move_with_collision_handling(src: Path, dest: Path) -> bool:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return True

    print(f"Destination exists: {dest}")
    try:
        choice = input("Overwrite? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if choice not in ("y", "yes"):
        print("Cancelled.")
        return False
    dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True


def process_clip(
    clip_path: Path,
    *,
    curated_root: Path,
    archive_root: Path,
    completer: PrefixCompleter,
    canonical_lines: set[str],
    sci_to_line: dict[str, str],
    common_to_lines: dict[str, list[str]],
) -> str:
    """
    Returns 'next', 'quit', or 'replay_file' if the file stayed in place and
    caller should re-offer the same path (not used; we always advance on skip).
    """
    parent_folder = clip_path.parent.name
    display = format_folder_display(parent_folder)

    print("\n" + "=" * 60)
    print(f"File:     {clip_path}")
    print(f"Negative: {parent_folder}")
    print(f"Species:  {display}")

    audio = load_audio(clip_path)
    if audio is None:
        print("Could not load audio; skipping.")
        return "next"

    def play_current() -> None:
        print("  Playing…")
        _play_clip(audio)

    play_current()

    while True:
        try:
            choice = input(
                "\n[S]kip  [A]rchive  [R]eplay  [L]abel  [Q]uit: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "quit"

        if choice in ("s", "skip", ""):
            return "next"
        if choice in ("q", "quit"):
            return "quit"
        if choice in ("r", "replay"):
            play_current()
            continue
        if choice in ("a", "archive"):
            dest_dir = archive_root / parent_folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / clip_path.name
            if not move_with_collision_handling(clip_path, dest):
                continue
            print(f"Archived -> {dest}")
            return "next"
        if choice in ("l", "label"):
            try:
                species_input = prompt("Species: ", completer=completer)
            except (EOFError, KeyboardInterrupt):
                print()
                return "quit"

            line, err = resolve_input_to_label_line(
                species_input,
                canonical_lines=canonical_lines,
                sci_to_line=sci_to_line,
                common_to_lines=common_to_lines,
            )
            if err or not line:
                print(err or "Could not resolve species.")
                continue

            current_display = f"{display} ({parent_folder})"
            print(f"\nReclassify\n  from: {current_display}\n  to:   {line}")
            yn = prompt_yes_no("Proceed?")
            if yn is None:
                return "quit"
            if not yn:
                print("Cancelled.")
                continue

            slug = scientific_slug(line)
            new_name = f"{slug}_{clip_path.name}"
            dest_dir = curated_root / line
            dest = dest_dir / new_name

            if not move_with_collision_handling(clip_path, dest):
                continue
            print(f"Moved -> {dest}")
            return "next"

        print("Unknown option. Use S, A, R, L, or Q.")


def main() -> None:
    curated_root = resolve_from_script(CURATED_ROOT)
    archive_root = resolve_from_script(ARCHIVE_ROOT)
    labels_file = resolve_from_script(LABELS_FILE)

    if not curated_root.is_dir():
        print(f"Curated root not found: {curated_root}", file=sys.stderr)
        sys.exit(1)
    if not labels_file.is_file():
        print(f"Labels file not found: {labels_file}", file=sys.stderr)
        sys.exit(1)

    clips = collect_negative_clips(curated_root)
    if not clips:
        print(f"No audio clips under negative folders in {curated_root}")
        return

    sci_to_line = load_species_folder_map(labels_file)
    canonical_lines = load_all_label_lines(labels_file)
    common_to_lines = load_common_to_lines(labels_file)
    terms = load_autocomplete_terms(labels_file)
    completer = PrefixCompleter(terms, ignore_case=True)

    print(f"Found {len(clips)} clip(s). Curated: {curated_root}")

    idx = 0
    while idx < len(clips):
        clip_path = clips[idx]
        if not clip_path.exists():
            idx += 1
            continue

        result = process_clip(
            clip_path,
            curated_root=curated_root,
            archive_root=archive_root,
            completer=completer,
            canonical_lines=canonical_lines,
            sci_to_line=sci_to_line,
            common_to_lines=common_to_lines,
        )
        if result == "quit":
            print("Stopped.")
            break
        idx += 1

    print("Done.")


if __name__ == "__main__":
    main()
