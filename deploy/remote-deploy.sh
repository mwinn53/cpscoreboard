#!/bin/bash
# Runs ON the EC2 instance (as root, via SSM Run Command from ssm-deploy.sh).
# Usage: remote-deploy.sh <image-uri> <aws-region>
set -euo pipefail

IMAGE="$1"
REGION="$2"
APP_DIR=/opt/cpscoreboard
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

# On a brand-new instance, wait for first-boot setup (Docker, /data mount) to finish.
cloud-init status --wait >/dev/null || true
command -v docker >/dev/null || { echo "Docker is not installed; check cloud-init" >&2; exit 1; }
mountpoint -q /data || { echo "/data is not mounted; check cloud-init" >&2; exit 1; }

mkdir -p "$APP_DIR"
install -m 0644 "$SRC_DIR/docker-compose.prod.yml" "$APP_DIR/docker-compose.yml"
install -m 0644 "$SRC_DIR/Caddyfile" "$APP_DIR/Caddyfile"

# Build .env from SSM: /cpscoreboard/env/<KEY> -> KEY='value'
{
  echo "IMAGE='$IMAGE'"
  echo "AWS_REGION='$REGION'"
  aws ssm get-parameters-by-path --region "$REGION" --path /cpscoreboard/env/ \
      --recursive --with-decryption --query 'Parameters[].[Name,Value]' --output text |
    while IFS=$'\t' read -r name value; do
      if [[ "$value" == *"'"* ]]; then
        echo "Skipping ${name}: single quotes are not supported in values" >&2
        continue
      fi
      echo "${name##*/}='$value'"
    done
} > "$APP_DIR/.env.new"
chmod 0600 "$APP_DIR/.env.new"
mv "$APP_DIR/.env.new" "$APP_DIR/.env"

aws ecr get-login-password --region "$REGION" |
  docker login --username AWS --password-stdin "${IMAGE%%/*}" >/dev/null

cd "$APP_DIR"
docker compose pull --quiet
docker compose up -d --remove-orphans
docker image prune -f >/dev/null

# Wait for the app's Docker health check (/healthz).
APP_CONTAINER="$(docker compose ps -q app)"
status=unknown
for _ in $(seq 1 30); do
  status="$(docker inspect -f '{{.State.Health.Status}}' "$APP_CONTAINER" 2>/dev/null || echo unknown)"
  [ "$status" = healthy ] && break
  sleep 3
done
if [ "$status" != healthy ]; then
  echo "App did not become healthy (last status: $status)" >&2
  docker compose logs --tail 50 app >&2 || true
  exit 1
fi
echo "App container healthy"

# End-to-end check through Caddy over HTTPS with certificate validation, run from the instance
# itself (the site may be IP-restricted, so GitHub's runners can't reach it). Passes if any
# configured hostname works; a brand-new hostname may still be waiting for DNS/its certificate.
SITE_ADDRESS="$(sed -n "s/^SITE_ADDRESS='\(.*\)'$/\1/p" .env)"
IFS=',' read -ra HOSTS <<< "$SITE_ADDRESS"
for _ in $(seq 1 12); do
  for host in "${HOSTS[@]}"; do
    host="$(echo "$host" | xargs)"
    if curl -fsS --max-time 5 --resolve "$host:443:127.0.0.1" "https://$host/healthz" >/dev/null 2>&1; then
      echo "Deployed $IMAGE — https://$host/healthz OK via Caddy"
      docker compose ps
      exit 0
    fi
  done
  sleep 5
done

echo "Caddy did not serve /healthz over HTTPS for: $SITE_ADDRESS" >&2
docker compose logs --tail 30 caddy >&2 || true
exit 1
