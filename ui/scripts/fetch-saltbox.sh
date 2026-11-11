#!/usr/bin/env bash
# Fetch the Saltbox commit the tests use as fixtures into tests/.saltbox.
# The suite reads Saltbox's real playbook, schemas, config defaults and role
# defaults; pinning the commit keeps test results reproducible. Set
# SALTBOX_COMMIT (a full commit hash) to test against a newer Saltbox.
set -euo pipefail

SALTBOX_COMMIT="${SALTBOX_COMMIT:-a9410d5aab6907be2a4f9b389aca19341db3f905}"
dest="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/tests/.saltbox"

if [ "$(git -C "$dest" rev-parse HEAD 2>/dev/null || true)" = "$SALTBOX_COMMIT" ]; then
  echo "tests/.saltbox is already at $SALTBOX_COMMIT"
  exit 0
fi
rm -rf "$dest"
git init -q "$dest"
git -C "$dest" remote add origin https://github.com/saltyorg/Saltbox.git
git -C "$dest" fetch -q --depth 1 origin "$SALTBOX_COMMIT"
git -C "$dest" -c advice.detachedHead=false checkout -q FETCH_HEAD
echo "tests/.saltbox is at $SALTBOX_COMMIT"
