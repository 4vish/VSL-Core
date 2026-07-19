"""Layer 2 executable VSL constructs: AllowedState, InadmissibleState,
Fallback, Invariant, PreNode, TerminalState.

This module must NEVER import any agent-framework package (`agents`,
`langgraph`, `langchain`, or similar) or any model-provider SDK (`openai`,
`anthropic`, or similar). It is the most likely module to accidentally
regain such a coupling later if someone adds a "convenience" method that
assumes a particular framework's call shape -- don't. Any adapter-specific
compile step (turning a PreNode/Invariant into a framework's own guardrail
type) belongs in a separate `vsl-<framework>` package, never here.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from .metrics import AssuranceBasis, AssuranceLevel, GammaEstimate, ROBUST_GAMMA_DEFAULT_THRESHOLD


@dataclass(frozen=True)
class AllowedState:
    """A state meeting all required prerequisites, Constraints, rules, and
    validity conditions.

    assurance_level is not set directly -- it's required to be derived from
    a real AssuranceBasis (F1/F2 facts), so a caller can't claim HIGH
    without stating what makes it HIGH.
    """

    name: str
    description: str
    assurance_basis: AssuranceBasis
    measurement: str
    validity_conditions: tuple[str, ...] = ()

    @property
    def assurance_level(self) -> AssuranceLevel:
        return self.assurance_basis.derived_level


@dataclass(frozen=True)
class InadmissibleState:
    """A state that must not occur -- corresponds to a Drift Node."""

    name: str
    description: str
    signature: str
    energy_gap_proxy: str | None = None


@dataclass(frozen=True)
class Fallback:
    """A deterministic recovery/termination action when a State is invalid
    or a Pre-Node cannot be satisfied.
    """

    on_failure: str = "INCREASE_DELTA"
    delta_factor: float = 1.5
    max_retries: int = 3
    on_max_retries: str = "AUTOMATION_DENIED"


class DriftMonitor(Protocol):
    """Framework-agnostic monitor signature. An adapter's compile step is
    responsible for constructing whatever `candidate_input` means in its
    own framework's terms before calling this.
    """

    async def __call__(self, candidate_input: Any) -> GammaEstimate: ...


class FormationLayerIntervention(Protocol):
    """Framework-agnostic formation-layer intervention signature."""

    async def __call__(self, delta_factor: float) -> bool: ...


@dataclass(frozen=True)
class Invariant:
    """A persistent Constraint that cannot be bypassed. Violation triggers
    IMMEDIATE_TERMINAL_STATE per the spec, not an ordinary Fallback.

    assurance_basis is required, same discipline as AllowedState/PreNode:
    the source spec's own INVARIANT pseudocode example carries an
    ASSURANCE_LEVEL field alongside PRE_NODE and ALLOWED_STATE's (only
    INADMISSIBLE_STATE's example lacks one) -- Invariant was missed when
    AssuranceBasis was first added to close the F1/F2 structural-
    enforcement gap, caught later via a compliance-mapping cross-check
    against the spec's own pseudocode. assurance_level is derived from it,
    same pattern as AllowedState/PreNode: not settable directly.

    on_violation names which TerminalState that immediate transition is
    into. It's optional (an Invariant can exist before its Terminal State
    is decided), but when set, an adapter catching InvariantViolation for
    this Invariant should treat entry into on_violation as automatic --
    that's what "violation triggers immediate Terminal State" means.
    """

    name: str
    description: str
    rule: Callable[[Any], Awaitable[bool]]
    assurance_basis: AssuranceBasis
    scope: str = "ALL_STATES"
    cannot_be_bypassed: bool = True
    on_violation: TerminalState | None = None

    @property
    def assurance_level(self) -> AssuranceLevel:
        return self.assurance_basis.derived_level


@dataclass(frozen=True)
class TerminalState:
    """A state from which no further automated transitions are permitted."""

    name: str
    description: str
    entry_conditions: tuple[str, ...] = ()
    requires_human_authorised_transition: bool = True


@dataclass(frozen=True)
class PreNode:
    """A mandatory prerequisite that must be satisfied before transitioning
    into a target State -- the central VERBA construct. Every Pre-Node is
    an Eligibility Condition: a State transition without a satisfied
    Pre-Node is, by definition, Drift.
    """

    name: str
    description: str
    monitor: DriftMonitor
    assurance_basis: AssuranceBasis
    gamma_threshold: float = ROBUST_GAMMA_DEFAULT_THRESHOLD
    intervention: FormationLayerIntervention | None = None
    fallback: Fallback = field(default_factory=Fallback)

    @property
    def assurance_level(self) -> AssuranceLevel:
        return self.assurance_basis.derived_level

    def __post_init__(self) -> None:
        if self.fallback.max_retries < 0:
            raise ValueError("Fallback.max_retries must be >= 0.")
        if self.fallback.delta_factor <= 0:
            raise ValueError("Fallback.delta_factor must be > 0.")


_invariant_registry: list[Invariant] = []
_invariant_registry_lock = threading.Lock()


def register_invariant(invariant: Invariant) -> None:
    """Register an Invariant in the module-level registry.

    Raises ValueError on a duplicate name rather than silently overwriting
    -- silently replacing a governance Invariant is exactly the kind of
    silent failure Design Principle P3 ("explicit failure conditions")
    forbids.
    """
    with _invariant_registry_lock:
        if any(existing.name == invariant.name for existing in _invariant_registry):
            raise ValueError(f"An Invariant named {invariant.name!r} is already registered.")
        _invariant_registry.append(invariant)


def registered_invariants() -> tuple[Invariant, ...]:
    with _invariant_registry_lock:
        return tuple(_invariant_registry)
