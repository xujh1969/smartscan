"""Batch orchestration: idempotent runs, error isolation, cancellation, atomic saves."""

from __future__ import annotations

import datetime
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image

from .detection import DETECTOR_VERSION, detect_quads, estimate_background, resolve_occlusion
from .metadata import build_text_chunk, read_metadata, write_png
from .models import BatchConfig, BatchResult, Flags, OrientationState, PhotoQuad, SplitResult
from .naming import content_hash, find_existing, next_name, reserve_name
from .orientation import should_auto_rotate, vote
from .rotation import apply_state
from .review import load_review
from .split import deskew_and_crop

Progress = Callable[[int, int, str], None]
Cancel = Callable[[], bool]
_DISK_FACTOR = 3


def log_file_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "SmartScan" / "logs" / "smartscan.log"


def _append_log(message: str) -> None:
    path = log_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            stamp = datetime.datetime.now().isoformat(timespec="seconds")
            handle.write(f"{stamp} {message}\n")
    except OSError:
        pass


def estimate_disk_need(config: BatchConfig) -> int:
    return sum(
        path.stat().st_size for path in config.source_files if path.exists()
    ) * _DISK_FACTOR


def _load_existing(output_dir: Path) -> list[dict]:
    metas: list[dict] = []
    for png in sorted(output_dir.glob("*.png")):
        try:
            meta = read_metadata(png)
        except Exception:
            continue
        if (meta.get("source") and meta.get("digest")
                and meta.get("detector_version") == DETECTOR_VERSION):
            metas.append(
                {"path": str(png), "source": meta["source"], "digest": meta["digest"],
                 "review_revision": meta.get("review_revision", "")}
            )
            metas[-1]["review_crop_index"] = meta.get("review_crop_index", "")
    return metas


def _read_source(path: Path) -> tuple[np.ndarray, tuple[float, float], bytes | None]:
    with Image.open(path) as image:
        dpi = image.info.get("dpi") or (300.0, 300.0)
        icc = image.info.get("icc_profile")
        array = np.asarray(image)
        mode = image.mode
    if array.dtype != np.uint8 or mode not in ("L", "RGB", "RGBA"):
        raise ValueError("仅支持 8bit/通道输入；更高位深请人工处理以免降低清晰度")
    if array.ndim == 2:
        import cv2

        array = cv2.cvtColor(array, cv2.COLOR_GRAY2RGB)
    elif array.shape[2] == 4:
        array = array[:, :, :3]
    return array, (float(dpi[0]), float(dpi[1])), icc


def _auto_orientation(crop: np.ndarray) -> tuple[np.ndarray, int, str, list[str]]:
    angle = should_auto_rotate(vote(crop))
    if not angle:
        return crop, 0, OrientationState.UNKNOWN, []
    state = 90 if angle == 90 else 270
    return (
        apply_state(crop, state),
        state,
        OrientationState.AUTO,
        [Flags.AUTO_ROTATED],
    )


def _save_photo(
    output_dir: Path,
    index: int,
    digest: str,
    source_key: str,
    crop: np.ndarray,
    quad: PhotoQuad,
    rotation: int,
    orientation: str,
    extra_flags: list[str],
    dpi: tuple[float, float],
    icc: bytes | None,
    review_revision: str = "",
    review_crop_index: int | None = None,
) -> SplitResult:
    target = reserve_name(output_dir, next_name(index, digest))
    text = build_text_chunk(
        source=source_key,
        digest=digest,
        quad=quad.ordered(),
        tilt_deg=quad.tilt_deg,
        rotation=rotation,
        orientation=orientation,
        flags=quad.flags() + extra_flags,
        confidence=quad.confidence,
    )
    text["detector_version"] = DETECTOR_VERSION
    text["detection_method"] = "reviewed" if review_revision else "automatic"
    text["review_revision"] = review_revision
    if review_crop_index is not None:
        text["review_crop_index"] = str(review_crop_index)
    write_png(target, Image.fromarray(crop), dpi=dpi, icc=icc, text=text)
    return SplitResult(
        path=target,
        source=source_key,
        digest=digest,
        rotation=rotation,
        orientation=orientation,
        tilt_deg=quad.tilt_deg,
        confidence=quad.confidence,
        flags=quad.flags() + extra_flags,
    )


def run(
    config: BatchConfig,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> BatchResult:
    raw_report = progress or (lambda *_: None)

    def report(done: int, total: int, stage: str) -> None:
        raw_report(done, total, stage)
        _append_log(f"{done}/{total} {stage}")

    should_cancel = cancel or (lambda: False)
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    if estimate_disk_need(config) > shutil.disk_usage(str(output_dir)).free:
        raise OSError("输出目录磁盘空间不足，已停止处理")

    existing = _load_existing(output_dir)
    result = BatchResult()
    total = len(config.source_files)
    index = 0
    _append_log(f"batch start: {total} files -> {output_dir}")

    for position, source in enumerate(config.source_files, start=1):
        if should_cancel():
            break
        try:
            digest = content_hash(source)
            source_key = str(source.resolve())
            reviewed = load_review(source)
            if config.require_review and reviewed is None:
                raise ValueError("原图已变化或缺少已保存的裁切框，请重新预览校正")
            revision = reviewed.revision if reviewed is not None else ""
            matching = [meta for meta in existing if meta["review_revision"] == revision]
            completed = {
                int(meta["review_crop_index"]) for meta in matching
                if meta["source"] == source_key and meta["digest"] == digest
                and meta["review_crop_index"].isdecimal()
            }
            complete = (completed.issuperset(range(len(reviewed.points))) if reviewed is not None
                        else bool(find_existing(matching, source_key, digest)))
            if complete:
                result.completed.append(source)
                report(position, total, "skipped")
                continue

            image, dpi, icc = _read_source(source)
            background = estimate_background(image)
            quads = (reviewed.quads() if reviewed is not None else resolve_occlusion(
                detect_quads(image, background, min_area_ratio=config.min_area_ratio)
            ))
            if not quads:
                if reviewed is None:
                    result.review.append(source)
                else:
                    result.completed.append(source)
                report(position, total, "review" if reviewed is None else "done")
                continue

            if any(quad.status != "ok" or quad.confidence < 0.6 for quad in quads):
                result.review.append(source)

            over_tilt = False
            for quad in quads:
                if abs(quad.tilt_deg) > config.max_tilt_deg:
                    quad.confidence = min(quad.confidence, 0.5)
                    over_tilt = True
            if over_tilt and source not in result.review:
                result.review.append(source)

            for crop_index, quad in enumerate(quads):
                if reviewed is not None and crop_index in completed:
                    continue
                crop = deskew_and_crop(
                    image,
                    quad,
                    background,
                    visible_mask=quad.visible_mask,
                    fill_mode=config.fill_mode,
                )
                if reviewed is not None:
                    rotation = reviewed.rotations[crop_index]
                    oriented = apply_state(crop, rotation)
                    orientation, extra_flags = OrientationState.MANUAL, []
                else:
                    oriented, rotation, orientation, extra_flags = _auto_orientation(crop)
                index += 1
                result.ok.append(
                    _save_photo(
                        output_dir,
                        index,
                        digest,
                        source_key,
                        oriented,
                        quad,
                        rotation,
                        orientation,
                        extra_flags,
                        dpi,
                        icc,
                        revision,
                        crop_index if reviewed is not None else None,
                    )
                )
            result.completed.append(source)
            report(position, total, "done")
        except Exception as exc:
            result.failed.append((source, str(exc)))
            report(position, total, "failed")
    return result
