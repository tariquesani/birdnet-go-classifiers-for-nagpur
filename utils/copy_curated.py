from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import TypedDict

# ===== User-editable paths =====
DB_PATH = r"C:\Users\ADMIN\Projects\birdnet-go\birdnet.db"
CLIPS_ROOT = r"C:\Users\ADMIN\Projects\birdnet-go\clips"
OUTPUT_ROOT = r"..\raw_pool\curated"
LABELS_FILE = r".\labels.txt"

# ===== Behavior =====
FALSE_POSITIVE_VALUE = "false_positive"
VERIFIED_VALUE = "correct"
OVERWRITE_EXISTING = False
DRY_RUN = False


class ReviewedDetection(TypedDict):
    clip_name: str
    scientific_name: str
    verified: str


def resolve_from_script(path_value: str) -> Path:
    script_dir = Path(__file__).resolve().parent
    path = Path(path_value)
    return path if path.is_absolute() else (script_dir / path).resolve()


def normalize_species_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def load_species_folder_map(labels_file: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with labels_file.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or "_" not in line:
                continue
            scientific_name = line.split("_", 1)[0].strip()
            if not scientific_name:
                continue
            mapping[normalize_species_name(scientific_name)] = line
    return mapping


def get_reviewed_detections(
    db_path: Path,
    false_positive_value: str,
    verified_value: str,
) -> list[ReviewedDetection]:
    query = """
        SELECT d.clip_name, l.scientific_name, dr.verified
        FROM detection_reviews dr
        JOIN detections d ON d.id = dr.detection_id
        JOIN labels l ON l.id = d.label_id
        WHERE dr.verified IN (?, ?)
        ORDER BY dr.id ASC
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(query, (false_positive_value, verified_value)).fetchall()

    detections: list[ReviewedDetection] = []
    for clip_name, scientific_name, verified in rows:
        if not clip_name or not scientific_name:
            continue
        detections.append(
            {
                "clip_name": clip_name,
                "scientific_name": scientific_name,
                "verified": verified,
            }
        )
    return detections


def resolve_species_folder_name(
    scientific_name: str,
    verified: str,
    species_folder_map: dict[str, str],
    false_positive_value: str,
) -> tuple[str, bool]:
    lookup_key = normalize_species_name(scientific_name)
    base_folder = species_folder_map.get(lookup_key)
    mapping_miss = base_folder is None
    if mapping_miss:
        base_folder = scientific_name.strip().replace("/", "-").replace("\\", "-")

    if verified == false_positive_value:
        return f"-{base_folder}", mapping_miss
    return base_folder, mapping_miss


def copy_reviewed_clips(
    detections: list[ReviewedDetection],
    clips_root: Path,
    output_root: Path,
    species_folder_map: dict[str, str],
    false_positive_value: str,
    overwrite_existing: bool,
    dry_run: bool,
) -> dict[str, int]:
    stats = {
        "total_rows": len(detections),
        "copied": 0,
        "false_positive_rows": 0,
        "verified_rows": 0,
        "already_exists": 0,
        "missing_source": 0,
        "mapping_missing": 0,
        "errors": 0,
    }

    for detection in detections:
        clip_name = detection["clip_name"]
        scientific_name = detection["scientific_name"]
        verified = detection["verified"]
        if verified == false_positive_value:
            stats["false_positive_rows"] += 1
        else:
            stats["verified_rows"] += 1

        species_folder, mapping_miss = resolve_species_folder_name(
            scientific_name=scientific_name,
            verified=verified,
            species_folder_map=species_folder_map,
            false_positive_value=false_positive_value,
        )
        if mapping_miss:
            stats["mapping_missing"] += 1
            print(f"[MAPPING-MISS] {scientific_name} -> {species_folder}")

        source = clips_root / clip_name
        destination = output_root / species_folder / Path(clip_name).name

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
    output_root = resolve_from_script(OUTPUT_ROOT)
    labels_file = resolve_from_script(LABELS_FILE)

    print("== Reviewed clip exporter ==")
    print(f"SCRIPT_DIR={script_dir}")
    print(f"DB_PATH={db_path}")
    print(f"CLIPS_ROOT={clips_root}")
    print(f"OUTPUT_ROOT={output_root}")
    print(f"LABELS_FILE={labels_file}")
    print(
        f"FALSE_POSITIVE_VALUE={FALSE_POSITIVE_VALUE}, VERIFIED_VALUE={VERIFIED_VALUE}"
    )
    print(
        f"OVERWRITE_EXISTING={OVERWRITE_EXISTING}, DRY_RUN={DRY_RUN}"
    )
    print()

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    if not clips_root.exists():
        raise FileNotFoundError(f"Clips root not found: {clips_root}")
    if not labels_file.exists():
        raise FileNotFoundError(f"Labels file not found: {labels_file}")

    species_folder_map = load_species_folder_map(labels_file)
    detections = get_reviewed_detections(
        db_path=db_path,
        false_positive_value=FALSE_POSITIVE_VALUE,
        verified_value=VERIFIED_VALUE,
    )
    print(
        f"Found {len(detections)} reviewed clips for "
        f"'{FALSE_POSITIVE_VALUE}' and '{VERIFIED_VALUE}'."
    )
    print(f"Loaded {len(species_folder_map)} species labels.")

    stats = copy_reviewed_clips(
        detections=detections,
        clips_root=clips_root,
        output_root=output_root,
        species_folder_map=species_folder_map,
        false_positive_value=FALSE_POSITIVE_VALUE,
        overwrite_existing=OVERWRITE_EXISTING,
        dry_run=DRY_RUN,
    )

    print("\n== Summary ==")
    print(f"Rows matched:     {stats['total_rows']}")
    print(f"False positive:   {stats['false_positive_rows']}")
    print(f"Verified:         {stats['verified_rows']}")
    print(f"Copied:           {stats['copied']}")
    print(f"Already existed:  {stats['already_exists']}")
    print(f"Missing source:   {stats['missing_source']}")
    print(f"Mapping missing:  {stats['mapping_missing']}")
    print(f"Errors:           {stats['errors']}")


if __name__ == "__main__":
    main()
