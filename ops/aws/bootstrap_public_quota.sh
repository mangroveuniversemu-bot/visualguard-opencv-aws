#!/usr/bin/env bash
# VisualGuard: prepare the quota prerequisites; never publish a Function URL.
set -euo pipefail
export AWS_PAGER=""

if [[ "${1:-}" != "--apply" ]]; then
  cat <<'PLAN'
PREVIEW — no AWS calls made.
On --apply, use the current AWS sign-in in us-east-1 to:
  1. Confirm the existing VisualGuard function is still AWS_IAM.
  2. Create/reuse visualguard-daily-quota (on-demand; quota_date String).
  3. Add only dynamodb:UpdateItem on that table to visualguard-lambda-runtime.
  4. Add lambda:AddPermission/GetPolicy on only visualguard-inspector to
     visualguard-github-deploy.
Existing inline policies with different content stop the script.
No access keys, deployments, Function URL changes or inference requests.
The on-demand table may incur charges. This does not create a dollar cap.
After reviewing the scope, run this file with --apply in AWS CloudShell.
PLAN
  exit 0
fi

command -v aws >/dev/null || { echo 'AWS CLI required.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Python 3 required.' >&2; exit 1; }
vg_region=us-east-1
vg_table=visualguard-daily-quota
vg_runtime=visualguard-lambda-runtime
vg_deploy=visualguard-github-deploy
vg_function=visualguard-inspector
vg_tmp=$(mktemp -d)
trap 'rm -rf -- "$vg_tmp"' EXIT
vg_aws() { aws "$@" --region "$vg_region" --no-cli-pager; }
vg_account=$(vg_aws sts get-caller-identity --query Account --output text)
[[ "$vg_account" =~ ^[0-9]{12}$ ]] || { echo 'Invalid AWS account.' >&2; exit 1; }

vg_check_private() {
  local auth url role
  vg_aws lambda get-function-url-config --function-name "$vg_function" --output json > "$vg_tmp/function-url.json"
  auth=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["AuthType"])' "$vg_tmp/function-url.json")
  url=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["FunctionUrl"])' "$vg_tmp/function-url.json")
  [[ "$url" == 'https://zkdmdpnivndaqlsxgm4umbjwjy0akezq.lambda-url.us-east-1.on.aws/' ]] || { echo 'STOP: URL differs from the recorded VisualGuard AWS deployment.' >&2; exit 1; }
  role=$(vg_aws lambda get-function-configuration --function-name "$vg_function" --query Role --output text)
  [[ "$role" == "arn:aws:iam::$vg_account:role/$vg_runtime" ]] || { echo 'STOP: function runtime role differs from the recorded role.' >&2; exit 1; }
  [[ "$auth" == AWS_IAM ]] || { echo 'STOP: expected the existing AWS_IAM URL; inspect concurrent changes.' >&2; exit 1; }
}
vg_check_private
for vg_role in "$vg_runtime" "$vg_deploy"; do
  vg_aws iam get-role --role-name "$vg_role" --output json > "$vg_tmp/$vg_role.json"
done
python3 - "$vg_tmp" "$vg_account" "$vg_runtime" "$vg_deploy" <<'PY'
import json, pathlib, sys
root, account, *roles = sys.argv[1:]
for role in roles:
    value = json.loads((pathlib.Path(root) / (role + '.json')).read_text())['Role']
    if value['Arn'] != f'arn:aws:iam::{account}:role/{role}':
        raise SystemExit('STOP: role ARN differs from the documented VisualGuard role.')
PY

cat > "$vg_tmp/quota.json" <<EOF
{"Version":"2012-10-17","Statement":[{"Sid":"UseVisualGuardDailyInferenceQuotaOnly","Effect":"Allow","Action":"dynamodb:UpdateItem","Resource":"arn:aws:dynamodb:$vg_region:$vg_account:table/$vg_table"}]}
EOF
cat > "$vg_tmp/public-permission.json" <<EOF
{"Version":"2012-10-17","Statement":[{"Sid":"OnlyIfOwnerApprovesAPublicJudgeUrl","Effect":"Allow","Action":["lambda:AddPermission","lambda:GetPolicy"],"Resource":"arn:aws:lambda:$vg_region:$vg_account:function:$vg_function"}]}
EOF

# Inspect all prerequisites before the first write. Never overwrite an
# unrelated policy, and distinguish absence from AccessDenied/network errors.
vg_check_policy() {
  local role=$1 policy=$2 expected=$3 required=${4:-false}
  if vg_aws iam get-role-policy --role-name "$role" --policy-name "$policy" --output json > "$vg_tmp/$policy.existing.json" 2> "$vg_tmp/error"; then
    python3 - "$vg_tmp/$policy.existing.json" "$expected" <<'PY'
import json, sys
actual = json.load(open(sys.argv[1]))['PolicyDocument']
expected = json.load(open(sys.argv[2]))
if actual != expected:
    raise SystemExit('STOP: an existing policy with this name has different content; inspect the partial state before continuing.')
PY
  elif [[ "$required" == true ]] || ! grep -q 'NoSuchEntity' "$vg_tmp/error"; then
    echo 'STOP: cannot inspect the existing inline policy.' >&2
    cat "$vg_tmp/error" >&2
    exit 1
  fi
}
vg_check_policy "$vg_runtime" visualguard-daily-quota-updateitem "$vg_tmp/quota.json"
vg_check_policy "$vg_deploy" visualguard-public-url-addendum "$vg_tmp/public-permission.json"
vg_create_table=false
vg_check_table() {
  python3 - "$vg_tmp/table.json" "${1:-false}" <<'PY' 
import json, sys
t = json.load(open(sys.argv[1]))['Table']
key = [{'AttributeName': 'quota_date', 'KeyType': 'HASH'}]
defs = [{'AttributeName': 'quota_date', 'AttributeType': 'S'}]
if t.get('KeySchema') != key or t.get('AttributeDefinitions') != defs:
    raise SystemExit('STOP: existing table has a different key schema.')
if t.get('BillingModeSummary', {}).get('BillingMode') != 'PAY_PER_REQUEST':
    raise SystemExit('STOP: existing table is not on-demand.')
if sys.argv[2] == 'true' and t.get('TableStatus') != 'ACTIVE':
    raise SystemExit('STOP: quota table is not ACTIVE.')
PY
}
if vg_aws dynamodb describe-table --table-name "$vg_table" --output json > "$vg_tmp/table.json" 2> "$vg_tmp/error"; then
  vg_check_table
elif grep -q 'ResourceNotFoundException' "$vg_tmp/error"; then
  vg_create_table=true
else
  echo 'STOP: cannot inspect the quota table.' >&2
  cat "$vg_tmp/error" >&2
  exit 1
fi

if [[ "$vg_create_table" == true ]]; then
  vg_aws dynamodb create-table --table-name "$vg_table" --billing-mode PAY_PER_REQUEST \
    --attribute-definitions AttributeName=quota_date,AttributeType=S \
    --key-schema AttributeName=quota_date,KeyType=HASH \
    --tags Key=project,Value=visualguard --output json > "$vg_tmp/created.json"
fi
vg_aws dynamodb wait table-exists --table-name "$vg_table"
vg_aws dynamodb describe-table --table-name "$vg_table" --output json > "$vg_tmp/table.json"
vg_check_table true
vg_check_private
vg_aws iam put-role-policy --role-name "$vg_runtime" --policy-name visualguard-daily-quota-updateitem --policy-document "file://$vg_tmp/quota.json"
vg_aws iam put-role-policy --role-name "$vg_deploy" --policy-name visualguard-public-url-addendum --policy-document "file://$vg_tmp/public-permission.json"
vg_check_policy "$vg_runtime" visualguard-daily-quota-updateitem "$vg_tmp/quota.json" true
vg_check_policy "$vg_deploy" visualguard-public-url-addendum "$vg_tmp/public-permission.json" true
vg_check_private
printf '%s\n' 'QUOTA_PREREQUISITES_READY' 'Function URL remains AWS_IAM. No inference request made.' 'Next: deploy the verified quota source through the existing aws-deploy-public-* tag workflow.'
