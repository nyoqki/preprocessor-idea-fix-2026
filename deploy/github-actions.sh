#!/usr/bin/env bash
set -Eeuo pipefail

: "${DEPLOY_SSH_KEY:?YASNO_DEPLOY_SSH_KEY repository secret is required}"
: "${IMAGE_DIGEST:?The checked image digest is required}"
: "${GITHUB_SHA:?GITHUB_SHA is required}"
: "${GITHUB_ACTOR:?GITHUB_ACTOR is required}"
: "${GH_TOKEN:?A short-lived package-read token is required}"

latest=$(git ls-remote origin refs/heads/main | cut -f1)
if [[ "$latest" != "$GITHUB_SHA" ]]; then
  printf 'Skip outdated release %s; main is %s.\n' "$GITHUB_SHA" "$latest"
  exit 0
fi
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]

umask 077
key_dir=$(mktemp -d)
trap 'rm -rf "$key_dir"' EXIT
printf '%s\n' "$DEPLOY_SSH_KEY" > "$key_dir/id_ed25519"
unset DEPLOY_SSH_KEY

jq -nc '{registry_user: env.GITHUB_ACTOR, registry_token: env.GH_TOKEN}' |
  ssh -i "$key_dir/id_ed25519" \
    -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile=deploy/known_hosts \
    -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=20 \
    -p 23971 admin@207.2.120.48 "deploy $GITHUB_SHA $IMAGE_DIGEST"
