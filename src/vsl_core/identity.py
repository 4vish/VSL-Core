"""Layer 4 identity/audit-scoping vocabulary: Identity Key, Cluster Key,
Instance, Re-Enablement.

Stdlib only.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class IdentityKey:
    """A stable identifier scoping counters, limits, and process Instances.

    Frozen and hashable so it can key dicts (e.g. Ledger partitioning) or
    be used directly as a set/mapping member.
    """

    value: str

    @classmethod
    def generate(cls, prefix: str = "vsl") -> "IdentityKey":
        return cls(value=f"{prefix}-{uuid.uuid4()}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ClusterKey:
    """The composite Identity Key shared across all constituent systems of
    a Cluster.

    Deliberately NOT a subclass of IdentityKey. A Cluster's governance
    sufficiency is not the same question as any one constituent's -- the
    Flash Crash case study is precisely the failure mode where individual
    Gamma > 1 was insufficient at the Cluster level. Making ClusterKey a
    distinct type (rather than an IdentityKey subtype) means a ClusterKey
    can never be silently accepted somewhere only a single-system
    IdentityKey should be valid.
    """

    value: str
    constituent_keys: tuple[IdentityKey, ...]

    @classmethod
    def from_constituents(cls, constituent_keys: tuple[IdentityKey, ...]) -> "ClusterKey":
        """Derive a stable composite value from a deterministic hash of
        the sorted constituent key values, so the same set of constituents
        always produces the same ClusterKey.value regardless of the order
        they were supplied in.
        """
        sorted_values = sorted(k.value for k in constituent_keys)
        digest = hashlib.sha256("|".join(sorted_values).encode("utf-8")).hexdigest()
        return cls(value=f"cluster-{digest[:16]}", constituent_keys=tuple(constituent_keys))


@dataclass(frozen=True)
class Evidence:
    """The evidence a Re-Enablement request must carry: a root-cause
    analysis and a specification-update proposal, per the spec's
    Re-Enablement requirements.

    A structured type rather than two loose strings so validation (both
    fields non-empty) lives in exactly one place and callers can't
    construct "evidence" that's silently missing a field.
    """

    root_cause_analysis: str
    specification_update_proposal: str

    def __post_init__(self) -> None:
        if not self.root_cause_analysis.strip():
            raise ValueError("root_cause_analysis must be a non-empty evidence string.")
        if not self.specification_update_proposal.strip():
            raise ValueError("specification_update_proposal must be a non-empty evidence string.")


@dataclass(frozen=True)
class Instance:
    """A single execution of a process with its own identifier, counters,
    limits, and history -- scoped by Identity Key.

    Instances are immutable; Re-Enablement never mutates an existing
    Instance, it produces a new one (see re_enable()).
    """

    instance_id: str
    identity_key: IdentityKey
    created_at: float = field(default_factory=time.time)
    predecessor_instance_id: str | None = None
    generation: int = 0

    @classmethod
    def new(cls, identity_key: IdentityKey | None = None) -> "Instance":
        """Mint a fresh Instance. If no IdentityKey is given, a new one is
        generated -- this is also the path Re-Enablement uses internally,
        since Re-Enablement "always creates a new Instance with a new
        Identity Key" per the spec.
        """
        return cls(
            instance_id=str(uuid.uuid4()),
            identity_key=identity_key or IdentityKey.generate(),
        )

    def re_enable(self, *, evidence: Evidence) -> "Instance":
        """Restore eligibility after a Terminal State.

        Always returns a brand-new Instance with a new IdentityKey; never
        mutates self, and the old Instance/IdentityKey are never reused --
        Re-Enablement is a reset of eligibility, not of the audit trail.

        `evidence` is a required Evidence object, not two optional loose
        strings: the spec states Re-Enablement "requires root-cause
        analysis and a specification-update proposal as evidence," and
        Evidence.__post_init__ enforces both fields are non-empty.

        Note on enforcement: this is the mechanism, not the sanctioned
        policy path. It intentionally has no knowledge of GovernanceAuthority
        or HumanAuthorisedTransition (identity.py stays dependency-free, per
        the module's build-order position) and is still directly callable
        by anyone with an Instance and an Evidence object -- exactly like
        AutomationDeniedException's "cannot be silently caught" is a
        convention rather than a language-enforced guarantee, this method
        cannot itself prevent a caller from bypassing
        governance.request_re_enablement(). Callers who need the audited,
        authority-attributed path should go through
        governance.request_re_enablement(), which pairs this call with a
        HumanAuthorisedTransition record.
        """
        return Instance(
            instance_id=str(uuid.uuid4()),
            identity_key=IdentityKey.generate(),
            predecessor_instance_id=self.instance_id,
            generation=self.generation + 1,
        )
