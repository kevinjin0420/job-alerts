#!/usr/bin/env bash
set -euo pipefail

PROFILE="${AWS_PROFILE:-notify-actions}"
REGION="${AWS_REGION:-us-west-1}"
ACCOUNT_ID="863516093571"
BUCKET="job-alerts-state-${ACCOUNT_ID}"
FUNCTION_NAME="job-alerts-watch"
ROLE_NAME="job-alerts-lambda-role"
RULE_NAME="job-alerts-watch-schedule"
RUNTIME="python3.12"
HANDLER="watch.handler"

AWS=(aws --profile "${PROFILE}" --region "${REGION}")

# The deployer's IAM policy grants lambda:GetFunction but not
# lambda:GetFunctionConfiguration, which `aws lambda wait` needs. Poll
# GetFunction (which returns the same LastUpdateStatus) instead.
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

if [ -f "${SCRIPT_DIR}/.env" ]; then
  # shellcheck source=.env
  source "${SCRIPT_DIR}/.env"
fi

for var in NTFY_TOPIC SMTP_USER SMTP_PASS; do
  if [ -z "${!var:-}" ]; then
    echo "Missing required secret: ${var} (set it in aws/.env or export it)" >&2
    exit 1
  fi
done

# shellcheck source=config.env
source "${SCRIPT_DIR}/config.env"
for var in SCHEDULE_RATE; do
  if [ -z "${!var:-}" ]; then
    echo "Missing required setting in aws/config.env: ${var}" >&2
    exit 1
  fi
done

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
"${AWS[@]}" iam put-role-policy --role-name "${ROLE_NAME}" --policy-name job-alerts-lambda-exec \
  --policy-document "file://${SCRIPT_DIR}/roles/watch-exec-policy.json"
ROLE_ARN=$("${AWS[@]}" iam get-role --role-name "${ROLE_NAME}" --query 'Role.Arn' --output text)

if [ "${ROLE_JUST_CREATED}" = "1" ]; then
  echo "==> Waiting for new role to propagate"
  sleep 10
fi

echo "==> Building deployment package"
STAGE_DIR="$(mktemp -d)"
ZIP_PATH="$(mktemp -u /tmp/job-alerts-XXXXXX).zip"
trap 'rm -rf "${STAGE_DIR}" "${ZIP_PATH}"' EXIT
cp "${REPO_ROOT}/config.py" "${REPO_ROOT}/users.py" "${REPO_ROOT}/classifier.py" "${REPO_ROOT}/resume.py" "${REPO_ROOT}/notifiers.py" "${STAGE_DIR}/"
cp "${REPO_ROOT}/watch/watch.py" "${STAGE_DIR}/"
cp -r "${REPO_ROOT}/sources" "${STAGE_DIR}/sources"
echo "==> Installing dependencies"
pip install --target "${STAGE_DIR}" pypdf --quiet
(cd "${STAGE_DIR}" && zip -qr "${ZIP_PATH}" .)

echo "==> Writing Lambda environment config"
ENV_JSON="${STAGE_DIR}/env.json"
STATE_BUCKET="${BUCKET}" NTFY_TOPIC="${NTFY_TOPIC}" SMTP_USER="${SMTP_USER}" \
  SMTP_PASS="${SMTP_PASS}" OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}" ZYTE_API_KEY="${ZYTE_API_KEY:-}" python3 -c '
import json, os, sys
required_keys = ["STATE_BUCKET", "NTFY_TOPIC", "SMTP_USER", "SMTP_PASS"]
variables = {k: os.environ[k] for k in required_keys}
if os.environ.get("OPENROUTER_API_KEY"):
    variables["OPENROUTER_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
if os.environ.get("ZYTE_API_KEY"):
    variables["ZYTE_API_KEY"] = os.environ["ZYTE_API_KEY"]
json.dump({"Variables": variables}, sys.stdout)
' > "${ENV_JSON}"

echo "==> Deploying Lambda function: ${FUNCTION_NAME}"
if "${AWS[@]}" lambda get-function --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  "${AWS[@]}" lambda update-function-code --function-name "${FUNCTION_NAME}" --zip-file "fileb://${ZIP_PATH}" >/dev/null
  wait_for_function_updated "${FUNCTION_NAME}"
  "${AWS[@]}" lambda update-function-configuration --function-name "${FUNCTION_NAME}" \
    --runtime "${RUNTIME}" --handler "${HANDLER}" --timeout 280 --memory-size 256 \
    --environment "file://${ENV_JSON}" >/dev/null
else
  "${AWS[@]}" lambda create-function --function-name "${FUNCTION_NAME}" \
    --runtime "${RUNTIME}" --handler "${HANDLER}" --role "${ROLE_ARN}" \
    --zip-file "fileb://${ZIP_PATH}" --timeout 280 --memory-size 256 \
    --environment "file://${ENV_JSON}" >/dev/null
fi
wait_for_function_updated "${FUNCTION_NAME}"
FUNCTION_ARN=$("${AWS[@]}" lambda get-function --function-name "${FUNCTION_NAME}" --query 'Configuration.FunctionArn' --output text)

echo "==> Scheduling (${SCHEDULE_RATE}): ${RULE_NAME}"
"${AWS[@]}" events put-rule --name "${RULE_NAME}" --schedule-expression "${SCHEDULE_RATE}" --state ENABLED >/dev/null
"${AWS[@]}" lambda add-permission --function-name "${FUNCTION_NAME}" --statement-id "${RULE_NAME}-invoke" \
  --action lambda:InvokeFunction --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" >/dev/null 2>&1 || true
"${AWS[@]}" events put-targets --rule "${RULE_NAME}" --targets "Id=1,Arn=${FUNCTION_ARN}" >/dev/null

echo "==> Done. Function: ${FUNCTION_ARN}"
