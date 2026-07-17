"""Layer 4 Governance Authority / Human-Authorised Transition / escalation /
Policy-as-Code (Proofing, Binding, Specification).

Cross-module dependencies: .identity (Evidence/Instance), .ledger (
HUMAN_AUTHORISED_TRANSITION, RE_ENABLEMENT, VerbaLedger), and .constructs
(PreNode/Invariant/TerminalState, for bundling into a Specification).
Confirmed acyclic: constructs.py has zero awareness of this module, ledger.py
never imports governance.py, and cluster.py already establishes the
identical "imports constructs + identity together" shape elsewhere in this
package.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, replace

from .constructs import Invariant, PreNode, TerminalState
from .identity import Evidence, Instance
from .ledger import HUMAN_AUTHORISED_TRANSITION, RE_ENABLEMENT, VerbaLedger

__all__ = [
    "GovernanceAuthority",
    "HumanAuthorisedTransition",
    "Proofing",
    "Binding",
    "Specification",
    "request_re_enablement",
    "HUMAN_AUTHORISED_TRANSITION",
    "RE_ENABLEMENT",
    "VerbaLedger",
]


@dataclass(frozen=True)
class GovernanceAuthority:
    """A defined role/body authorised to approve rule changes, exceptions,
    Human-Authorised Transitions, and Specification Updates. Must be named
    per escalation pathway, with secondary authorities and defined
    response times.
    """

    name: str
    escalation_contact: str
    secondary_authorities: tuple[str, ...] = ()
    response_time_sla_seconds: float | None = None


@dataclass(frozen=True)
class HumanAuthorisedTransition:
    """A transition requiring explicit, auditable human approval from the
    Governance Authority. The only sanctioned way out of a Terminal State
    -- no timeout, no default-approve, no automatic retry-after-N-seconds.

    Construct via authorise(), not the bare constructor, wherever possible
    -- authorise() is the one path that ties this record to a real Evidence
    object rather than an arbitrary evidence tuple.
    """

    authority: GovernanceAuthority
    authorised_by: str
    evidence: tuple[str, ...]
    timestamp: float = field(default_factory=time.time)
    authorisation_evidence_hash: str = ""

    def __post_init__(self) -> None:
        if not self.authorised_by.strip():
            raise ValueError("authorised_by must name a real, non-empty human approver.")
        if not self.authorisation_evidence_hash:
            blob = "|".join(self.evidence).encode("utf-8")
            object.__setattr__(self, "authorisation_evidence_hash", hashlib.sha256(blob).hexdigest())

    @classmethod
    def authorise(cls, authority: GovernanceAuthority, *, authorised_by: str, evidence: Evidence) -> "HumanAuthorisedTransition":
        """The one sanctioned way to produce a HumanAuthorisedTransition:
        from a real GovernanceAuthority, a named human approver, and a
        validated Evidence object (root_cause_analysis +
        specification_update_proposal, both already checked non-empty by
        Evidence.__post_init__).
        """
        return cls(
            authority=authority,
            authorised_by=authorised_by,
            evidence=(evidence.root_cause_analysis, evidence.specification_update_proposal),
        )


def request_re_enablement(
    instance: Instance,
    authority: GovernanceAuthority,
    *,
    authorised_by: str,
    evidence: Evidence,
) -> tuple[Instance, HumanAuthorisedTransition]:
    """The sanctioned path out of a Terminal State: produces a new,
    re-enabled Instance AND the HumanAuthorisedTransition record that
    authorises it, together, so a caller cannot obtain one without the
    other.

    Routes through HumanAuthorisedTransition.authorise() (real
    GovernanceAuthority + named human approver + validated Evidence) and
    Instance.re_enable() (mechanism). Both entries -- RE_ENABLEMENT for the
    new Instance, HUMAN_AUTHORISED_TRANSITION for the authorisation record
    -- are what a caller should then write to a VerbaLedger.

    This is a convenience/policy wrapper, not a language-enforced gate:
    Instance.re_enable() remains directly callable on its own (see its
    docstring) -- exactly the same non-enforcement shape as
    AutomationDeniedException's "cannot be silently caught," documented
    rather than silently assumed away.
    """
    transition = HumanAuthorisedTransition.authorise(authority, authorised_by=authorised_by, evidence=evidence)
    new_instance = instance.re_enable(evidence=evidence)
    return new_instance, transition


@dataclass(frozen=True)
class Proofing:
    """Automated verification that a claimed attribute matches an
    authoritative record, using stable anchors. Required before a new
    Specification version activates.

    A plain result type, not a check-runner: core doesn't know what an
    "authoritative record" is for any given domain, the same way it doesn't
    know how to compute a real Gamma estimate. The caller performs whatever
    domain-specific comparison makes sense and constructs
    Proofing(verified=<result>, verified_against="...").
    """

    verified: bool
    verified_against: str
    verified_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Binding:
    """Explicit link between a verified factor and a proven record /
    approved escalation path, required before proceeding. Prevents
    Specification activation without prior Proofing.

    __post_init__ enforces this structurally: a Binding cannot be
    constructed at all from an unverified Proofing, not just by convention.
    """

    proofing: Proofing
    escalation_path: str
    bound_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.proofing.verified:
            raise ValueError(
                "Cannot create a Binding from unverified Proofing -- Binding "
                "requires prior successful Proofing to have already occurred."
            )


@dataclass(frozen=True)
class Specification:
    """Policy-as-Code: a deterministic, versioned, machine-readable bundle
    of PreNodes/Invariants/TerminalStates. Per Design Principle P5, a new
    version requires Proofing and GOV approval before activation.

    approved_by is required at construction (Specification.approved_by:
    GovernanceAuthority, no default) -- a Specification with no named
    approving authority can't be represented at all. binding starts unset
    (a Specification can be drafted before it's proofed) and is attached
    via with_binding() once Proofing has succeeded; activate() then refuses
    to proceed without one.
    """

    name: str
    version: str
    approved_by: GovernanceAuthority
    pre_nodes: tuple[PreNode, ...] = ()
    invariants: tuple[Invariant, ...] = ()
    terminal_states: tuple[TerminalState, ...] = ()
    binding: Binding | None = None
    activated_at: float | None = None

    def with_binding(self, binding: Binding) -> "Specification":
        """Return a new Specification with `binding` attached. Since
        Binding.__post_init__ already refuses to exist without verified
        Proofing, a Specification can never reach activate() without a real,
        successful Proofing behind it.
        """
        return replace(self, binding=binding)

    def activate(self) -> "Specification":
        """Return a new, activated Specification. Raises ValueError if
        already active, or if no Binding has been attached yet -- this is
        the structural enforcement of P5 ("New versions require Proofing
        and GOV approval before activation"): approved_by is already
        required at construction, and binding transitively requires a
        verified Proofing.
        """
        if self.activated_at is not None:
            raise ValueError(f"Specification {self.name!r} v{self.version} is already active as of {self.activated_at}.")
        if self.binding is None:
            raise ValueError(
                f"Cannot activate Specification {self.name!r} v{self.version} without a "
                f"Binding (which itself requires prior successful Proofing)."
            )
        return replace(self, activated_at=time.time())
