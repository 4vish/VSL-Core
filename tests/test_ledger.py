import time

import pytest

from vsl_core.exceptions import LedgerIntegrityError
from vsl_core.ledger import (
    DRIFT_DETECTED_KEY,
    HUMAN_AUTHORISED_TRANSITION,
    RE_ENABLEMENT,
    VERIFICATION_RESULT_KEY,
    GENESIS_HASH,
    InMemoryLedgerStore,
    JsonlLedgerStore,
    LedgerEntryType,
    VerbaLedger,
    VerificationResult,
)


def test_bare_module_constants_match_enum_members():
    assert HUMAN_AUTHORISED_TRANSITION is LedgerEntryType.HUMAN_AUTHORISED_TRANSITION
    assert RE_ENABLEMENT is LedgerEntryType.RE_ENABLEMENT


def test_seven_entry_types_exist():
    assert {e.value for e in LedgerEntryType} == {
        "MONITOR",
        "PRE_NODE",
        "VERIFICATION",
        "TERMINAL",
        "SPECIFICATION_UPDATE",
        "HUMAN_AUTHORISED_TRANSITION",
        "RE_ENABLEMENT",
    }


def test_in_memory_write_chains_entries_and_verifies():
    ledger = VerbaLedger(InMemoryLedgerStore())
    e1 = ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"drift_detected": False})
    e2 = ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"drift_detected": False})
    assert e1.sequence == 0
    assert e2.sequence == 1
    assert e1.prev_hash == GENESIS_HASH
    assert e2.prev_hash == e1.entry_hash
    assert ledger.verify_integrity() is True


def test_empty_ledger_verifies_true():
    ledger = VerbaLedger()
    assert ledger.verify_integrity() is True


def test_jsonl_store_round_trips_and_verifies(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"drift_detected": False})
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.VERIFICATION, identity_key="sys-1", payload={"result": "SUFFICIENT"})

    # Re-instantiate fresh, over the same file, proving persistence not an in-memory artifact.
    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is True
    assert len(list(reopened.store.all_entries())) == 3


def test_tamper_detection_flips_one_byte_in_payload(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"marker": "TAMPER_TARGET_VALUE"})
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.VERIFICATION, identity_key="sys-1", payload={"result": "SUFFICIENT"})
    ledger.write(LedgerEntryType.TERMINAL, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.HUMAN_AUTHORISED_TRANSITION, identity_key="sys-1", payload={})

    # Step 0: untouched chain verifies True -- this alone is not the test.
    untouched = VerbaLedger(JsonlLedgerStore(path))
    assert untouched.verify_integrity() is True

    # Flip exactly one byte inside a string value -- same length, still valid JSON.
    raw = path.read_bytes()
    assert b"TAMPER_TARGET_VALUE" in raw
    tampered = raw.replace(b"TAMPER_TARGET_VALUE", b"TAMPER_TARGET_VALUX", 1)
    assert tampered != raw
    assert len(tampered) == len(raw)
    path.write_bytes(tampered)

    # Fresh instantiation over the same (now-tampered) file.
    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is False

    # Diagnosability: audit() must still run without raising on a tampered chain.
    report = reopened.audit()
    assert report is not None


def test_tamper_detection_catches_prev_hash_mutation(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    # Mutate the prev_hash field's value in the second line only, keeping JSON valid
    # (a hex hash string of the same length, guaranteed different from the real one).
    import json

    second = json.loads(lines[1])
    real_prev_hash = second["prev_hash"]
    mutated_prev_hash = ("f" if real_prev_hash[0] != "f" else "0") + real_prev_hash[1:]
    second["prev_hash"] = mutated_prev_hash
    lines[1] = json.dumps(second, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is False


def test_write_refuses_to_extend_a_chain_with_a_corrupted_last_entry(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"marker": "TAMPER_TARGET_VALUE"})

    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"TAMPER_TARGET_VALUE", b"TAMPER_TARGET_VALUX", 1))

    corrupted = VerbaLedger(JsonlLedgerStore(path))
    with pytest.raises(LedgerIntegrityError):
        corrupted.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})


def test_audit_all_checks_pass_on_a_well_formed_chain():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", instance_id="inst-1", payload={"drift_detected": True})
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", instance_id="inst-1", payload={})
    ledger.write(LedgerEntryType.VERIFICATION, identity_key="sys-1", instance_id="inst-1", payload={"result": "INSUFFICIENT"})
    ledger.write(LedgerEntryType.SPECIFICATION_UPDATE, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.TERMINAL, identity_key="sys-1", payload={})
    ledger.write(LedgerEntryType.HUMAN_AUTHORISED_TRANSITION, identity_key="sys-1", payload={})

    report = ledger.audit()
    assert report.all_passed is True
    assert report.checks_failed == ()


def test_audit_catches_drift_flagged_monitor_with_no_pre_node():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", instance_id="inst-1", payload={"drift_detected": True})
    # No PRE_NODE follows.
    report = ledger.audit()
    assert "drift_flagged_monitor_has_pre_node" in report.checks_failed
    assert report.violations["drift_flagged_monitor_has_pre_node"]


def test_audit_catches_pre_node_with_no_verification():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", instance_id="inst-1", payload={})
    report = ledger.audit()
    assert "pre_node_has_verification" in report.checks_failed


def test_audit_catches_insufficient_verification_with_no_spec_update():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.VERIFICATION, identity_key="sys-1", payload={"result": "INSUFFICIENT"})
    report = ledger.audit()
    assert "insufficient_verification_has_specification_update" in report.checks_failed


def test_audit_catches_terminal_with_no_human_authorised_transition():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.TERMINAL, identity_key="sys-1", payload={})
    report = ledger.audit()
    assert "terminal_has_human_authorised_transition" in report.checks_failed


def test_audit_monitoring_gap_check_requires_explicit_parameter():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})
    report_without_param = ledger.audit()
    assert "no_monitoring_gaps" not in report_without_param.checks_failed


def test_issue_certificate_none_on_failed_audit():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.TERMINAL, identity_key="sys-1", payload={})
    assert ledger.issue_certificate() is None


def test_issue_certificate_present_on_passed_audit_and_carries_disclaimer():
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"drift_detected": False})
    cert = ledger.issue_certificate()
    assert cert is not None
    assert cert.audit_report.all_passed is True
    assert "does not guarantee" in cert.NOTE
    assert "does not guarantee" in str(cert)
    assert cert.certificate_hash


def test_write_monitor_uses_the_canonical_drift_detected_key():
    ledger = VerbaLedger()
    entry = ledger.write_monitor(identity_key="sys-1", drift_detected=True)
    assert entry.payload[DRIFT_DETECTED_KEY] is True


def test_write_monitor_extra_payload_cannot_clobber_drift_detected_key():
    ledger = VerbaLedger()
    entry = ledger.write_monitor(identity_key="sys-1", drift_detected=True, extra_payload={DRIFT_DETECTED_KEY: False})
    assert entry.payload[DRIFT_DETECTED_KEY] is True


def test_write_verification_uses_the_canonical_result_key():
    ledger = VerbaLedger()
    entry = ledger.write_verification(identity_key="sys-1", result=VerificationResult.INSUFFICIENT)
    assert entry.payload[VERIFICATION_RESULT_KEY] == "INSUFFICIENT"


def test_audit_checks_pass_using_entries_written_via_convenience_methods():
    ledger = VerbaLedger()
    ledger.write_monitor(identity_key="sys-1", instance_id="inst-1", drift_detected=True)
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", instance_id="inst-1", payload={})
    ledger.write_verification(identity_key="sys-1", instance_id="inst-1", result=VerificationResult.INSUFFICIENT)
    ledger.write(LedgerEntryType.SPECIFICATION_UPDATE, identity_key="sys-1", payload={})

    report = ledger.audit()
    assert "drift_flagged_monitor_has_pre_node" not in report.checks_failed
    assert "insufficient_verification_has_specification_update" not in report.checks_failed


def test_audit_still_supports_raw_literal_payload_keys_for_backward_compat():
    # Existing callers writing raw dicts with the literal string keys must
    # keep working -- the constants' values are unchanged, just now named.
    ledger = VerbaLedger()
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={"drift_detected": True})
    ledger.write(LedgerEntryType.VERIFICATION, identity_key="sys-1", payload={"result": "INSUFFICIENT"})
    report = ledger.audit()
    assert "insufficient_verification_has_specification_update" in report.checks_failed
