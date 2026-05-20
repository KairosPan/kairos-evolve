"""Schema drift detector for routing contracts.

If this fails:
  - if our local Pydantic models drifted, fix them
  - if kairos main bumped routing.json, run scripts/regen-contracts.sh
    and confirm our models still match
"""

from __future__ import annotations

import json
from pathlib import Path

from kairos_evolve.core.routing_contracts import RoutingEvent, RoutingPolicy

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "contracts" / "jsonschemas" / "routing.json"


def _compare(name: str, local_schema: dict, published_defs: dict) -> None:
    pub = published_defs[name]
    for key in ("type", "properties", "required"):
        assert pub.get(key) == local_schema.get(key), (
            f"routing.json[{name}][{key}] != local {name}.model_json_schema()[{key}] — "
            f"published={pub.get(key)!r} local={local_schema.get(key)!r}"
        )


def test_routing_event_matches_published_schema():
    published = json.loads(SCHEMA_FILE.read_text())
    local = RoutingEvent.model_json_schema(ref_template="#/$defs/{model}")
    _compare("RoutingEvent", local, published["$defs"])


def test_routing_policy_matches_published_schema():
    published = json.loads(SCHEMA_FILE.read_text())
    local = RoutingPolicy.model_json_schema(ref_template="#/$defs/{model}")
    _compare("RoutingPolicy", local, published["$defs"])
