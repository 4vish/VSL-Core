import pytest

from vsl_core.cluster import Cluster, ClusterInadmissibleState, ClusterPreNode
from vsl_core.identity import ClusterKey, IdentityKey


def test_cluster_construction_with_matching_key():
    a = IdentityKey.generate()
    b = IdentityKey.generate()
    key = ClusterKey.from_constituents((a, b))
    cluster = Cluster(name="trading_system_network", cluster_key=key, constituents=(a, b))
    assert cluster.constituents == (a, b)


def test_cluster_rejects_constituent_not_covered_by_cluster_key():
    a = IdentityKey.generate()
    b = IdentityKey.generate()
    c = IdentityKey.generate()
    key = ClusterKey.from_constituents((a, b))  # does not cover c
    with pytest.raises(ValueError):
        Cluster(name="bad_cluster", cluster_key=key, constituents=(a, b, c))


def test_add_constituent_returns_new_cluster_with_recomputed_key():
    a = IdentityKey.generate()
    b = IdentityKey.generate()
    c = IdentityKey.generate()
    key_ab = ClusterKey.from_constituents((a, b))
    cluster = Cluster(name="net", cluster_key=key_ab, constituents=(a, b))

    expanded = cluster.add_constituent(c)

    assert expanded is not cluster
    assert c in expanded.constituents
    assert expanded.cluster_key.value != cluster.cluster_key.value
    # original untouched
    assert c not in cluster.constituents


def test_cluster_inadmissible_state_carries_note_as_first_class_field():
    state = ClusterInadmissibleState(
        name="cascade_failure",
        description="Combined tendency toward cascade",
        signature="aggregate_order_flow_KL > cluster_threshold",
        note="Individual system Gamma > 1 is insufficient. Cluster-level governance is required.",
    )
    assert "insufficient" in state.note


def test_cluster_pre_node_construction():
    pre_node = ClusterPreNode(
        name="cascade_circuit_breaker",
        trigger_description="cluster_gamma < 1.2 OR high_frequency_withdrawal_detected",
        authority="market_surveillance_governance_authority",
    )
    assert pre_node.fallback.max_retries == 3
