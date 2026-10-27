# Current public film review gate

This gate applies only to the current 2:20 owner-review film at
<https://youtu.be/AEDHXknTBy8>. It does not reuse or upgrade the historical
CHECK146 180-second storyboard contract.

## Inputs

1. Download the exact published film to a local path without transcoding it.
2. A reviewer who is distinct from the operator watches the entire file and
   records whether it visibly covers the solo team, working application,
   architecture, and principal results.
3. The reviewer records the exact video SHA-256 and size, the checked-in
   contract SHA-256, and the claim boundary below. Do not commit the media or a
   receipt containing personal information.

The review JSON uses this shape:

```json
{
  "schema_version": 1,
  "status": "INDEPENDENT_REVIEWED",
  "operator_id": "role-identifier",
  "reviewer_id": "different-role-identifier",
  "contract_sha256": "64 lowercase hex characters",
  "video_sha256": "64 lowercase hex characters",
  "video_size_bytes": 123,
  "public_film_url": "https://youtu.be/AEDHXknTBy8",
  "observed_requirements": [
    "solo_team",
    "working_application",
    "architecture",
    "principal_results"
  ],
  "claim_boundary": {
    "synthetic_inputs_disclosed": true,
    "public_aws_endpoint_disclosed": true,
    "live_camera_claimed": false,
    "field_accuracy_claimed": false,
    "physical_action_claimed": false,
    "credentials_visible": false
  },
  "credentials_exposed": false
}
```

Run the fail-closed verifier locally:

```bash
python ops/verify_public_film_evidence.py \
  --video .local/public-film.mp4 \
  --review .local/public-film-review.json
```

A PASS binds the reviewed local bytes to the observations and boundary. It
does not authenticate YouTube delivery, prove field accuracy, show a live
camera, execute a physical action, or authorize another AWS deployment.
