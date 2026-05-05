from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from config import get_settings, validate_runtime_settings
from db import connect
from images import (
    IMAGE_DERIVED_DIR,
    IMAGE_FILE_URL_PREFIX,
    IMAGE_OUTPUTS_DIR,
    IMAGE_REFERENCES_DIR,
    ImageGenerationResponse,
    create_image_thumbnail,
    image_file_path,
    image_thumbnail_filename,
    image_thumbnail_relative_path,
)


def _file_url(file_name: str) -> str:
    return f"{IMAGE_FILE_URL_PREFIX}/{file_name}"


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _date_dir(created: int) -> str:
    return time.strftime("%Y/%m/%d", time.gmtime(created))


def _task_dir(job_id: str, created: int) -> str:
    return f"{_date_dir(created)}/{job_id}"


def _compact_stem(role: str, index: int) -> str:
    return f"o{index}" if role == IMAGE_OUTPUTS_DIR else f"r{index}"


def _compact_file_name(task_dir: str, role: str, index: int, extension: str, suffix: int | None = None) -> str:
    stem = _compact_stem(role, index)
    if suffix is not None:
        stem = f"{stem}-{suffix}"
    return f"{task_dir}/{role}/{stem}{extension}"


def _target_file_name(
    image_dir: Path,
    task_dir: str,
    role: str,
    index: int,
    extension: str,
    source: Path | None,
) -> str:
    for suffix in [None, *range(2, 1000)]:
        candidate = _compact_file_name(task_dir, role, index, extension, suffix)
        target = image_dir.joinpath(*candidate.split("/"))
        if source is not None and source == target:
            return candidate
        if not target.exists():
            return candidate
    raise RuntimeError(f"无法为 {task_dir}/{role} 生成可用的短文件名")


def _safe_relative_path(image_dir: Path, file_name: str | None) -> Path | None:
    if not file_name or file_name.startswith("/") or "\\" in file_name:
        return None
    parts = file_name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return image_dir.joinpath(*parts)


def _source_path(image_dir: Path, file_name: str | None, saved_path: str | None = None) -> Path | None:
    relative_path = _safe_relative_path(image_dir, file_name)
    if relative_path is not None:
        return relative_path
    return Path(saved_path) if saved_path else None


def _thumbnail_from_url(image_dir: Path, thumbnail_url: str | None) -> Path | None:
    if not thumbnail_url or not thumbnail_url.startswith(f"{IMAGE_FILE_URL_PREFIX}/"):
        return None
    return _safe_relative_path(image_dir, thumbnail_url.removeprefix(f"{IMAGE_FILE_URL_PREFIX}/"))


def _thumbnail_candidates(image_dir: Path, file_name: str | None, thumbnail_url: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    from_url = _thumbnail_from_url(image_dir, thumbnail_url)
    if from_url is not None:
        candidates.append(from_url)
    if file_name:
        path = _safe_relative_path(image_dir, file_name)
        if path is not None:
            candidates.append(path.with_name(image_thumbnail_filename(path.name)))
            parts = file_name.split("/")
            if len(parts) == 2 and parts[0] in {"generated", "references"}:
                candidates.append(image_dir / "thumbnails" / parts[0] / image_thumbnail_filename(parts[1]))
            elif len(parts) in {5, 6} and parts[-2] in {IMAGE_OUTPUTS_DIR, IMAGE_REFERENCES_DIR}:
                candidates.append(image_dir.joinpath(*parts[:-2], IMAGE_DERIVED_DIR, image_thumbnail_filename(parts[-1])))
            elif len(parts) == 1:
                candidates.append(image_dir / image_thumbnail_filename(file_name))
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _move_if_needed(source: Path | None, target: Path) -> bool:
    _ensure_private_dir(target.parent)
    if target.exists():
        return False
    if source is None or source == target or not source.exists():
        return False
    source.replace(target)
    return True


def _ensure_thumbnail(source_path: Path, thumbnail_path: Path, candidates: list[Path]) -> bool:
    _ensure_private_dir(thumbnail_path.parent)
    if thumbnail_path.exists():
        return True
    for candidate in candidates:
        if candidate != thumbnail_path and candidate.exists():
            candidate.replace(thumbnail_path)
            return True
    return create_image_thumbnail(source_path, thumbnail_path) is not None


def _has_table(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _validate_database(conn: sqlite3.Connection, db_path: Path) -> bool:
    missing = [table for table in ("image_jobs", "image_job_references") if not _has_table(conn, table)]
    if not missing:
        return True
    names = ", ".join(missing)
    print(
        "图片目录整理失败：当前数据库缺少表 "
        f"{names}。\n"
        f"当前数据库路径：{db_path}\n"
        "请确认 SWITCHBOARD_DATA_DIR 指向正在使用的 SwitchBoard 数据目录；"
        "该目录下应已有 switchboard.sqlite。",
        file=sys.stderr,
    )
    return False


def main() -> int:
    settings = get_settings()
    validate_runtime_settings(settings)
    image_dir = settings.image_output_dir or settings.db_path.parent / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    updated = 0
    thumbnails = 0
    skipped = 0
    with connect(settings.db_path) as conn:
        if not _validate_database(conn, settings.db_path):
            return 1
        jobs = list(conn.execute("SELECT id, created_at, result_json FROM image_jobs WHERE result_json IS NOT NULL"))
        for job in jobs:
            task_dir = _task_dir(str(job["id"]), int(job["created_at"]))
            result = ImageGenerationResponse.model_validate_json(job["result_json"])
            changed = False
            for index, item in enumerate(result.data, start=1):
                before = (item.file_name, item.file_url, item.thumbnail_url, item.saved_path, item.url)
                source_name = Path(item.file_name or item.saved_path or f"output-{index}.png").name
                extension = Path(source_name).suffix or ".png"
                source = _source_path(image_dir, item.file_name, item.saved_path)
                target_name = _target_file_name(image_dir, task_dir, IMAGE_OUTPUTS_DIR, index, extension, source)
                target = image_file_path(settings, target_name)
                if _move_if_needed(source, target):
                    moved += 1
                thumbnail_name = image_thumbnail_relative_path(target_name)
                thumbnail_path = image_file_path(settings, thumbnail_name)
                if target.exists() and _ensure_thumbnail(target, thumbnail_path, _thumbnail_candidates(image_dir, item.file_name, item.thumbnail_url)):
                    thumbnails += 1
                item.file_name = target_name
                item.file_url = _file_url(target_name)
                item.thumbnail_url = _file_url(thumbnail_name) if thumbnail_path.exists() else None
                item.saved_path = str(target)
                item.url = item.file_url
                after = (item.file_name, item.file_url, item.thumbnail_url, item.saved_path, item.url)
                if after != before:
                    changed = True
            if changed:
                conn.execute(
                    "UPDATE image_jobs SET result_json = ? WHERE id = ?",
                    (result.model_dump_json(), job["id"]),
                )
                updated += 1

        references = list(
            conn.execute(
                """
                SELECT refs.id, refs.file_name, refs.position, jobs.id AS job_id, jobs.created_at AS job_created_at
                FROM image_job_references refs
                JOIN image_jobs jobs ON jobs.id = refs.job_id
                """
            )
        )
        for reference in references:
            old_name = str(reference["file_name"])
            task_dir = _task_dir(str(reference["job_id"]), int(reference["job_created_at"]))
            source_name = Path(old_name).name
            extension = Path(source_name).suffix or ".png"
            source = _source_path(image_dir, old_name)
            target_name = _target_file_name(
                image_dir,
                task_dir,
                IMAGE_REFERENCES_DIR,
                int(reference["position"]) + 1,
                extension,
                source,
            )
            target = image_file_path(settings, target_name)
            if _move_if_needed(source, target):
                moved += 1
            thumbnail_name = image_thumbnail_relative_path(target_name)
            thumbnail_path = image_file_path(settings, thumbnail_name)
            if target.exists() and _ensure_thumbnail(target, thumbnail_path, _thumbnail_candidates(image_dir, old_name)):
                thumbnails += 1
            if target_name != old_name:
                conn.execute(
                    "UPDATE image_job_references SET file_name = ? WHERE id = ?",
                    (target_name, reference["id"]),
                )
                updated += 1

    print(f"图片目录整理完成：移动 {moved}，更新 {updated}，缩略图就绪 {thumbnails}，跳过 {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
