#!/usr/bin/env bash
set -euo pipefail

PROFILE="${AWS_PROFILE:-notify-actions}"
REGION="${AWS_REGION:-us-west-1}"
ACCOUNT_ID="863516093571"
BUCKET="job-alerts-state-${ACCOUNT_ID}"
FUNCTION_NAME="job-alerts-renderer"
ROLE_NAME="job-alerts-renderer-role"
RUNTIME="nodejs24.x"
HANDLER="index.handler"

AWS=(aws --profile "${PROFILE}" --region "${REGION}")

wait_for_function_updated() {
  local function_name="$1"
  local status
  for _ in $(seq 1 30); do
    status=$("${AWS[@]}" lambda get-function --function-name "${function_name}" --query 'Configuration.LastUpdateStatus' --output text)
    if [ "${status}" = "Successful" ]; then
      return 0
    fi
    sleep 2
  done
  echo "Timed out waiting for ${function_name} to finish updating (last status: ${status})" >&2
  return 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${SCRIPT_DIR}")"

echo "==> Ensuring state bucket exists: ${BUCKET}"
if ! "${AWS[@]}" s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
  "${AWS[@]}" s3api create-bucket --bucket "${BUCKET}" --create-bucket-configuration LocationConstraint="${REGION}"
  "${AWS[@]}" s3api put-public-access-block --bucket "${BUCKET}" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

echo "==> Ensuring execution role exists: ${ROLE_NAME}"
if ! "${AWS[@]}" iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
  "${AWS[@]}" iam create-role --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "file://${SCRIPT_DIR}/roles/trust-policy.json" >/dev/null
  ROLE_JUST_CREATED=1
else
  ROLE_JUST_CREATED=0
fi
"${AWS[@]}" iam put-role-policy --role-name "${ROLE_NAME}" --policy-name job-alerts-renderer-exec \
  --policy-document "file://${SCRIPT_DIR}/roles/renderer-exec-policy.json"
ROLE_ARN=$("${AWS[@]}" iam get-role --role-name "${ROLE_NAME}" --query 'Role.Arn' --output text)

if [ "${ROLE_JUST_CREATED}" = "1" ]; then
  echo "==> Waiting for new role to propagate"
  sleep 10
fi

echo "==> Installing dependencies (npm ci, production only)"
(cd "${REPO_ROOT}/renderer" && npm ci --omit=dev)

echo "==> Building deployment package"
ZIP_PATH="$(mktemp -u /tmp/job-alerts-renderer-XXXXXX).zip"
trap 'rm -f "${ZIP_PATH}"' EXIT
(cd "${REPO_ROOT}/renderer" && zip -qr "${ZIP_PATH}" index.js package.json node_modules)

# Chromium + node_modules puts this well past Lambda's 50MB direct-upload cap - upload via the
# existing state bucket instead (deployer already has s3:PutObject on job-alerts-* per
# aws/policies/job-alerts-storage-policy.json, so this needs no new IAM grant).
S3_KEY="renderer/$(date +%s).zip"
echo "==> Uploading package to s3://${BUCKET}/${S3_KEY}"
"${AWS[@]}" s3 cp "${ZIP_PATH}" "s3://${BUCKET}/${S3_KEY}" >/dev/null

echo "==> Deploying Lambda function: ${FUNCTION_NAME}"
if "${AWS[@]}" lambda get-function --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  "${AWS[@]}" lambda update-function-code --function-name "${FUNCTION_NAME}" \
    --s3-bucket "${BUCKET}" --s3-key "${S3_KEY}" >/dev/null
  wait_for_function_updated "${FUNCTION_NAME}"
  "${AWS[@]}" lambda update-function-configuration --function-name "${FUNCTION_NAME}" \
    --runtime "${RUNTIME}" --handler "${HANDLER}" --timeout 60 --memory-size 2048 >/dev/null
else
  "${AWS[@]}" lambda create-function --function-name "${FUNCTION_NAME}" \
    --runtime "${RUNTIME}" --handler "${HANDLER}" --role "${ROLE_ARN}" \
    --code "S3Bucket=${BUCKET},S3Key=${S3_KEY}" --timeout 60 --memory-size 2048 >/dev/null
fi
wait_for_function_updated "${FUNCTION_NAME}"
FUNCTION_ARN=$("${AWS[@]}" lambda get-function --function-name "${FUNCTION_NAME}" --query 'Configuration.FunctionArn' --output text)

echo "==> Done. Function: ${FUNCTION_ARN}"
