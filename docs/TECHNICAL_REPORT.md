# VisualGuard technical report

**Competition:** OpenCV AI Competition 2026, powered by AWS.
**Evidence classes used below:** `SYNTHETIC_SCENE_EVALUATION`,
`LOCAL_CONTAINER`, `HOSTED_CI`, `LAMBDA_EMULATOR`. No field data, camera or
AWS execution is reported here; AWS is `NOT_RUN` until the runbook in
[`AWS_DEPLOYMENT_RUNBOOK.md`](AWS_DEPLOYMENT_RUNBOOK.md) is executed.

## 1. Problem

Automation next to equipment panels should not continue when an alarm
indicator is lit, and it should not trust a camera view that is blurred,
badly exposed or blocked. VisualGuard inspects a bound pair of views (front
and side) and returns one of three bounded decisions. Each decision maps to a
planned next step that a human or a downstream workflow can act on:

| Decision | Planned follow-up | Meaning |
|---|---|---|
| `STOP` | `HOLD_AUTOMATION` | lit red indicator seen, or evidence integrity failed |
| `REQUEST_VIEW` | `REQUEST_NEW_CAPTURE` | a view is unusable or provenance is incomplete |
| `REVIEW` | `QUEUE_HUMAN_REVIEW` | usable views, no alarm; a person confirms |

The system plans actions but never executes them (`action_executed=false`,
`physical_action=NONE`).

## 2. Method (OpenCV 5.0.0, `opencv-python-headless==5.0.0.93`)

Per 640×480 BGR view (`vision/scene_analysis.py`):

1. **Sharpness:** `cvtColor` to grey, `GaussianBlur` 3×3, `Sobel` x and y.
   The score is the minimum of the per-axis 99th-percentile gradient, so
   motion blur along one axis is not hidden by sharp edges along the other.
   `Laplacian` variance is reported as a secondary metric.
2. **Exposure:** `calcHist` gives mean grey and dark/bright clipped
   fractions.
3. **Occlusion:** the grey frame is split into 40×40 cells. Dark cells with
   low texture count as blocked; visible fraction is measured from pixels,
   not supplied by the caller.
4. **Lit red indicator:** HSV `cvtColor`, two-band `inRange` for red hue,
   `morphologyEx` open then close, `findContours`, then shape and emission
   tests: area, fill ratio against `minEnclosingCircle`, `boundingRect`
   aspect, and mean V inside the `drawContours` mask.
5. **Fusion:** any detection gives `STOP`; otherwise any failed quality gate
   gives `REQUEST_VIEW` with the first reason in the order underexposed,
   overexposed, occluded, blurred; otherwise `REVIEW`.
6. **Provenance:** freshness (5 s), view skew (0.25 s), expected source IDs,
   unique capture IDs, distinct buffers, and the durable capture replay
   ledger. A reused capture ID with different bytes gives `STOP`.

Thresholds live in one `CONFIG` dict whose SHA-256 is part of every capture
envelope. A changed config gives `STOP / PIPELINE_CONFIG_CHANGED`.

## 3. Evaluation (`evidence/CHECK137_OPENCV5_SCENE_PIPELINE_EVAL.json`)

**Data.** `vision/synthetic_scenes.py` renders 18 labelled scenario
families with OpenCV drawing and filtering: clear, alarm in one or both
views, noise, JPEG, glare, rectangular and round red stickers, an unlit red
lens, defocus, motion blur, under- and overexposure, lens occlusion, an
occluded alarm, an underexposed alarm, and a defocused alarm. Ground truth
comes from generator parameters. Thresholds were chosen on the `dev` split
(180 pairs). The `test` split (540 pairs) uses disjoint seeds and wider lamp
size, background, texture and noise ranges.

**Methods** on identical pairs:

- `pipeline`: the full method above;
- `ablation_no_quality_gate`: the same detector without quality gates;
- `baseline_naive_red`: red-pixel count only;
- `baseline_legacy_brightness`: the repository's previous grey-threshold
  pixel count, ported to full frames.

**Held-out test split, 540 pairs (source commit `b3049dd`):**

| Method | Exact | Unsafe misses (alarm → REVIEW) | False stops | REQUEST_VIEW recall on degraded | Median ms / pair |
|---|---|---|---|---|---|
| pipeline | **94.26%** | **0 / 210** | 30 / 330 | **99.52%** | 41.4 |
| ablation, no quality gate | 55.56% | 60 / 210 | 30 / 330 | 0% | 41.0 |
| baseline, naive red count | 50.00% | 60 / 210 | 61 / 330 | 0% | 2.9 |
| baseline, legacy brightness | 31.85% | 76 / 210 | 244 / 330 | 0% | 0.2 |

The dev split gives the same picture: pipeline 94.44% exact with 0 unsafe
misses.

**What the ablation shows.** Without quality gates, the 60 test pairs where
the only view of a lit alarm is occluded or underexposed become `REVIEW`,
which is an unsafe miss. With gates they become `REQUEST_VIEW`. Shape tests
remove the rectangular-sticker and unlit-lens false stops that the
colour-only baseline produces.

## 4. Failure cases (kept visible on purpose)

| Case | Result | Why | Status |
|---|---|---|---|
| Round bright red non-emissive sticker | **30/30 false `STOP`** | colour + shape cannot tell a red disc from a lit lamp; mean V differs by only ~12 levels on this generator, so a V threshold would overfit | open; fails toward safety |
| Motion blur, test seed `2110022` | 1/30 `REVIEW` instead of `REQUEST_VIEW` | directional p99 sharpness 80 ≥ 60 while Laplacian variance was 3.8 | open; a combined gate is a candidate, but tuning it on the test split would contaminate the held-out result |

Outside the known-hard sticker family the pipeline gets 509/510 test pairs
exactly right. That number holds on this generator only.

## 5. Serving and latency

- `service/app.py` exposes `/healthz`, `/v1/samples`, `/v1/inspect` and a
  demo page. Inputs are decoded with `cv2.imdecode` and resized to 640×480
  with `INTER_AREA`. The original shape is recorded.
- Local read-only container, 9/9 smoke checks
  (`evidence/CHECK138_LOCAL_CONTAINER_ENDPOINT_SMOKE.json`): about 60–140 ms
  server analysis per pair on the session host.
- Hosted CI run `39808657344` (GitHub `ubuntu-latest`) built the HTTP and
  Lambda images, ran a read-only container and passed the same 9 smoke
  checks with about 35–60 ms per request.
- Lambda image through the AWS Runtime Interface Emulator: `REPORT
  Duration` about 89 ms for an inspect call. This is local emulation, not
  AWS.

## 6. Limitations and responsible use

- All evaluation frames are synthetic. The same author wrote generator and
  detector, so held-out seeds reduce the coupling but do not remove it. No
  claim of field accuracy is made.
- Red-indicator semantics are an assumption. Real panels use many colours,
  blink patterns and lens types; deployment would need site-specific
  calibration data and a review of false-stop cost.
- The system only plans actions. Any real actuation would need its own
  safety case, interlocks and human authorization, none of which exist here.
- Uploaded images are processed in memory. Only digests enter the replay
  ledger, and logs contain no image data. On Lambda, `/tmp` is ephemeral and
  per instance.
- Replay protection is per instance, not global.

## 7. Reproduce

```bash
python -m pip install -r requirements-vision.txt pytest==9.0.2 ruff==0.14.13
python -m pytest -q
python ops/evaluate_scene_pipeline.py --output /tmp/eval.json
python -m service.app --port 8080 &   # then open http://127.0.0.1:8080/
python ops/smoke_test_endpoint.py --base-url http://127.0.0.1:8080
docker build --target http -t visualguard:http .
docker run --read-only --tmpfs /tmp -p 8080:8080 visualguard:http
```
