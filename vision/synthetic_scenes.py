"""Deterministic synthetic two-view control-panel scenes for VisualGuard.

Every scene is rendered with OpenCV drawing and filtering primitives from a
seeded generator. The scenes are SYNTHETIC: they exercise the pipeline, its
baselines, and its failure handling, but they are not field data and cannot
establish field accuracy. Ground truth comes from the generator parameters,
never from the pipeline under test.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

import cv2
import numpy as np


WIDTH = 640
HEIGHT = 480
VIEWS = ("front", "side")
GENERATOR_VERSION = "visualguard-synthetic-panel-v1"

BGR_LAMP_RED = (40, 40, 240)
BGR_LAMP_GREEN = (70, 225, 60)
BGR_LAMP_OFF = (52, 52, 60)
BGR_UNLIT_RED = (30, 30, 105)
BGR_STICKER_RED = (35, 35, 225)


@dataclass(frozen=True)
class Scenario:
    """One labelled scenario family.

    ``lamp`` is the indicator state; ``lamp_views`` lists the views in which
    it is in frame. ``degradation`` is applied only to ``degraded_views``.
    ``expected`` is the primary correct decision and ``acceptable`` the set
    of decisions that are not wrong (for example STOP on a degraded alarm).
    """

    name: str
    lamp: str
    lamp_views: tuple[str, ...]
    distractors: tuple[str, ...]
    degradation: str
    degraded_views: tuple[str, ...]
    expected: str
    acceptable: frozenset[str]
    alarm_present: bool
    note: str


def _scenario(
    name: str,
    *,
    lamp: str,
    lamp_views: tuple[str, ...] = VIEWS,
    distractors: tuple[str, ...] = (),
    degradation: str = "none",
    degraded_views: tuple[str, ...] = (),
    expected: str,
    acceptable: tuple[str, ...] = (),
    note: str,
) -> Scenario:
    return Scenario(
        name=name,
        lamp=lamp,
        lamp_views=lamp_views,
        distractors=distractors,
        degradation=degradation,
        degraded_views=degraded_views,
        expected=expected,
        acceptable=frozenset((expected, *acceptable)),
        alarm_present=lamp == "red",
        note=note,
    )


SCENARIOS: tuple[Scenario, ...] = (
    _scenario(
        "normal_green_clear",
        lamp="green",
        expected="REVIEW",
        note="Lit green indicator, both views usable.",
    ),
    _scenario(
        "normal_lamp_off_clear",
        lamp="off",
        expected="REVIEW",
        note="Indicator off, both views usable.",
    ),
    _scenario(
        "alarm_red_both_views",
        lamp="red",
        expected="STOP",
        note="Lit red alarm indicator visible in both views.",
    ),
    _scenario(
        "alarm_red_side_only",
        lamp="red",
        lamp_views=("side",),
        expected="STOP",
        note="Alarm indicator is only in frame for the side view.",
    ),
    _scenario(
        "alarm_red_sensor_noise",
        lamp="red",
        degradation="mild_noise",
        degraded_views=VIEWS,
        expected="STOP",
        acceptable=("REQUEST_VIEW",),
        note="Alarm under moderate sensor noise.",
    ),
    _scenario(
        "alarm_red_jpeg",
        lamp="red",
        degradation="mild_jpeg",
        degraded_views=VIEWS,
        expected="STOP",
        acceptable=("REQUEST_VIEW",),
        note="Alarm after aggressive JPEG compression.",
    ),
    _scenario(
        "normal_green_with_glare",
        lamp="green",
        distractors=("glare",),
        expected="REVIEW",
        note="Specular glare: bright but unsaturated; brightness trap.",
    ),
    _scenario(
        "normal_green_with_red_sticker",
        lamp="green",
        distractors=("red_sticker",),
        expected="REVIEW",
        note="Rectangular red label: red but not lamp-shaped; colour trap.",
    ),
    _scenario(
        "normal_unlit_red_lamp",
        lamp="off",
        distractors=("unlit_red",),
        expected="REVIEW",
        note="Unlit red lens: red hue but not emitting.",
    ),
    _scenario(
        "normal_round_red_sticker",
        lamp="green",
        distractors=("round_red_sticker",),
        expected="REVIEW",
        note="Known-hard: round bright red non-emissive object.",
    ),
    _scenario(
        "normal_defocus",
        lamp="green",
        degradation="defocus",
        degraded_views=("front",),
        expected="REQUEST_VIEW",
        note="One view is badly out of focus.",
    ),
    _scenario(
        "normal_motion_blur",
        lamp="green",
        degradation="motion",
        degraded_views=("side",),
        expected="REQUEST_VIEW",
        note="One view has heavy motion blur.",
    ),
    _scenario(
        "normal_underexposed",
        lamp="off",
        degradation="dark",
        degraded_views=("front",),
        expected="REQUEST_VIEW",
        note="One view is severely underexposed.",
    ),
    _scenario(
        "normal_overexposed",
        lamp="green",
        degradation="overexposed",
        degraded_views=("side",),
        expected="REQUEST_VIEW",
        note="One view is washed out and clipped.",
    ),
    _scenario(
        "normal_lens_occluded",
        lamp="green",
        degradation="occluded",
        degraded_views=("front",),
        expected="REQUEST_VIEW",
        note="A dark object covers a large part of one lens.",
    ),
    _scenario(
        "alarm_lamp_occluded",
        lamp="red",
        lamp_views=("side",),
        degradation="occluded_lamp",
        degraded_views=("side",),
        expected="REQUEST_VIEW",
        acceptable=("STOP",),
        note="The only view of the alarm lamp is covered; must not REVIEW.",
    ),
    _scenario(
        "alarm_underexposed",
        lamp="red",
        lamp_views=("side",),
        degradation="dark",
        degraded_views=("side",),
        expected="REQUEST_VIEW",
        acceptable=("STOP",),
        note="The only view of the alarm lamp is severely underexposed.",
    ),
    _scenario(
        "alarm_defocus",
        lamp="red",
        degradation="defocus",
        degraded_views=VIEWS,
        expected="STOP",
        acceptable=("REQUEST_VIEW",),
        note="Alarm visible but both views out of focus.",
    ),
)
SCENARIOS_BY_NAME = {scenario.name: scenario for scenario in SCENARIOS}

# The held-out split widens the parameter ranges so evaluation is not run on
# exactly the distribution used to choose thresholds.
SPLIT_RANGES = {
    "dev": {
        "lamp_radius": (14, 24),
        "background_level": (80, 140),
        "texture_amplitude": (10.0, 18.0),
        "sensor_sigma": (1.5, 3.0),
    },
    "test": {
        "lamp_radius": (10, 28),
        "background_level": (60, 165),
        "texture_amplitude": (6.0, 24.0),
        "sensor_sigma": (1.0, 4.0),
    },
}
SPLIT_SEED_BASE = {"dev": 1_000_000, "test": 2_000_000}


@dataclass(frozen=True)
class RenderedScene:
    scenario: Scenario
    split: str
    index: int
    seed: int
    views: dict[str, np.ndarray]

    def digest(self) -> str:
        sha = hashlib.sha256()
        for name in VIEWS:
            sha.update(name.encode())
            sha.update(self.views[name].tobytes())
        return sha.hexdigest()


def _uniform(rng: np.random.Generator, bounds: tuple[float, float]) -> float:
    return float(rng.uniform(bounds[0], bounds[1]))


def _background(rng: np.random.Generator, ranges: dict) -> np.ndarray:
    level = _uniform(rng, ranges["background_level"])
    tint = rng.uniform(-12, 12, size=3)
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
    angle = rng.uniform(0, 2 * np.pi)
    gradient = (np.cos(angle) * x / WIDTH + np.sin(angle) * y / HEIGHT) * rng.uniform(
        -30, 30
    )
    coarse = rng.normal(0, 1, size=(HEIGHT // 32, WIDTH // 32)).astype(np.float32)
    texture = cv2.resize(coarse, (WIDTH, HEIGHT), interpolation=cv2.INTER_CUBIC)
    texture *= _uniform(rng, ranges["texture_amplitude"])
    base = level + gradient + texture
    image = np.stack([base + tint[0], base + tint[1], base + tint[2]], axis=-1)
    return np.clip(image, 0, 255).astype(np.uint8)


def _panel(
    rng: np.random.Generator, image: np.ndarray
) -> tuple[tuple[int, int, int, int], list[tuple[int, int, int, int]]]:
    """Draw an equipment panel; return its box and reserved boxes."""
    width = int(rng.integers(300, 420))
    height = int(rng.integers(200, 290))
    left = int(rng.integers(20, WIDTH - width - 20))
    top = int(rng.integers(20, HEIGHT - height - 20))
    shade = int(rng.integers(35, 75))
    cv2.rectangle(
        image, (left, top), (left + width, top + height), (shade,) * 3, cv2.FILLED
    )
    cv2.rectangle(
        image,
        (left, top),
        (left + width, top + height),
        (shade + 60,) * 3,
        3,
        cv2.LINE_AA,
    )
    for row in range(2):
        cv2.putText(
            image,
            f"PUMP {chr(65 + int(rng.integers(0, 6)))}{row + 1}",
            (left + 14, top + 30 + row * 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (200, 200, 200),
            1,
            cv2.LINE_AA,
        )
    for _ in range(int(rng.integers(2, 5))):
        cx = int(rng.integers(left + 40, left + width - 40))
        cy = int(rng.integers(top + height // 2, top + height - 30))
        cv2.circle(image, (cx, cy), int(rng.integers(10, 18)), (140, 140, 140), -1)
        cv2.circle(image, (cx, cy), 4, (30, 30, 30), -1)
    for _ in range(int(rng.integers(2, 4))):
        x0 = int(rng.integers(0, WIDTH))
        cv2.line(
            image,
            (x0, HEIGHT - 1),
            (int(rng.integers(left, left + width)), top + height),
            (20, 20, 20),
            int(rng.integers(3, 7)),
            cv2.LINE_AA,
        )
    return (left, top, width, height), [(left, top, 180, 70)]


def _overlaps(box, boxes, margin: int = 12) -> bool:
    x, y, w, h = box
    for ox, oy, ow, oh in boxes:
        if (
            x < ox + ow + margin
            and ox < x + w + margin
            and y < oy + oh + margin
            and oy < y + h + margin
        ):
            return True
    return False


def _place(
    rng: np.random.Generator,
    size: tuple[int, int],
    region: tuple[int, int, int, int],
    reserved: list[tuple[int, int, int, int]],
) -> tuple[int, int, int, int]:
    width, height = size
    rx, ry, rw, rh = region
    for _ in range(200):
        x = int(rng.integers(rx, max(rx + 1, rx + rw - width)))
        y = int(rng.integers(ry, max(ry + 1, ry + rh - height)))
        box = (x, y, width, height)
        if not _overlaps(box, reserved):
            reserved.append(box)
            return box
    raise RuntimeError("could not place object without overlap")


def _draw_lamp(
    rng: np.random.Generator,
    image: np.ndarray,
    center: tuple[int, int],
    radius: int,
    state: str,
) -> None:
    cv2.circle(image, center, radius + 6, (25, 25, 25), -1, cv2.LINE_AA)
    cv2.circle(image, center, radius + 6, (110, 110, 110), 2, cv2.LINE_AA)
    color = {
        "red": BGR_LAMP_RED,
        "green": BGR_LAMP_GREEN,
        "off": BGR_LAMP_OFF,
        "unlit_red": BGR_UNLIT_RED,
    }[state]
    if state in {"red", "green"}:
        glow = np.zeros_like(image)
        cv2.circle(glow, center, int(radius * 1.25), color, -1, cv2.LINE_AA)
        glow = cv2.GaussianBlur(glow, (0, 0), radius * 0.45)
        cv2.add(image, (glow * 0.6).astype(np.uint8), dst=image)
    cv2.circle(image, center, radius, color, -1, cv2.LINE_AA)
    if state in {"red", "green"}:
        highlight = (
            center[0] - radius // 3,
            center[1] - radius // 3,
        )
        cv2.circle(
            image, highlight, max(2, radius // 4), (235, 235, 245), -1, cv2.LINE_AA
        )


def _draw_distractor(
    rng: np.random.Generator,
    image: np.ndarray,
    kind: str,
    reserved: list[tuple[int, int, int, int]],
) -> None:
    full = (10, 10, WIDTH - 20, HEIGHT - 20)
    if kind == "glare":
        axes = (int(rng.integers(18, 40)), int(rng.integers(12, 28)))
        x, y, _, _ = _place(rng, (axes[0] * 2, axes[1] * 2), full, reserved)
        layer = np.zeros_like(image)
        cv2.ellipse(
            layer,
            (x + axes[0], y + axes[1]),
            axes,
            float(rng.uniform(0, 180)),
            0,
            360,
            (255, 255, 255),
            -1,
            cv2.LINE_AA,
        )
        layer = cv2.GaussianBlur(layer, (0, 0), 4)
        cv2.max(image, layer, dst=image)
    elif kind == "red_sticker":
        size = (int(rng.integers(28, 70)), int(rng.integers(18, 50)))
        x, y, w, h = _place(rng, size, full, reserved)
        cv2.rectangle(image, (x, y), (x + w, y + h), BGR_STICKER_RED, -1)
        cv2.putText(
            image,
            "HOT",
            (x + 3, y + h - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (240, 240, 240),
            1,
            cv2.LINE_AA,
        )
    elif kind == "round_red_sticker":
        radius = int(rng.integers(14, 24))
        x, y, _, _ = _place(rng, (radius * 2, radius * 2), full, reserved)
        cv2.circle(
            image, (x + radius, y + radius), radius, BGR_STICKER_RED, -1, cv2.LINE_AA
        )
    elif kind == "unlit_red":
        radius = int(rng.integers(14, 24))
        x, y, _, _ = _place(rng, (radius * 2 + 14, radius * 2 + 14), full, reserved)
        _draw_lamp(rng, image, (x + radius + 7, y + radius + 7), radius, "unlit_red")
    else:
        raise ValueError(f"unknown distractor {kind!r}")


def _motion_kernel(rng: np.random.Generator) -> np.ndarray:
    length = int(rng.integers(25, 41))
    kernel = np.zeros((length, length), dtype=np.float32)
    kernel[length // 2, :] = 1.0
    rotation = cv2.getRotationMatrix2D(
        (length / 2 - 0.5, length / 2 - 0.5), float(rng.uniform(0, 180)), 1.0
    )
    kernel = cv2.warpAffine(kernel, rotation, (length, length))
    return kernel / max(float(kernel.sum()), 1e-6)


def _degrade(
    rng: np.random.Generator,
    image: np.ndarray,
    kind: str,
    lamp_box: tuple[int, int, int, int] | None,
) -> np.ndarray:
    if kind == "none":
        return image
    if kind == "mild_noise":
        noise = rng.normal(0, rng.uniform(5, 10), size=image.shape)
        return np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    if kind == "mild_jpeg":
        quality = int(rng.integers(20, 45))
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise RuntimeError("JPEG encode failed")
        return cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if kind == "defocus":
        return cv2.GaussianBlur(image, (0, 0), rng.uniform(5.0, 9.0))
    if kind == "motion":
        return cv2.filter2D(image, -1, _motion_kernel(rng))
    if kind == "dark":
        return cv2.convertScaleAbs(image, alpha=rng.uniform(0.10, 0.20), beta=0)
    if kind == "overexposed":
        return cv2.convertScaleAbs(
            image, alpha=rng.uniform(2.6, 3.6), beta=rng.uniform(30, 60)
        )
    if kind in {"occluded", "occluded_lamp"}:
        occluded = image.copy()
        fraction = rng.uniform(0.38, 0.6)
        if kind == "occluded_lamp" and lamp_box is not None:
            lx, ly, lw, lh = lamp_box
            cx, cy = lx + lw // 2, ly + lh // 2
        else:
            cx = int(rng.integers(WIDTH // 4, 3 * WIDTH // 4))
            cy = int(rng.integers(HEIGHT // 4, 3 * HEIGHT // 4))
        area = fraction * WIDTH * HEIGHT
        ratio = rng.uniform(0.8, 1.4)
        ax = int(np.sqrt(area * ratio / np.pi))
        ay = int(np.sqrt(area / ratio / np.pi))
        shade = int(rng.integers(8, 26))
        cv2.ellipse(
            occluded,
            (cx, cy),
            (ax, ay),
            float(rng.uniform(0, 180)),
            0,
            360,
            (shade, shade, shade + 4),
            -1,
            cv2.LINE_AA,
        )
        return occluded
    raise ValueError(f"unknown degradation {kind!r}")


def render_view(
    scenario: Scenario,
    view: str,
    rng: np.random.Generator,
    ranges: dict,
) -> np.ndarray:
    image = _background(rng, ranges)
    panel, reserved = _panel(rng, image)
    lamp_box = None
    if view in scenario.lamp_views:
        radius = int(rng.integers(*ranges["lamp_radius"]))
        lamp_box = _place(rng, (radius * 2 + 14, radius * 2 + 14), panel, reserved)
        x, y, _, _ = lamp_box
        _draw_lamp(rng, image, (x + radius + 7, y + radius + 7), radius, scenario.lamp)
    for kind in scenario.distractors:
        _draw_distractor(rng, image, kind, reserved)
    sensor = rng.normal(0, _uniform(rng, ranges["sensor_sigma"]), size=image.shape)
    image = np.clip(image.astype(np.float32) + sensor, 0, 255).astype(np.uint8)
    if view in scenario.degraded_views:
        image = _degrade(rng, image, scenario.degradation, lamp_box)
    return np.ascontiguousarray(image)


def render_scene(scenario: Scenario, *, split: str, index: int) -> RenderedScene:
    if split not in SPLIT_RANGES:
        raise ValueError(f"unknown split {split!r}")
    scenario_offset = SCENARIOS.index(scenario) * 10_000
    seed = SPLIT_SEED_BASE[split] + scenario_offset + index
    rng = np.random.default_rng(seed)
    views = {
        view: render_view(scenario, view, rng, SPLIT_RANGES[split]) for view in VIEWS
    }
    return RenderedScene(scenario, split, index, seed, views)


def generate_split(split: str, per_scenario: int) -> list[RenderedScene]:
    return [
        render_scene(scenario, split=split, index=index)
        for scenario in SCENARIOS
        for index in range(per_scenario)
    ]
