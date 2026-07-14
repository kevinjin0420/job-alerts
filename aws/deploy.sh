#!/usr/bin/env bash
set -euo pipefail

PROFILE="${AWS_PROFILE:-notify-actions}"
REGION="${AWS_REGION:-us-west-1}"
ACCOUNT_ID="863516093571"
BUCKET="notify-actions-state-${ACCOUNT_ID}"
FUNCTION_NAME="notify-actions-watch"
ROLE_NAME="notify-actions-lambda-role"
RULE_NAME="notify-actions-watch-schedule"
RUNTIME="python3.12"
HANDLER="lambda_function.handler"

AWS=(aws --profile "${PROFILE}" --region "${REGION}")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${SCRIPT_DIR}")"

if [ -f "${SCRIPT_DIR}/.env" ]; then
  # shellcheck source=.env
  source "${SCRIPT_DIR}/.env"
fi

for var in NTFY_TOPIC EMAIL_TO SMTP_USER SMTP_PASS; do
  if [ -z "${!var:-}" ]; then
    echo "Missing required secret: ${var} (set it in aws/.env or export it)" >&2
    exit 1
  fi
done

# shellcheck source=config.env
source "${SCRIPT_DIR}/config.env"
for var in SCHEDULE_RATE COMPANIES ENABLED_SOURCES; do
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
    --assume-role-policy-document "file://${SCRIPT_DIR}/lambda-trust-policy.json" >/dev/null
  ROLE_JUST_CREATED=1
else
  ROLE_JUST_CREATED=0
fi
"${AWS[@]}" iam put-role-policy --role-name "${ROLE_NAME}" --policy-name notify-actions-lambda-exec \
  --policy-document "file://${SCRIPT_DIR}/lambda-exec-policy.json"
ROLE_ARN=$("${AWS[@]}" iam get-role --role-name "${ROLE_NAME}" --query 'Role.Arn' --output text)

if [ "${ROLE_JUST_CREATED}" = "1" ]; then
  echo "==> Waiting for new role to propagate"
  sleep 10
fi

echo "==> Building deployment package"
STAGE_DIR="$(mktemp -d)"
ZIP_PATH="$(mktemp -u /tmp/notify-actions-XXXXXX).zip"
trap 'rm -rf "${STAGE_DIR}" "${ZIP_PATH}"' EXIT
cp "${REPO_ROOT}"/*.py "${STAGE_DIR}/"
cp -r "${REPO_ROOT}/sources" "${STAGE_DIR}/sources"
(cd "${STAGE_DIR}" && zip -qr "${ZIP_PATH}" .)

echo "==> Writing Lambda environment config"
ENV_JSON="${STAGE_DIR}/env.json"
STATE_BUCKET="${BUCKET}" NTFY_TOPIC="${NTFY_TOPIC}" EMAIL_TO="${EMAIL_TO}" SMTP_USER="${SMTP_USER}" \
  SMTP_PASS="${SMTP_PASS}" COMPANIES="${COMPANIES}" ENABLED_SOURCES="${ENABLED_SOURCES}" python3 -c '
import json, os, sys
keys = ["STATE_BUCKET", "NTFY_TOPIC", "EMAIL_TO", "SMTP_USER", "SMTP_PASS", "COMPANIES", "ENABLED_SOURCES"]
variables = {k: os.environ[k] for k in keys}
json.dump({"Variables": variables}, sys.stdout)
' > "${ENV_JSON}"

echo "==> Deploying Lambda function: ${FUNCTION_NAME}"
if "${AWS[@]}" lambda get-function --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  "${AWS[@]}" lambda update-function-code --function-name "${FUNCTION_NAME}" --zip-file "fileb://${ZIP_PATH}" >/dev/null
  "${AWS[@]}" lambda wait function-updated --function-name "${FUNCTION_NAME}"
  "${AWS[@]}" lambda update-function-configuration --function-name "${FUNCTION_NAME}" \
    --runtime "${RUNTIME}" --handler "${HANDLER}" --timeout 60 --memory-size 256 \
    --environment "file://${ENV_JSON}" >/dev/null
else
  "${AWS[@]}" lambda create-function --function-name "${FUNCTION_NAME}" \
    --runtime "${RUNTIME}" --handler "${HANDLER}" --role "${ROLE_ARN}" \
    --zip-file "fileb://${ZIP_PATH}" --timeout 60 --memory-size 256 \
    --environment "file://${ENV_JSON}" >/dev/null
fi
"${AWS[@]}" lambda wait function-updated --function-name "${FUNCTION_NAME}"
FUNCTION_ARN=$("${AWS[@]}" lambda get-function --function-name "${FUNCTION_NAME}" --query 'Configuration.FunctionArn' --output text)

echo "==> Scheduling (${SCHEDULE_RATE}): ${RULE_NAME}"
"${AWS[@]}" events put-rule --name "${RULE_NAME}" --schedule-expression "${SCHEDULE_RATE}" --state ENABLED >/dev/null
"${AWS[@]}" lambda add-permission --function-name "${FUNCTION_NAME}" --statement-id "${RULE_NAME}-invoke" \
  --action lambda:InvokeFunction --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" >/dev/null 2>&1 || true
"${AWS[@]}" events put-targets --rule "${RULE_NAME}" --targets "Id=1,Arn=${FUNCTION_ARN}" >/dev/null

echo "==> Done. Function: ${FUNCTION_ARN}"
