import pytest

from vsl_core.identity import ClusterKey, Evidence, IdentityKey, Instance


def test_identity_key_generate_is_unique_and_hashable():
    a = IdentityKey.generate()
    b = IdentityKey.generate()
    assert a != b
    assert hash(a) != hash(b) or a.value != b.value
    # usable as dict key
    d = {a: "first"}
    assert d[a] == "first"


def test_identity_key_generate_uses_prefix():
    key = IdentityKey.generate(prefix="myapp")
    assert key.value.startswith("myapp-")


def test_cluster_key_is_not_an_identity_key_subclass():
    a = IdentityKey.generate()
    b = IdentityKey.generate()
    cluster_key = ClusterKey.from_constituents((a, b))
    assert not isinstance(cluster_key, IdentityKey)


def test_cluster_key_deterministic_regardless_of_constituent_order():
    a = IdentityKey.generate()
    b = IdentityKey.generate()
    key1 = ClusterKey.from_constituents((a, b))
    key2 = ClusterKey.from_constituents((b, a))
    assert key1.value == key2.value


def test_cluster_key_differs_for_different_constituents():
    a = IdentityKey.generate()
    b = IdentityKey.generate()
    c = IdentityKey.generate()
    key_ab = ClusterKey.from_constituents((a, b))
    key_ac = ClusterKey.from_constituents((a, c))
    assert key_ab.value != key_ac.value


def test_instance_new_mints_fresh_identity_key():
    instance = Instance.new()
    assert instance.instance_id
    assert instance.identity_key is not None
    assert instance.predecessor_instance_id is None
    assert instance.generation == 0


def test_instance_new_accepts_explicit_identity_key():
    key = IdentityKey.generate()
    instance = Instance.new(identity_key=key)
    assert instance.identity_key == key


def test_evidence_rejects_empty_fields():
    with pytest.raises(ValueError):
        Evidence(root_cause_analysis="", specification_update_proposal="x")
    with pytest.raises(ValueError):
        Evidence(root_cause_analysis="x", specification_update_proposal="   ")


def test_evidence_accepts_valid_fields():
    evidence = Evidence(root_cause_analysis="alarm software infinite loop", specification_update_proposal="add heartbeat invariant")
    assert evidence.root_cause_analysis == "alarm software infinite loop"


def test_re_enable_creates_new_instance_with_new_identity_key():
    original = Instance.new()
    evidence = Evidence(
        root_cause_analysis="alarm software infinite loop",
        specification_update_proposal="add heartbeat invariant",
    )
    re_enabled = original._re_enable(evidence=evidence)
    assert re_enabled.instance_id != original.instance_id
    assert re_enabled.identity_key != original.identity_key
    assert re_enabled.predecessor_instance_id == original.instance_id
    assert re_enabled.generation == original.generation + 1


def test_re_enable_does_not_mutate_original_instance():
    original = Instance.new()
    original_id = original.instance_id
    original_key = original.identity_key
    evidence = Evidence(root_cause_analysis="root cause", specification_update_proposal="spec update")
    original._re_enable(evidence=evidence)
    assert original.instance_id == original_id
    assert original.identity_key == original_key


def test_re_enable_requires_a_real_evidence_object_not_loose_strings():
    original = Instance.new()
    with pytest.raises(TypeError):
        original._re_enable(root_cause_analysis="a", specification_update_proposal="b")  # type: ignore[call-arg]


def test_re_enable_chain_increments_generation_each_time():
    gen0 = Instance.new()
    gen1 = gen0._re_enable(evidence=Evidence(root_cause_analysis="a", specification_update_proposal="b"))
    gen2 = gen1._re_enable(evidence=Evidence(root_cause_analysis="c", specification_update_proposal="d"))
    assert gen1.generation == 1
    assert gen2.generation == 2
    assert gen2.predecessor_instance_id == gen1.instance_id


def test_re_enable_has_no_public_name_anymore():
    # Locks in the rename: the bare mechanism is _re_enable (leading
    # underscore, signalling "not the sanctioned entry point"). A public
    # re_enable() was the exact bypass risk an external review flagged --
    # this test fails loudly if that public name ever comes back.
    assert not hasattr(Instance, "re_enable")
    assert hasattr(Instance, "_re_enable")
