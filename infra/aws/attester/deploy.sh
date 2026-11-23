#!/usr/bin/env bash
# Deploys the stack tower-gate-attester (D-359 Salto 2; infra/aws/attester/README.md). Run by the Torre with the account's
# credentials, never by the app deployer (the stack is not under infra/aws/stacks/). It zips attester.py deterministically,
# uploads it once as artifacts/lambda/tower-gate-attester/<sha256>.zip to the outputs bucket and deploys stack.json.
# Usage: infra/aws/attester/deploy.sh [APP_ID]   (APP_ID: the App's numeric id; omitted keeps the deployed one)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
region="${AWS_REGION:-us-east-1}"
account="$(aws sts get-caller-identity --query Account --output text)"
bucket="tower-outputs-${account}-${region}"
zip="$(mktemp -d)/attester.zip"
python3 - "$here/attester.py" "$zip" <<'PY'
import sys, zipfile
src, out = sys.argv[1:3]
info = zipfile.ZipInfo('attester.py', date_time=(1980, 1, 1, 0, 0, 0))
info.external_attr = 0o644 << 16
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    z.writestr(info, open(src, 'rb').read())
PY
sha="$(sha256sum "$zip" | cut -d' ' -f1)"
key="artifacts/lambda/tower-gate-attester/${sha}.zip"
aws s3api head-object --bucket "$bucket" --key "$key" >/dev/null 2>&1 || aws s3 cp --only-show-errors "$zip" "s3://$bucket/$key"
params=("CodeKey=$key")
if [[ -n "${1:-}" ]]; then params+=("AppId=$1"); fi
aws cloudformation deploy --region "$region" --stack-name tower-gate-attester --template-file "$here/stack.json" \
  --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset --tags project=tower \
  --parameter-overrides "${params[@]}"
aws cloudformation describe-stacks --region "$region" --stack-name tower-gate-attester \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output text
