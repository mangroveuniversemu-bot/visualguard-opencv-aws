# VisualGuard architecture

Status labels are part of the diagram: anything marked **NOT_RUN** has not
executed on AWS. Local, CI and emulator runs are listed in
[`TECHNICAL_REPORT.md`](TECHNICAL_REPORT.md).

## System

```mermaid
flowchart LR
  subgraph Client
    UI["Browser demo page<br/>GET /"]
    Agent["Workflow / agent client<br/>POST /v1/inspect"]
  end
  subgraph AWS["AWS (prepared, NOT_RUN)"]
    URL["Lambda Function URL<br/>AWS_IAM by default"]
    subgraph Lambda["Lambda container image (ECR, immutable digest)"]
      Core["service.app.Service.handle<br/>decode, size limits, structured log"]
      Pipe["vision.scene_analysis<br/>OpenCV 5 quality gates + indicator detection"]
      Fuse["two-view fusion<br/>alarm wins, then unusable views block"]
      Ledger[("capture replay ledger<br/>SQLite in /tmp, per instance")]
      Plan["vision.follow_up.plan_follow_up<br/>planned action, never executed"]
    end
    CW["CloudWatch Logs<br/>JSON request lines + REPORT"]
  end
  subgraph Delivery["Delivery"]
    GH["GitHub Actions<br/>aws-* tag or manual dispatch"]
    OIDC["OIDC role assumption<br/>no stored AWS keys"]
    ECR["ECR repository visualguard<br/>IMMUTABLE tags, keep 3"]
  end
  UI --> URL
  Agent --> URL
  URL --> Core --> Pipe --> Fuse --> Plan
  Pipe --- Ledger
  Core --> CW
  GH --> OIDC --> ECR --> Lambda
```

The same `Service.handle` core runs in three places with identical rules:
`python -m service.app` (local), the `http` image target (App Runner / ECS /
local container), and the `lambda` image target through
`service.lambda_handler.handler`.

## Perception, decision, action loop

```mermaid
flowchart TD
  A["Two bound views: front + side<br/>source_id, capture_id, captured_at"] --> B{"Provenance checks<br/>coverage, freshness, skew,<br/>source, duplicate IDs/buffers"}
  B -- fail --> R1["REQUEST_VIEW or STOP"]
  B -- pass --> C["Per view, OpenCV 5:<br/>Sobel/Laplacian sharpness<br/>calcHist exposure<br/>dark-cell occlusion<br/>HSV inRange + morphology +<br/>findContours shape tests"]
  C --> D{"Replay ledger<br/>capture_id -> envelope SHA-256"}
  D -- substituted bytes --> R2["STOP<br/>CAPTURE_ID_REPLAY_MISMATCH"]
  D -- recorded / replayed --> E{"Fusion"}
  E -- lit red indicator in any view --> S["STOP / ALARM"]
  E -- any view unusable --> Q["REQUEST_VIEW / reason"]
  E -- otherwise --> V["REVIEW / HUMAN_REVIEW"]
  S --> P1["HOLD_AUTOMATION"]
  Q --> P2["REQUEST_NEW_CAPTURE"]
  V --> P3["QUEUE_HUMAN_REVIEW"]
  R1 --> P0["planned action recorded"]
  R2 --> P1
  P1 & P2 & P3 & P0 --> H["Human control:<br/>action_executed = false<br/>physical_action = NONE"]
```

The vision result changes the next step: the same request shape yields
`QUEUE_HUMAN_REVIEW`, `REQUEST_NEW_CAPTURE` or `HOLD_AUTOMATION` depending on
the pixels. Every `/v1/inspect` response includes a `trace` with the
`perceive`, `decide` and `plan` steps, and every request writes one JSON log
line (no image data).

## Trust boundaries and limits

- Replay protection is per Lambda execution environment (SQLite in `/tmp`).
  Concurrent instances do not share it; a shared store (for example
  DynamoDB conditional writes) would be needed for global replay protection.
- `execution_environment` in responses is self-reported. The Lambda Runtime
  Interface Emulator sets the same variables locally, so only AWS-side
  evidence (CloudWatch `REPORT` lines, `aws lambda invoke` results) counts.
- The witness/anchor modules in `vision/opencv5_inspection.py` use local
  HMAC fixtures; no independently administered witness exists.
- No camera, actuator or external side effect exists anywhere in the system.
