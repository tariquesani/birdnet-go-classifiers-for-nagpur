from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

# ===== User-editable paths =====
DB_PATH = r"C:\Users\ADMIN\Projects\birdnet-go\birdnet.db"
CLIPS_ROOT = r"C:\Users\ADMIN\Projects\birdnet-go\clips"
FALSE_POSITIVE_ROOT = r"..\raw_pool\false-positive"

# ===== Behavior =====
VERIFIED_VALUE = "false_positive"
PRESERVE_SUBFOLDERS = True
OVERWRITE_EXISTING = False
DRY_RUN = False


def resolve_from_script(path_value: str) -> Path:
    script_dir = Path(__file__).resolve().parent
    path = Path(path_value)
    return path if path.is_absolute() else (script_dir / path).resolve()


def get_reviewed_clip_names(db_path: Path, verified_value: str) -> list[str]:
    query = """
        SELECT d.clip_name
        FROM detection_reviews dr
        JOIN detections d ON d.id = dr.detection_id
        WHERE dr.verified = ?
        ORDER BY dr.id ASC
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(query, (verified_value,)).fetchall()

    clip_names: list[str] = []
    for (clip_name,) in rows:
        if clip_name:
            clip_names.append(clip_name)
    return clip_names


def copy_false_positive_clips(
    clip_names: list[str],
    clips_root: Path,
    output_root: Path,
    preserve_subfolders: bool,
    overwrite_existing: bool,
    dry_run: bool,
) -> dict[str, int]:
    stats = {
        "total_rows": len(clip_names),
        "copied": 0,
        "already_exists": 0,
        "missing_source": 0,
        "errors": 0,
    }

    for clip_name in clip_names:
        source = clips_root / clip_name
        destination = (
            output_root / clip_name
            if preserve_subfolders
            else output_root / Path(clip_name).name
        )

        if not source.exists():
            stats["missing_source"] += 1
            print(f"[MISSING] {source}")
            continue

        if destination.exists() and not overwrite_existing:
            stats["already_exists"] += 1
            print(f"[SKIP] Already exists: {destination}")
            continue

        try:
            if dry_run:
                print(f"[DRY-RUN] Copy {source} -> {destination}")
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                print(f"[COPIED] {source} -> {destination}")
            stats["copied"] += 1
        except OSError as exc:
            stats["errors"] += 1
            print(f"[ERROR] {source} -> {destination}: {exc}")

    return stats


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    db_path = resolve_from_script(DB_PATH)
    clips_root = resolve_from_script(CLIPS_ROOT)
    output_root = resolve_from_script(FALSE_POSITIVE_ROOT)

    print("== False-positive clip exporter ==")
    print(f"SCRIPT_DIR={script_dir}")
    print(f"DB_PATH={db_path}")
    print(f"CLIPS_ROOT={clips_root}")
    print(f"FALSE_POSITIVE_ROOT={output_root}")
    print(f"VERIFIED_VALUE={VERIFIED_VALUE}")
    print(
        "PRESERVE_SUBFOLDERS="
        f"{PRESERVE_SUBFOLDERS}, OVERWRITE_EXISTING={OVERWRITE_EXISTING}, DRY_RUN={DRY_RUN}"
    )
    print()

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    if not clips_root.exists():
        raise FileNotFoundError(f"Clips root not found: {clips_root}")

    clip_names = get_reviewed_clip_names(db_path, VERIFIED_VALUE)
    print(f"Found {len(clip_names)} reviewed clips for '{VERIFIED_VALUE}'.")

    stats = copy_false_positive_clips(
        clip_names=clip_names,
        clips_root=clips_root,
        output_root=output_root,
        preserve_subfolders=PRESERVE_SUBFOLDERS,
        overwrite_existing=OVERWRITE_EXISTING,
        dry_run=DRY_RUN,
    )

    print("\n== Summary ==")
    print(f"Rows matched:     {stats['total_rows']}")
    print(f"Copied:           {stats['copied']}")
    print(f"Already existed:  {stats['already_exists']}")
    print(f"Missing source:   {stats['missing_source']}")
    print(f"Errors:           {stats['errors']}")


if __name__ == "__main__":
    main()
