#!/usr/bin/env bash
# Sync jsonschemas + envelope fixtures from a local kairos checkout.
#
# Usage:
#   KAIROS_REPO=/path/to/kairos ./scripts/regen-contracts.sh
#
# Or invoke from this repo's root with $KAIROS_REPO set in environment.
#
# Phase 1 only mirrors envelope.json from contracts/jsonschemas/ and the
# 5 envelope/v1/*.json fixtures. L3-L6 schemas are pulled in their respective
# implementation phases when their consumers land.

set -euo pipefail

if [ -z "${KAIROS_REPO:-}" ]; then
  echo "ERROR: set KAIROS_REPO to the path of a local KairosPan/kairos checkout" >&2
  echo "  e.g. KAIROS_REPO=/Volumes/kairos/heuristic/kairos/kairos $0" >&2
  exit 2
fi

if [ ! -d "$KAIROS_REPO/packages/harness/src/kairos_harness/optimizer/contracts/jsonschemas" ]; then
  echo "ERROR: $KAIROS_REPO does not look like a kairos checkout (missing contracts/jsonschemas)" >&2
  exit 2
fi

THIS_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Mirror jsonschemas (Phase 1: envelope only)
mkdir -p "$THIS_DIR/contracts/jsonschemas"
cp "$KAIROS_REPO/packages/harness/src/kairos_harness/optimizer/contracts/jsonschemas/envelope.json" \
   "$THIS_DIR/contracts/jsonschemas/envelope.json"

# Mirror envelope/v1 fixtures
mkdir -p "$THIS_DIR/shared/envelope/v1"
for fixture in batch_merkle expired_rejected field_order_stable sign_verify tampered_rejected; do
  cp "$KAIROS_REPO/shared/envelope/v1/${fixture}.json" \
     "$THIS_DIR/shared/envelope/v1/${fixture}.json"
done

# Print provenance so the commit message can record what was synced
( cd "$KAIROS_REPO" && echo "synced from kairos $(git rev-parse HEAD) on $(date -u +%FT%TZ)" )

echo "OK: mirrored 1 jsonschema + 5 envelope fixtures"
