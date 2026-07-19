import asyncio
import uuid

import pytest

from vsl_core.constructs import (
    AllowedState,
    Fallback,
    InadmissibleState,
    Invariant,
    PreNode,
    TerminalState,
    register_invariant,
    registered_invariants,
)
from vsl_core.metrics import AssuranceBasis, AssuranceLevel, F2Modification, GammaEstimate

_HIGH_ASSURANCE_BASIS = AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.FULL)


async def _always_true(_candidate_input) -> bool:
    return True


async def _stub_monitor(_candidate_input) -> GammaEstimate:
    return GammaEstimate(gamma_hat=2.0)


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def test_allowed_state_construction():
    state = AllowedState(
        name="factual_response",
        description="Model output is factually supported",
        assurance_basis=_HIGH_ASSURANCE_BASIS,
        measurement="D_KL(P_t || P_A) < 0.15 nats",
        validity_conditions=("token_probability_factual > token_probability_hallucination",),
    )
    assert state.assurance_level == AssuranceLevel.HIGH
    assert len(state.validity_conditions) == 1


def test_allowed_state_assurance_level_derived_not_stored_directly():
    # assurance_level can't be set directly -- it's a read-only property
    # derived from assurance_basis, not a constructor argument.
    with pytest.raises(TypeError):
        AllowedState(
            name="x",
            description="d",
            assurance_level=AssuranceLevel.HIGH,  # type: ignore[call-arg]
            measurement="m",
        )


def test_inadmissible_state_construction():
    state = InadmissibleState(
        name="hallucination_attractor",
        description="Model converges to factually unsupported output",
        signature="P_t(x_hallucination) > P_t(x_factual) for 3 consecutive steps",
    )
    assert state.energy_gap_proxy is None


def test_fallback_defaults_match_spec():
    fallback = Fallback()
    assert fallback.on_failure == "INCREASE_DELTA"
    assert fallback.delta_factor == 1.5
    assert fallback.max_retries == 3
    assert fallback.on_max_retries == "AUTOMATION_DENIED"


def test_invariant_cannot_be_bypassed_defaults_true():
    invariant = Invariant(name=_unique_name("inv"), description="d", rule=_always_true, assurance_basis=_HIGH_ASSURANCE_BASIS)
    assert invariant.cannot_be_bypassed is True
    assert invariant.scope == "ALL_STATES"


def test_invariant_requires_assurance_basis_no_default():
    # Same discipline as PreNode: no default HIGH, must be justified explicitly.
    with pytest.raises(TypeError):
        Invariant(name=_unique_name("inv"), description="d", rule=_always_true)  # type: ignore[call-arg]


def test_invariant_assurance_level_matches_pre_node_derivation():
    invariant = Invariant(name=_unique_name("inv"), description="d", rule=_always_true, assurance_basis=_HIGH_ASSURANCE_BASIS)
    assert invariant.assurance_level == AssuranceLevel.HIGH


def test_invariant_on_violation_defaults_to_none():
    invariant = Invariant(name=_unique_name("inv"), description="d", rule=_always_true, assurance_basis=_HIGH_ASSURANCE_BASIS)
    assert invariant.on_violation is None


def test_invariant_on_violation_round_trips_when_set():
    terminal = TerminalState(name="governance_failure_terminal", description="d")
    invariant = Invariant(
        name=_unique_name("inv"),
        description="d",
        rule=_always_true,
        assurance_basis=_HIGH_ASSURANCE_BASIS,
        on_violation=terminal,
    )
    assert invariant.on_violation is terminal
    assert invariant.on_violation.name == "governance_failure_terminal"


def test_terminal_state_requires_human_authorised_transition_by_default():
    terminal = TerminalState(name="t", description="d", entry_conditions=("gamma < 0.8",))
    assert terminal.requires_human_authorised_transition is True


def test_pre_node_construction_with_defaults():
    node = PreNode(name="gate", description="d", monitor=_stub_monitor, assurance_basis=_HIGH_ASSURANCE_BASIS)
    assert node.gamma_threshold == 1.1
    assert node.assurance_level == AssuranceLevel.HIGH
    assert node.fallback.max_retries == 3


def test_pre_node_requires_assurance_basis_no_default():
    # assurance_basis has no default -- a PreNode can no longer be
    # constructed without justifying its assurance level via real F1/F2
    # facts. This replaces the old behavior of silently defaulting to HIGH.
    with pytest.raises(TypeError):
        PreNode(name="gate", description="d", monitor=_stub_monitor)  # type: ignore[call-arg]


def test_pre_node_rejects_negative_max_retries():
    with pytest.raises(ValueError):
        PreNode(
            name="gate",
            description="d",
            monitor=_stub_monitor,
            assurance_basis=_HIGH_ASSURANCE_BASIS,
            fallback=Fallback(max_retries=-1),
        )


def test_pre_node_rejects_non_positive_delta_factor():
    with pytest.raises(ValueError):
        PreNode(
            name="gate",
            description="d",
            monitor=_stub_monitor,
            assurance_basis=_HIGH_ASSURANCE_BASIS,
            fallback=Fallback(delta_factor=0),
        )


def test_register_invariant_and_lookup():
    name = _unique_name("registered")
    invariant = Invariant(name=name, description="d", rule=_always_true, assurance_basis=_HIGH_ASSURANCE_BASIS)
    register_invariant(invariant)
    assert invariant in registered_invariants()


def test_register_invariant_rejects_duplicate_name():
    name = _unique_name("dup")
    invariant_a = Invariant(name=name, description="a", rule=_always_true, assurance_basis=_HIGH_ASSURANCE_BASIS)
    invariant_b = Invariant(name=name, description="b", rule=_always_true, assurance_basis=_HIGH_ASSURANCE_BASIS)
    register_invariant(invariant_a)
    with pytest.raises(ValueError):
        register_invariant(invariant_b)


def test_drift_monitor_protocol_call_shape():
    # No pytest-asyncio dependency in this zero-third-party-dep package --
    # drive the coroutine directly via asyncio.run().
    estimate = asyncio.run(_stub_monitor("some input"))
    assert isinstance(estimate, GammaEstimate)
    assert estimate.sufficient()
