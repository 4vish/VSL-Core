"""Layer 0/2 Cluster construct: a higher-order identity formed by
coordination of multiple Nodes, generating governance requirements absent
at the Node level.

Canonical failure mode (Flash Crash, 2010): individual Gamma > 1, Cluster
Gamma = 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .constructs import Fallback, FormationLayerIntervention, Invariant
from .identity import ClusterKey, IdentityKey


@dataclass(frozen=True)
class ClusterInadmissibleState:
    """A Cluster-level Inadmissible State.

    `note` is a first-class field, not a comment: the spec's own Cluster
    example carries a warning sentence ("Individual system Gamma > 1 is
    insufficient. Cluster-level governance is required.") that is the
    single most important sentence in the whole construct and should be
    programmatically retrievable by anything built on top of this package.
    """

    name: str
    description: str
    signature: str
    note: str = ""


@dataclass(frozen=True)
class ClusterPreNode:
    """A Cluster-level Pre-Node -- fires on aggregate/cross-constituent
    signatures that no single constituent's own Pre-Node would catch.
    """

    name: str
    trigger_description: str
    authority: str
    intervention: FormationLayerIntervention | None = None
    fallback: Fallback = field(default_factory=Fallback)


@dataclass(frozen=True)
class Cluster:
    """A higher-order identity formed by coordination of multiple Nodes.

    __post_init__ validates that every declared constituent is actually
    covered by the given ClusterKey's constituent_keys -- this encodes
    Design Principle P4 (recursive composition) as a runtime-checked
    invariant instead of a hopeful convention, and directly guards against
    the Flash-Crash-shaped bug where a Cluster's governance silently
    doesn't actually cover one of its constituents.
    """

    name: str
    cluster_key: ClusterKey
    constituents: tuple[IdentityKey, ...]
    cluster_inadmissible_states: tuple[ClusterInadmissibleState, ...] = ()
    cluster_pre_nodes: tuple[ClusterPreNode, ...] = ()
    invariants: tuple[Invariant, ...] = ()

    def __post_init__(self) -> None:
        covered = set(self.cluster_key.constituent_keys)
        missing = [c for c in self.constituents if c not in covered]
        if missing:
            raise ValueError(
                f"Cluster {self.name!r} declares constituents not covered by "
                f"its own cluster_key: {missing}. A Cluster's ClusterKey must "
                f"be derived from (at least) all of its declared constituents."
            )

    def add_constituent(self, identity_key: IdentityKey) -> "Cluster":
        """Return a new Cluster with `identity_key` added and cluster_key
        recomputed. Immutable-by-convention, consistent with
        vsl_core.identity.Instance.re_enable.
        """
        new_constituents = tuple(self.constituents) + (identity_key,)
        new_cluster_key = ClusterKey.from_constituents(new_constituents)
        return Cluster(
            name=self.name,
            cluster_key=new_cluster_key,
            constituents=new_constituents,
            cluster_inadmissible_states=self.cluster_inadmissible_states,
            cluster_pre_nodes=self.cluster_pre_nodes,
            invariants=self.invariants,
        )
