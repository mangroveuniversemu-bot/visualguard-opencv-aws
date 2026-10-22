"""OpenCV 5 two-view scene analysis for VisualGuard.

The pipeline measures image quality from pixels (sharpness, exposure, lens
occlusion), detects lit red alarm indicators with colour segmentation,
morphology and contour-shape tests, fuses the two views, and binds every
capture to the existing durable replay ledger. It returns a bounded decision
(``REVIEW``, ``REQUEST_VIEW`` or ``STOP``) that ``vision.follow_up`` turns into
a planned, never executed, next step.

It is not a camera driver, safety controller, or field-validated detector.
Thresholds were chosen on the synthetic ``dev`` split only.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import sqlite3
import time
from typing import Mapping

import cv2
import numpy as np

from vision.opencv5_inspection import (
    MAX_VIEW_CAPTURE_SKEW_SECONDS,
    OPENCV_VERSION,
    PACKAGE_VERSION,
    VIEW_SOURCE_IDS,
    CaptureReplayLedger,
    CaptureReplayLedgerIntegrityError,
    CaptureReplayLedgerSchemaError,
    _package_version,
    _valid_capture_time,
    runtime_matches_contract,
)


PIPELINE_VERSION = "opencv5-scene-v1"
ENVELOPE_SCHEMA_VERSION = 1
FRAME_HEIGHT = 480
FRAME_WIDTH = 640
MAX_FRAME_AGE_SECONDS = 5.0

CONFIG: dict[str, float | int] = {
    # Quality gates.
    "min_sharpness": 60.0,
    "min_mean_gray": 35.0,
    "max_mean_gray": 200.0,
    "max_dark_clipped_fraction": 0.5,
    "max_bright_clipped_fraction": 0.25,
    "occlusion_cell": 40,
    "occlusion_max_cell_std": 6.0,
    "occlusion_max_cell_mean": 30.0,
    "min_visible_fraction": 0.80,
    # Lit red indicator detection.
    "red_min_saturation": 100,
    "red_min_value": 150,
    "red_hue_low_max": 10,
    "red_hue_high_min": 170,
    "lamp_min_area": 150,
    "lamp_max_area": 15360,
    "lamp_min_fill": 0.75,
    "lamp_min_aspect": 0.70,
    "lamp_min_mean_value": 170,
}

QUALITY_REASON_ORDER = (
    "UNDEREXPOSED_VIEW",
    "OVEREXPOSED_VIEW",
    "OCCLUDED_VIEW",
    "BLURRED_VIEW",
)


def _config_digest(config: Mapping[str, float | int]) -> str:
    canonical = json.dumps(dict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


CONFIG_SHA256 = _config_digest(CONFIG)


@dataclass(frozen=True)
class SceneView:
    pixels: np.ndarray
    source_id: str | None = None
    capture_id: str | None = None
    captured_at: float | None = None


def validate_frame(pixels: object) -> bool:
    return (
        isinstance(pixels, np.ndarray)
        and pixels.dtype == np.uint8
        and pixels.shape == (FRAME_HEIGHT, FRAME_WIDTH, 3)
    )


def measure_quality(
    pixels: np.ndarray, config: Mapping[str, float | int] = CONFIG
) -> dict[str, object]:
    """Measure sharpness, exposure and dark-occlusion directly from pixels."""
    gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
    smoothed = cv2.GaussianBlur(gray, (3, 3), 0)
    gx = cv2.Sobel(smoothed, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(smoothed, cv2.CV_32F, 0, 1, ksize=3)
    # Directional 99th percentile so motion blur along one axis is not masked
    # by sharp edges along the other.
    sharpness = float(min(np.percentile(np.abs(gx), 99), np.percentile(np.abs(gy), 99)))
    laplacian_variance = float(cv2.Laplacian(smoothed, cv2.CV_64F).var())

    histogram = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
    total = float(gray.size)
    mean_gray = float(cv2.mean(gray)[0])
    dark_clipped = float(histogram[:6].sum() / total)
    bright_clipped = float(histogram[250:].sum() / total)

    cell = int(config["occlusion_cell"])
    rows, cols = FRAME_HEIGHT // cell, FRAME_WIDTH // cell
    cells = gray[: rows * cell, : cols * cell].reshape(rows, cell, cols, cell)
    cell_mean = cells.mean(axis=(1, 3))
    cell_std = cells.std(axis=(1, 3))
    blocked = (cell_std <= float(config["occlusion_max_cell_std"])) & (
        cell_mean <= float(config["occlusion_max_cell_mean"])
    )
    visible_fraction = float(1.0 - blocked.mean())

    failures = []
    if mean_gray < float(config["min_mean_gray"]) or dark_clipped > float(
        config["max_dark_clipped_fraction"]
    ):
        failures.append("UNDEREXPOSED_VIEW")
    if mean_gray > float(config["max_mean_gray"]) or bright_clipped > float(
        config["max_bright_clipped_fraction"]
    ):
        failures.append("OVEREXPOSED_VIEW")
    if visible_fraction < float(config["min_visible_fraction"]):
        failures.append("OCCLUDED_VIEW")
    if sharpness < float(config["min_sharpness"]):
        failures.append("BLURRED_VIEW")
    return {
        "sharpness": round(sharpness, 3),
        "laplacian_variance": round(laplacian_variance, 3),
        "mean_gray": round(mean_gray, 3),
        "dark_clipped_fraction": round(dark_clipped, 5),
        "bright_clipped_fraction": round(bright_clipped, 5),
        "visible_fraction": round(visible_fraction, 5),
        "failures": failures,
        "usable": not failures,
    }


def red_mask(
    pixels: np.ndarray, config: Mapping[str, float | int] = CONFIG
) -> np.ndarray:
    """Return the saturated, bright red mask before shape filtering."""
    hsv = cv2.cvtColor(pixels, cv2.COLOR_BGR2HSV)
    s_min = int(config["red_min_saturation"])
    v_min = int(config["red_min_value"])
    low = cv2.inRange(
        hsv, (0, s_min, v_min), (int(config["red_hue_low_max"]), 255, 255)
    )
    high = cv2.inRange(
        hsv, (int(config["red_hue_high_min"]), s_min, v_min), (179, 255, 255)
    )
    return cv2.bitwise_or(low, high)


def detect_red_indicators(
    pixels: np.ndarray, config: Mapping[str, float | int] = CONFIG
) -> list[dict[str, object]]:
    """Find lit, lamp-shaped red regions with morphology and contour tests."""
    mask = red_mask(pixels, config)
    kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    kernel_large = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_small)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_large)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    value = cv2.cvtColor(pixels, cv2.COLOR_BGR2HSV)[:, :, 2]
    detections = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if not float(config["lamp_min_area"]) <= area <= float(config["lamp_max_area"]):
            continue
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        fill = area / (math.pi * radius * radius) if radius > 0 else 0.0
        x, y, w, h = cv2.boundingRect(contour)
        aspect = min(w, h) / max(w, h)
        region = np.zeros(mask.shape, dtype=np.uint8)
        cv2.drawContours(region, [contour], -1, 255, cv2.FILLED)
        mean_value = float(cv2.mean(value, mask=region)[0])
        accepted = (
            fill >= float(config["lamp_min_fill"])
            and aspect >= float(config["lamp_min_aspect"])
            and mean_value >= float(config["lamp_min_mean_value"])
        )
        if accepted:
            detections.append(
                {
                    "kind": "LIT_RED_INDICATOR",
                    "bbox": [int(x), int(y), int(w), int(h)],
                    "center": [round(float(cx), 1), round(float(cy), 1)],
                    "area": round(area, 1),
                    "fill": round(fill, 4),
                    "aspect": round(aspect, 4),
                    "mean_value": round(mean_value, 2),
                }
            )
    detections.sort(key=lambda item: (-item["area"], item["bbox"]))
    return detections


def analyze_view(
    pixels: np.ndarray,
    config: Mapping[str, float | int] = CONFIG,
    *,
    use_quality_gate: bool = True,
) -> dict[str, object]:
    started = time.perf_counter()
    quality = measure_quality(pixels, config)
    if not use_quality_gate:
        quality = {**quality, "failures": [], "usable": True}
    detections = detect_red_indicators(pixels, config)
    return {
        "quality": quality,
        "detections": detections,
        "alarm": bool(detections),
        "frame_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
        "analysis_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }


def fuse(per_view: Mapping[str, Mapping[str, object]]) -> dict[str, str]:
    """Fuse view results. A visible alarm wins; then unusable views block."""
    alarm_views = sorted(name for name, result in per_view.items() if result["alarm"])
    if alarm_views:
        return {"decision": "STOP", "reason": "ALARM"}
    failures = {
        failure
        for result in per_view.values()
        for failure in result["quality"]["failures"]
    }
    for reason in QUALITY_REASON_ORDER:
        if reason in failures:
            return {"decision": "REQUEST_VIEW", "reason": reason}
    return {"decision": "REVIEW", "reason": "HUMAN_REVIEW"}


def capture_envelope_sha256(
    logical_view: str,
    view: SceneView,
    captured_at: float,
    *,
    config_sha256: str,
) -> str:
    envelope = {
        "capture_id": view.capture_id,
        "captured_at": float(captured_at),
        "config_sha256": config_sha256,
        "logical_view": logical_view,
        "opencv_version": OPENCV_VERSION,
        "package_version": PACKAGE_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "pixel_dtype": str(view.pixels.dtype),
        "pixel_shape": list(view.pixels.shape),
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "source_id": view.source_id,
        "view_captured_at": float(view.captured_at),
    }
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical + b"\0" + view.pixels.tobytes()).hexdigest()


def runtime_evidence() -> dict[str, str]:
    return {
        "opencv_version": cv2.__version__,
        "package": "opencv-python-headless",
        "package_version": _package_version(),
        "pipeline_version": PIPELINE_VERSION,
        "config_sha256": CONFIG_SHA256,
        "algorithm": (
            "cvtColor+GaussianBlur+Sobel+Laplacian+calcHist (quality); "
            "cvtColor(HSV)+inRange+morphologyEx+findContours+"
            "minEnclosingCircle+boundingRect+drawContours+mean (indicator)"
        ),
    }


def _stop(reason: str) -> dict[str, object]:
    return {"decision": "STOP", "reason": reason, "physical_action": "NONE"}


def _request(reason: str) -> dict[str, object]:
    return {"decision": "REQUEST_VIEW", "reason": reason, "physical_action": "NONE"}


REPLAY_STOP_REASONS = {
    "MISMATCH": "CAPTURE_ID_REPLAY_MISMATCH",
    "FULL": "CAPTURE_REPLAY_LEDGER_FULL",
    "BACKLOG_LIMIT": "CAPTURE_REPLAY_BACKLOG_LIMIT",
    "BATCH_LIMIT": "CAPTURE_REPLAY_BATCH_LIMIT",
}


def analyze_scene(
    views: object,
    *,
    captured_at: float,
    now: float,
    replay_ledger: CaptureReplayLedger | None,
    config: Mapping[str, float | int] = CONFIG,
) -> dict[str, object]:
    """Analyse a bound front/side pair and fail closed on unusable evidence."""
    if not runtime_matches_contract():
        return _stop("DEPENDENCY_VERSION_CHANGED")
    config_sha256 = _config_digest(config)
    if config_sha256 != CONFIG_SHA256:
        return _stop("PIPELINE_CONFIG_CHANGED")
    if not _valid_capture_time(captured_at) or not _valid_capture_time(now):
        return _stop("INVALID_CAPTURE_TIME")
    if now < captured_at or now - captured_at > MAX_FRAME_AGE_SECONDS:
        return _stop("STALE_OR_FUTURE_FRAME")
    if not isinstance(views, dict):
        return _stop("INVALID_VIEW_CONTAINER")
    if set(views) != set(VIEW_SOURCE_IDS):
        return _request("INCOMPLETE_COVERAGE")
    if any(not isinstance(view, SceneView) for view in views.values()):
        return _stop("INVALID_VIEW")
    times = {name: view.captured_at for name, view in views.items()}
    if any(not _valid_capture_time(value) for value in times.values()):
        return _stop("INVALID_VIEW_CAPTURE_TIME")
    if any(
        now < value or now - value > MAX_FRAME_AGE_SECONDS for value in times.values()
    ):
        return _stop("STALE_OR_FUTURE_VIEW")
    if max(times.values()) - min(times.values()) > MAX_VIEW_CAPTURE_SKEW_SECONDS:
        return _request("VIEW_CAPTURE_TIME_SKEW")
    if any(views[name].source_id != source for name, source in VIEW_SOURCE_IDS.items()):
        return _request("VIEW_SOURCE_MISMATCH")
    capture_ids = [view.capture_id for view in views.values()]
    if any(not isinstance(value, str) or not value.strip() for value in capture_ids):
        return _request("INVALID_CAPTURE_ID")
    if len(set(capture_ids)) != len(capture_ids):
        return _request("DUPLICATED_CAPTURE_ID")
    if any(not validate_frame(view.pixels) for view in views.values()):
        return _stop("INVALID_FRAME")
    if np.shares_memory(views["front"].pixels, views["side"].pixels) or np.array_equal(
        views["front"].pixels, views["side"].pixels
    ):
        return _request("DUPLICATED_VIEW_BUFFER")
    if replay_ledger is None:
        return _stop("REPLAY_LEDGER_REQUIRED")
    if not isinstance(replay_ledger, CaptureReplayLedger):
        return _stop("INVALID_REPLAY_LEDGER")

    per_view = {}
    envelopes = {}
    for name in sorted(views):
        view = views[name]
        result = analyze_view(view.pixels, config)
        envelope = capture_envelope_sha256(
            name, view, captured_at, config_sha256=config_sha256
        )
        result["capture_envelope_sha256"] = envelope
        result["capture_id"] = view.capture_id
        result["source_id"] = view.source_id
        per_view[name] = result
        envelopes[view.capture_id] = envelope

    try:
        replay_status, replay_entries = replay_ledger.check_and_record(envelopes)
    except sqlite3.Error:
        return _stop("REPLAY_LEDGER_ERROR")
    if replay_status in REPLAY_STOP_REASONS:
        return _stop(REPLAY_STOP_REASONS[replay_status])
    if replay_status not in {"RECORDED", "REPLAYED"}:
        return _stop("CAPTURE_REPLAY_INTEGRITY_ERROR")
    try:
        rowset = replay_ledger.rowset_identity()
    except (CaptureReplayLedgerIntegrityError, CaptureReplayLedgerSchemaError):
        return _stop("CAPTURE_REPLAY_ROWSET_MISMATCH")

    fused = fuse(per_view)
    return {
        **fused,
        "views": per_view,
        "evidence": {
            **runtime_evidence(),
            "captured_at": float(captured_at),
            "view_captured_at": {name: float(value) for name, value in times.items()},
            "capture_replay_status": replay_status,
            "capture_replay_ledger_entries": replay_entries,
            "capture_replay_rowset_sha256": rowset["sha256"],
            "input_mode": "CALLER_SUPPLIED_FRAMES",
        },
        "physical_action": "NONE",
    }


def annotate(pixels: np.ndarray, view_result: Mapping[str, object]) -> np.ndarray:
    """Draw detections and quality metrics for human review."""
    canvas = pixels.copy()
    for detection in view_result["detections"]:
        x, y, w, h = detection["bbox"]
        cv2.rectangle(canvas, (x - 4, y - 4), (x + w + 4, y + h + 4), (0, 0, 255), 2)
        cv2.putText(
            canvas,
            "LIT RED",
            (x, max(12, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )
    quality = view_result["quality"]
    banner = (
        f"sharp {quality['sharpness']:.0f}  mean {quality['mean_gray']:.0f}  "
        f"visible {quality['visible_fraction']:.2f}"
    )
    status = ",".join(quality["failures"]) or "USABLE"
    cv2.rectangle(canvas, (0, 0), (FRAME_WIDTH, 40), (0, 0, 0), cv2.FILLED)
    cv2.putText(
        canvas, banner, (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1
    )
    cv2.putText(
        canvas,
        status,
        (8, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (0, 200, 255) if quality["failures"] else (0, 220, 0),
        1,
    )
    return canvas


def baseline_legacy_brightness(pixels: np.ndarray) -> bool:
    """Prior pipeline ported to full frames: grey threshold plus pixel count."""
    gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
    _, bright = cv2.threshold(gray, 199, 255, cv2.THRESH_BINARY)
    return int(cv2.countNonZero(bright)) >= int(CONFIG["lamp_min_area"])


def baseline_naive_red(pixels: np.ndarray) -> bool:
    """Colour-only ablation: red pixel count, no morphology or shape tests."""
    return int(cv2.countNonZero(red_mask(pixels))) >= int(CONFIG["lamp_min_area"])
