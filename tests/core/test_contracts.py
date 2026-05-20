"""contracts module re-exports — Phase 1 + Phase 2A surface."""


def test_contracts_root_reexports_envelope():
    from kairos_evolve.core import contracts

    expected = {
        "EnvelopeV1",
        "sign_envelope",
        "verify_envelope",
        "canonical_json",
        "merkle_root",
        "EnvelopeVerifyError",
        "DEFAULT_TTL",
        "FUTURE_SKEW",
        "RoutingEvent",
        "RoutingPolicy",
    }
    actual = set(contracts.__all__)
    missing = expected - actual
    assert not missing, f"missing re-exports: {missing}"


def test_contracts_envelope_v1_is_pydantic():
    from kairos_evolve.core.contracts import EnvelopeV1
    from pydantic import BaseModel

    assert issubclass(EnvelopeV1, BaseModel)
