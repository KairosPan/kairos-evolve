"""Schema drift detector for the candidate-return contract (Slice 9 / #34).

If this fails:
  - if our local Pydantic model drifted, fix it
  - if kairos main bumped candidate.json, run scripts/regen-contracts.sh
    and confirm our model still matches
"""

from __future__ import annotations

import json
from pathlib import Path

from kairos_evolve.core.candidate_contracts import CandidateReturn

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "contracts" / "jsonschemas" / "candidate.json"


def _compare(name: str, local_schema: dict, published_defs: dict) -> None:
    pub = published_defs[name]
    for key in ("type", "properties", "required"):
        assert pub.get(key) == local_schema.get(key), (
            f"candidate.json[{name}][{key}] != local {name}.model_json_schema()[{key}] — "
            f"published={pub.get(key)!r} local={local_schema.get(key)!r}"
        )


def test_candidate_return_matches_published_schema():
    published = json.loads(SCHEMA_FILE.read_text())
    local = CandidateReturn.model_json_schema(ref_template="#/$defs/{model}")
    _compare("CandidateReturn", local, published["$defs"])


def test_candidate_return_field_set_is_exact():
    """The wire shape is locked across both repos."""
    fields = set(CandidateReturn.model_fields)
    assert fields == {
        "job_id",
        "org_id",
        "skill_id",
        "candidate_text",
        "evidence",
        "spend_usd",
    }
