#!/bin/sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
TOKEN_FILE="${GITHUB_TOKEN_FILE:-/root/.github-token}"
if [ -z "$GITHUB_TOKEN" ] && [ -f "$TOKEN_FILE" ]; then
  GITHUB_TOKEN=$(cat "$TOKEN_FILE")
fi
if [ -z "$GITHUB_TOKEN" ]; then
  echo "Set GITHUB_TOKEN or write a PAT to $TOKEN_FILE"
  echo "  https://github.com/settings/tokens (repo scope)"
  exit 1
fi
export GITHUB_TOKEN
python3 /tmp/push_all_github.py
# Or simple git push:
git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/mobiletru/sunny_island.git"
git push -u origin main
echo "Done. Remote: https://github.com/mobiletru/sunny_island"
