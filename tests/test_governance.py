import pytest

from vsl_core.governance import (
    HUMAN_AUTHORISED_TRANSITION,
    RE_ENABLEMENT,
    Binding,
    GovernanceAuthority,
    HumanAuthorisedTransition,
    Proofing,
    Specification,
    VerbaLedger,
    request_re_enablement,
)
from vsl_core.identity import Evidence, Instance
from vsl_core.ledger import LedgerEntryType


def test_governance_reexports_ledger_symbols_matching_brief_import_line():
    # governance.py's import line is `from .ledger import
    # HUMAN_AUTHORISED_TRANSITION, RE_ENABLEMENT, VerbaLedger` -- confirm
    # these are importable directly from governance too.
    assert HUMAN_AUTHORISED_TRANSITION is LedgerEntryType.HUMAN_AUTHORISED_TRANSITION
    assert RE_ENABLEMENT is LedgerEntryType.RE_ENABLEMENT
    assert VerbaLedger is not None


def test_governance_authority_construction():
    authority = GovernanceAuthority(
        name="market_surveillance_governance_authority",
        escalation_contact="oncall@example.com",
        secondary_authorities=("backup@example.com",),
        response_time_sla_seconds=300.0,
    )
    assert authority.secondary_authorities == ("backup@example.com",)


def test_human_authorised_transition_authorise_computes_evidence_hash():
    authority = GovernanceAuthority(name="gov", escalation_contact="c")
    evidence = Evidence(root_cause_analysis="root cause doc", specification_update_proposal="spec update proposal")
    transition = HumanAuthorisedTransition.authorise(authority, authorised_by="jane.doe", evidence=evidence)
    assert transition.authorisation_evidence_hash
    assert len(transition.authorisation_evidence_hash) == 64  # sha256 hex digest


def test_human_authorised_transition_hash_is_deterministic_for_same_evidence():
    authority = GovernanceAuthority(name="gov", escalation_contact="c")
    evidence = Evidence(root_cause_analysis="x", specification_update_proposal="y")
    t1 = HumanAuthorisedTransition.authorise(authority, authorised_by="a", evidence=evidence)
    t2 = HumanAuthorisedTransition.authorise(authority, authorised_by="a", evidence=evidence)
    assert t1.authorisation_evidence_hash == t2.authorisation_evidence_hash


def test_human_authorised_transition_requires_named_approver():
    authority = GovernanceAuthority(name="gov", escalation_contact="c")
    evidence = Evidence(root_cause_analysis="x", specification_update_proposal="y")
    with pytest.raises(ValueError):
        HumanAuthorisedTransition.authorise(authority, authorised_by="", evidence=evidence)


def test_request_re_enablement_returns_instance_and_authorisation_together():
    authority = GovernanceAuthority(name="gov", escalation_contact="c")
    original = Instance.new()
    evidence = Evidence(
        root_cause_analysis="alarm software infinite loop",
        specification_update_proposal="add heartbeat invariant",
    )
    re_enabled, transition = request_re_enablement(
        original,
        authority,
        authorised_by="jane.doe",
        evidence=evidence,
    )
    assert re_enabled.instance_id != original.instance_id
    assert re_enabled.predecessor_instance_id == original.instance_id
    assert isinstance(transition, HumanAuthorisedTransition)
    assert transition.authority is authority
    assert transition.authorised_by == "jane.doe"
    assert transition.evidence == (evidence.root_cause_analysis, evidence.specification_update_proposal)


def test_request_re_enablement_requires_authorised_by():
    authority = GovernanceAuthority(name="gov", escalation_contact="c")
    original = Instance.new()
    evidence = Evidence(root_cause_analysis="x", specification_update_proposal="y")
    with pytest.raises(ValueError):
        request_re_enablement(original, authority, authorised_by="", evidence=evidence)


def test_proofing_construction():
    proofing = Proofing(verified=True, verified_against="signed spec hash matches registry")
    assert proofing.verified is True
    assert proofing.verified_against == "signed spec hash matches registry"


def test_binding_rejects_unverified_proofing():
    unverified = Proofing(verified=False, verified_against="hash mismatch")
    with pytest.raises(ValueError):
        Binding(proofing=unverified, escalation_path="gov-escalation")


def test_binding_accepts_verified_proofing():
    verified = Proofing(verified=True, verified_against="hash matches")
    binding = Binding(proofing=verified, escalation_path="gov-escalation")
    assert binding.proofing is verified


def test_specification_cannot_activate_without_binding():
    authority = GovernanceAuthority(name="gov", escalation_contact="c")
    spec = Specification(name="factual-response-policy", version="1.0.0", approved_by=authority)
    with pytest.raises(ValueError):
        spec.activate()


def test_specification_with_binding_then_activate_succeeds():
    authority = GovernanceAuthority(name="gov", escalation_contact="c")
    spec = Specification(name="factual-response-policy", version="1.0.0", approved_by=authority)
    proofing = Proofing(verified=True, verified_against="hash matches")
    binding = Binding(proofing=proofing, escalation_path="gov-escalation")

    bound = spec.with_binding(binding)
    assert bound.binding is binding
    assert bound.activated_at is None

    activated = bound.activate()
    assert activated.activated_at is not None
    # with_binding/activate return new instances -- originals are untouched.
    assert spec.binding is None
    assert bound.activated_at is None


def test_specification_cannot_activate_twice():
    authority = GovernanceAuthority(name="gov", escalation_contact="c")
    spec = Specification(name="factual-response-policy", version="1.0.0", approved_by=authority)
    proofing = Proofing(verified=True, verified_against="hash matches")
    binding = Binding(proofing=proofing, escalation_path="gov-escalation")
    activated = spec.with_binding(binding).activate()

    with pytest.raises(ValueError):
        activated.activate()
