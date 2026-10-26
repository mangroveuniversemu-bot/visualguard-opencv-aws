# VisualGuard Technical Report

**Snapshot:** 2026-10-27. This report separates verified synthetic/local/AWS evidence from field claims. It is not an independent product or safety review.

## Current status

VisualGuard is an OpenCV 5 two-view inspection prototype with a shared Python core, a local HTTP viewer, and a private AWS Lambda container deployed from ECR. The AWS Function URL requires AWS_IAM. The system returns REVIEW, STOP, or REQUEST_VIEW and a planned follow-up; it does not execute equipment commands. No actuator is connected.

The public 2:20 owner-review film is at https://youtu.be/AEDHXknTBy8. The Devpost submission is still a draft. The film is not byte-bound to the older CHECK146 video contract and has no independent reviewer receipt. CHECK146 verifies six bound evidence files, four saved AWS cases, and eight local negative controls; it does not verify this newer film or field accuracy.

## Problem and intended use

A red indicator in one equipment-panel view can be a real alarm, a misleading red object, or an image that cannot be trusted. VisualGuard compares front and side views, checks image quality, and offers a bounded next step for a human operator. It is a research prototype, not a production safety controller.

| Decision | Planned follow-up | Meaning |
| --- | --- | --- |
| STOP | HOLD_AUTOMATION | Red-indicator evidence or evidence-integrity failure; no physical stop is issued. |
| REQUEST_VIEW | REQUEST_NEW_CAPTURE | A view is unusable or provenance is incomplete. |
| REVIEW | QUEUE_HUMAN_REVIEW | Usable views with no detected alarm; a person confirms. |

All returned plans set action_executed=false; physical_action=NONE.

## Architecture and OpenCV method

The same Python/OpenCV 5 inspection core serves the local HTTP application and the containerized Lambda image. GitHub OIDC provides short-lived deployment credentials. ECR stores the Lambda image; CloudWatch records executions. AWS and local replay ledgers are per environment.

For each 640x480 BGR view, vision/scene_analysis.py measures directional sharpness (Sobel with Laplacian as a secondary metric), exposure (histogram and clipping), and dark low-texture occlusion. It detects red regions with two HSV bands, morphology, contour geometry, and brightness checks. A fusion step chooses a decision from both views and checks freshness, source IDs, capture IDs, buffer separation, and the durable replay ledger. Pipeline configuration is hashed into each capture envelope.

## Synthetic evaluation and failures

The held-out evaluation uses 540 procedurally generated pairs with disjoint test seeds. It measures behavior on this generator, not on factory cameras.

| Method | Exact-decision agreement | Alarm cases routed to REVIEW | False STOP cases |
| --- | ---: | ---: | ---: |
| OpenCV 5 pipeline | 94.26% | 0 / 210 | 30 / 330 |
| Naive red-pixel count | 50.00% | 60 / 210 | 61 / 330 |
| Legacy brightness baseline | 31.85% | 76 / 210 | 244 / 330 |

Ablating image-quality gates reduced agreement to 55.56% and routed 60 / 210 synthetic alarm cases to REVIEW. Two known failures remain: all 30 round red-sticker cases caused a false STOP, and one motion-blur case returned REVIEW instead of REQUEST_VIEW. These figures are synthetic exact-decision results, not real-world accuracy or recall claims.

## Archived exhibition material and video provenance

A separate local check examined 15 archived exhibition stills (12 frames from 2026-10-04 videos and 3 photos). It produced no red candidates. These images have no verified alarm labels, are not 15 independent machine trials, and do not establish accuracy or live-camera integration.

The film combines archived machinery footage as context, AI-generated illustrative operator scenes, interface captures using synthetic inputs, and saved private AWS evidence. It does not show live-camera inference or physical equipment control.

## AWS and software verification

Four saved AWS invocations cover health, alarm, clear, and missing-view behavior. They used synthetic or empty inputs. The deployed Lambda source is 832b1b4; the workflow record is 40223113044; evidence is stored in evidence/AWS_EXECUTION_20261026_40223113044.json. The endpoint remains AWS_IAM-protected and is not a public judge endpoint. No additional AWS invocation is claimed by this report update.

Hosted GitHub Actions run 40249719964 at audited baseline b85ebb0 reports 268 tests and 116 subtests passed. Separate local Windows verification reports 266 passed, 2 POSIX-only skipped, and 116 subtests. These results refer to their recorded revisions and environments; this document update did not rerun them.

## Limits and responsible use

All controlled evaluation inputs are synthetic and the generator and detector share an author. Archived exhibition images have no alarm ground truth. Red-indicator color and shape can be confused by round stickers. Field accuracy, camera-origin verification, human acceptance, globally shared replay protection, an independently administered monotonic witness, and physical action have not been demonstrated. Keep a person in control and do not connect this prototype to equipment without separate engineering and safety validation.

## Reproduce locally

Use Python 3.12, install requirements-vision.txt and pytest==9.0.2, then run:

- python -m pytest -q
- python ops/evaluate_scene_pipeline.py --output /tmp/eval.json
- python -m service.app --host 127.0.0.1 --port 8080
- python ops/smoke_test_endpoint.py --base-url http://127.0.0.1:8080

For the read-only HTTP image: docker build --target http -t visualguard:http . then docker run --read-only --tmpfs /tmp -p 8080:8080 visualguard:http.

## Evidence references

- docs/ARCHITECTURE.md
- docs/AWS_DEPLOYMENT_RUNBOOK.md
- docs/JUDGE_EVIDENCE_INDEX.md
- evidence/CHECK146_JUDGE_EVIDENCE_INDEX.json
- evidence/AWS_EXECUTION_20261026_40223113044.json
- Public owner-review film: https://youtu.be/AEDHXknTBy8
