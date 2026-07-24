#!/usr/bin/env bash
# Generic git identity setup — copy this file into any repo.
#
# Configures git user.name/user.email for the current repo (or globally
# with --global) using your GitHub "noreply" email, so pushes never get
# rejected with:
#   remote: error: GH007: Your push would publish a private email address.
#
# Usage:
#   scripts/setup-git.sh                 # detect via `gh` CLI, set locally
#   scripts/setup-git.sh --global         # same, but git config --global
#   scripts/setup-git.sh <github-username> [--global]   # skip `gh`, use API

set -euo pipefail

SCOPE="--local"
USERNAME=""

for arg in "$@"; do
  if [ "$arg" = "--global" ]; then
    SCOPE="--global"
  else
    USERNAME="$arg"
  fi
done

if [ -z "$USERNAME" ] && command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  USERNAME="$(gh api user --jq .login)"
  USER_ID="$(gh api user --jq .id)"
fi

if [ -z "${USER_ID:-}" ]; then
  if [ -z "$USERNAME" ]; then
    read -rp "GitHub username: " USERNAME
  fi
  USER_ID="$(curl -fsSL "https://api.github.com/users/${USERNAME}" | grep -m1 '"id"' | grep -o '[0-9]\+')"
fi

if [ -z "$USER_ID" ] || [ -z "$USERNAME" ]; then
  echo "Could not determine GitHub user id/login." >&2
  exit 1
fi

EMAIL="${USER_ID}+${USERNAME}@users.noreply.github.com"

git config "$SCOPE" user.email "$EMAIL"
git config "$SCOPE" user.name "$USERNAME"

echo "git user.email set to: $EMAIL"
echo "git user.name  set to: $USERNAME"
[ "$SCOPE" = "--local" ] && echo "(scope: this repo only — rerun with --global for all repos)"
