"""Schema drift detector: local EnvelopeV1 must produce the same JSON schema
as the kairos-main-published envelope.json (mirrored into contracts/jsonschemas).

If this fails:
  - if the local model is wrong, fix it
  - if kairos main bumped the schema, run scripts/regen-contracts.sh
    (which also updates the envelope/v1 fixtures) and verify the contract
    tests still pass
"""

from __future__ import annotations

import json
from pathlib import Path

from kairos_evolve.core.envelope import EnvelopeV1

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "contracts" / "jsonschemas" / "envelope.json"


def test_envelope_v1_matches_published_schema():
    published = json.loads(SCHEMA_FILE.read_text())
    local = EnvelopeV1.model_json_schema(ref_template="#/$defs/{model}")

    # Published schema wraps in a $defs map; local model_json_schema is the
    # bare per-model schema. Compare on shape: properties + required.
    pub_envelope = published["$defs"]["EnvelopeV1"]
    for key in ("type", "properties", "required"):
        assert pub_envelope.get(key) == local.get(key), (
            f"envelope.json[{key}] != EnvelopeV1.model_json_schema()[{key}] — "
            f"published={pub_envelope.get(key)!r} local={local.get(key)!r}"
        )
