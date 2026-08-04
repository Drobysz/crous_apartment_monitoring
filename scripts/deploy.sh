#!/usr/bin/env bash
# Runs on the production host through the protected deployment workflow.
set -Eeuo pipefail

: "${PRODUCTION_PATH:?PRODUCTION_PATH is required}"
: "${IMAGE_TAG:?IMAGE_TAG is required}"
: "${IMAGE_REPOSITORY:?IMAGE_REPOSITORY is required}"
: "${GHCR_DEPLOY_TOKEN:?GHCR_DEPLOY_TOKEN is required}"
: "${GHCR_USERNAME:?GHCR_USERNAME is required}"

exec 9>"${PRODUCTION_PATH}/.deploy.lock"
flock -n 9 || { echo "A deployment is already running" >&2; exit 1; }
cd "$PRODUCTION_PATH"

previous_tag="$(awk -F= '$1 == "IMAGE_TAG" { print $2 }' .deploy-image.env 2>/dev/null || true)"
printf '%s' "$GHCR_DEPLOY_TOKEN" | docker login ghcr.io --username "$GHCR_USERNAME" --password-stdin
export CROUS_IMAGE="${IMAGE_REPOSITORY}:${IMAGE_TAG}"
export CROUS_WEB_IMAGE="${CROUS_IMAGE}-web"
export IMAGE_TAG
docker compose pull app api admin_panel worker notification_bot next_app
docker compose run --rm migrate
printf 'IMAGE_TAG=%s\n' "$IMAGE_TAG" > .deploy-image.env
docker compose up -d --no-build app api admin_panel worker notification_bot next_app proxy

if ! curl --fail --silent --show-error --retry 12 --retry-delay 5 http://127.0.0.1/healthz >/dev/null; then
  echo "Deployment health check failed; application remains on the newly migrated schema." >&2
  if [[ -n "$previous_tag" ]]; then
    echo "Previous image tag was: $previous_tag. Roll back the image only after confirming schema compatibility." >&2
  fi
  docker compose ps
  exit 1
fi
docker compose ps
