#!/usr/bin/env bash
# Runs in GitHub Actions (or anywhere with AWS credentials): ships the deploy/ bundle to
# the instance via SSM Run Command, runs remote-deploy.sh there, and reports the result.
# Requires: INSTANCE_ID, IMAGE, AWS_REGION; aws CLI and jq.
set -euo pipefail
: "${INSTANCE_ID:?}" "${IMAGE:?}" "${AWS_REGION:?}"

here="$(cd "$(dirname "$0")" && pwd)"
bundle="$(tar -C "$here" -czf - docker-compose.prod.yml Caddyfile remote-deploy.sh | base64 -w0)"

remote="set -e
d=\$(mktemp -d)
echo '$bundle' | base64 -d | tar -xz -C \"\$d\"
bash \"\$d/remote-deploy.sh\" '$IMAGE' '$AWS_REGION' && rc=0 || rc=\$?
rm -rf \"\$d\"
exit \$rc"

params="$(jq -n --arg c "$remote" '{commands: [$c], executionTimeout: ["900"]}')"

command_id="$(aws ssm send-command \
  --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "deploy ${GITHUB_SHA:-manual}" \
  --parameters "$params" \
  --query Command.CommandId --output text)"
echo "SSM command $command_id sent to $INSTANCE_ID"

status=Pending
for _ in $(seq 1 180); do
  sleep 5
  status="$(aws ssm get-command-invocation --region "$AWS_REGION" \
    --command-id "$command_id" --instance-id "$INSTANCE_ID" \
    --query Status --output text 2>/dev/null || echo Pending)"
  case "$status" in
    Success | Failed | Cancelled | TimedOut) break ;;
  esac
done

invocation() {
  aws ssm get-command-invocation --region "$AWS_REGION" \
    --command-id "$command_id" --instance-id "$INSTANCE_ID" --query "$1" --output text
}
echo "--- remote stdout ---"; invocation StandardOutputContent
echo "--- remote stderr ---"; invocation StandardErrorContent
echo "Deploy status: $status"
[ "$status" = Success ]
