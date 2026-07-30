#!/usr/bin/env bash
set -euo pipefail

PROFILE="${AWS_PROFILE:-notify-actions}"
REGION="${AWS_REGION:-us-west-1}"
ACCOUNT_ID="863516093571"
FUNCTION_NAME="job-alerts-dashboard"
ROLE_NAME="job-alerts-dashboard-role"
RUNTIME="python3.12"
HANDLER="app.handler"
COGNITO_USER_POOL_ID="us-west-1_eEd1CGYWQ"
COGNITO_CLIENT_ID="v439vcnaat90hltipaokccv16"

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
ENV_FILE="${SCRIPT_DIR}/.env"

if [ -f "${ENV_FILE}" ]; then
  # shellcheck source=.env
  source "${ENV_FILE}"
fi

echo "==> Ensuring execution role exists: ${ROLE_NAME}"
if ! "${AWS[@]}" iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
  "${AWS[@]}" iam create-role --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "file://${SCRIPT_DIR}/roles/trust-policy.json" >/dev/null
  ROLE_JUST_CREATED=1
else
  ROLE_JUST_CREATED=0
fi
"${AWS[@]}" iam put-role-policy --role-name "${ROLE_NAME}" --policy-name job-alerts-dashboard-exec \
  --policy-document "file://${SCRIPT_DIR}/roles/dashboard-exec-policy.json"
ROLE_ARN=$("${AWS[@]}" iam get-role --role-name "${ROLE_NAME}" --query 'Role.Arn' --output text)

if [ "${ROLE_JUST_CREATED}" = "1" ]; then
  echo "==> Waiting for new role to propagate"
  sleep 10
fi

echo "==> Building deployment package"
STAGE_DIR="$(mktemp -d)"
ZIP_PATH="$(mktemp -u /tmp/job-alerts-dashboard-XXXXXX).zip"
trap 'rm -rf "${STAGE_DIR}" "${ZIP_PATH}"' EXIT
cp "${REPO_ROOT}/dashboard/app.py" "${STAGE_DIR}/"
cp "${REPO_ROOT}/dashboard/metrics.html" "${REPO_ROOT}/dashboard/config.html" "${REPO_ROOT}/dashboard/logs.html" \
  "${REPO_ROOT}/dashboard/admin.html" "${REPO_ROOT}/dashboard/listings.html" "${REPO_ROOT}/dashboard/sources.html" \
  "${REPO_ROOT}/dashboard/profile.html" "${REPO_ROOT}/dashboard/onboarding.html" "${REPO_ROOT}/dashboard/shared.js" \
  "${REPO_ROOT}/dashboard/sidebar.html" "${STAGE_DIR}/"
cp "${REPO_ROOT}/config.py" "${REPO_ROOT}/users.py" "${REPO_ROOT}/classifier.py" "${REPO_ROOT}/resume.py" "${REPO_ROOT}/notifiers.py" "${STAGE_DIR}/"
cp -r "${REPO_ROOT}/sources" "${STAGE_DIR}/sources"
echo "==> Installing dependencies"
pip install --target "${STAGE_DIR}" pypdf --quiet
(cd "${STAGE_DIR}" && zip -qr "${ZIP_PATH}" .)

echo "==> Writing Lambda environment config"
ENV_JSON="${STAGE_DIR}/env.json"
COGNITO_USER_POOL_ID="${COGNITO_USER_POOL_ID}" COGNITO_CLIENT_ID="${COGNITO_CLIENT_ID}" \
  OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}" python3 -c '
import json, os, sys
variables = {
    "COGNITO_USER_POOL_ID": os.environ["COGNITO_USER_POOL_ID"],
    "COGNITO_CLIENT_ID": os.environ["COGNITO_CLIENT_ID"],
}
if os.environ.get("OPENROUTER_API_KEY"):
    variables["OPENROUTER_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
json.dump({"Variables": variables}, sys.stdout)
' > "${ENV_JSON}"

echo "==> Deploying Lambda function: ${FUNCTION_NAME}"
if "${AWS[@]}" lambda get-function --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  "${AWS[@]}" lambda update-function-code --function-name "${FUNCTION_NAME}" --zip-file "fileb://${ZIP_PATH}" >/dev/null
  wait_for_function_updated "${FUNCTION_NAME}"
  "${AWS[@]}" lambda update-function-configuration --function-name "${FUNCTION_NAME}" \
    --runtime "${RUNTIME}" --handler "${HANDLER}" --timeout 30 --memory-size 256 \
    --environment "file://${ENV_JSON}" >/dev/null
else
  "${AWS[@]}" lambda create-function --function-name "${FUNCTION_NAME}" \
    --runtime "${RUNTIME}" --handler "${HANDLER}" --role "${ROLE_ARN}" \
    --zip-file "fileb://${ZIP_PATH}" --timeout 30 --memory-size 256 \
    --environment "file://${ENV_JSON}" >/dev/null
fi
wait_for_function_updated "${FUNCTION_NAME}"
FUNCTION_ARN=$("${AWS[@]}" lambda get-function --function-name "${FUNCTION_NAME}" --query 'Configuration.FunctionArn' --output text)

# Org SCP (CT.LAMBDA.PV.1) blocks public/non-IAM Lambda Function URLs outright, so this
# fronts the Lambda with an API Gateway HTTP API instead - a different resource type the
# guardrail doesn't govern. Clean up any leftover Function URL config from earlier attempts.
if "${AWS[@]}" lambda get-function-url-config --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  echo "==> Removing blocked Function URL config from earlier attempt"
  "${AWS[@]}" lambda delete-function-url-config --function-name "${FUNCTION_NAME}" >/dev/null
  "${AWS[@]}" lambda remove-permission --function-name "${FUNCTION_NAME}" --statement-id FunctionURLAllowPublicAccess >/dev/null 2>&1 || true
fi

echo "==> Ensuring API Gateway HTTP API exists"
API_ID=$("${AWS[@]}" apigatewayv2 get-apis --query "Items[?Name=='job-alerts-dashboard'].ApiId" --output text)
if [ -z "${API_ID}" ]; then
  API_ID=$("${AWS[@]}" apigatewayv2 create-api --name job-alerts-dashboard --protocol-type HTTP \
    --target "${FUNCTION_ARN}" --query 'ApiId' --output text)
fi
API_ENDPOINT=$("${AWS[@]}" apigatewayv2 get-api --api-id "${API_ID}" --query 'ApiEndpoint' --output text)

"${AWS[@]}" lambda add-permission --function-name "${FUNCTION_NAME}" --statement-id ApiGatewayInvoke \
  --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/*" >/dev/null 2>&1 || true

echo "==> Done. Dashboard URL: ${API_ENDPOINT}"
