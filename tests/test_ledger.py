import time

import pytest

from vsl_core.exceptions import LedgerIntegrityError
from vsl_core.ledger import (
    DRIFT_DETECTED_KEY,
    HUMAN_AUTHORISED_TRANSITION,
    LEDGER_SCHEMA_VERSION,
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


def test_audit_without_caused_by_can_false_pass_on_interleaved_decisions():
    # Documents a real limitation of the timestamp-based fallback, not a
    # desired behavior: two unrelated decisions on the same identity/
    # instance can be confused. A drift-flagged MONITOR for "payment" is
    # followed by an unrelated PRE_NODE for "email" -- without caused_by,
    # check2 can't tell them apart and incorrectly reports the payment
    # drift as resolved. The next test proves caused_by fixes exactly this.
    ledger = VerbaLedger()
    ledger.write_monitor(
        identity_key="sys-1", instance_id="inst-1", drift_detected=True, extra_payload={"decision": "payment"}
    )
    ledger.write(LedgerEntryType.PRE_NODE, identity_key="sys-1", instance_id="inst-1", payload={"decision": "email"})

    report = ledger.audit()
    assert "drift_flagged_monitor_has_pre_node" not in report.checks_failed


def test_audit_with_caused_by_correctly_catches_interleaved_decision_violation():
    ledger = VerbaLedger()
    payment_monitor = ledger.write_monitor(
        identity_key="sys-1", instance_id="inst-1", drift_detected=True, extra_payload={"decision": "payment"}
    )
    # An unrelated PRE_NODE for a different decision, explicitly marked as
    # caused by something other than the payment monitor.
    ledger.write(
        LedgerEntryType.PRE_NODE,
        identity_key="sys-1",
        instance_id="inst-1",
        caused_by="some-other-monitor-entry-id",
        payload={"decision": "email"},
    )

    report = ledger.audit()
    assert "drift_flagged_monitor_has_pre_node" in report.checks_failed
    assert payment_monitor.entry_id in report.violations["drift_flagged_monitor_has_pre_node"]


def test_audit_with_caused_by_correctly_resolves_the_right_decision():
    ledger = VerbaLedger()
    payment_monitor = ledger.write_monitor(
        identity_key="sys-1", instance_id="inst-1", drift_detected=True, extra_payload={"decision": "payment"}
    )
    ledger.write(
        LedgerEntryType.PRE_NODE,
        identity_key="sys-1",
        instance_id="inst-1",
        caused_by=payment_monitor.entry_id,
        payload={"decision": "payment"},
    )
    # An unrelated interleaved decision, correctly not confused with the above.
    ledger.write(
        LedgerEntryType.PRE_NODE,
        identity_key="sys-1",
        instance_id="inst-1",
        caused_by="some-other-monitor-entry-id",
        payload={"decision": "email"},
    )

    report = ledger.audit()
    assert "drift_flagged_monitor_has_pre_node" not in report.checks_failed


def test_tamper_detection_catches_decision_id_mutation(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write_monitor(
        identity_key="sys-1", instance_id="inst-1", drift_detected=True, decision_id="DECISION_MARKER_VALUE"
    )

    untouched = VerbaLedger(JsonlLedgerStore(path))
    assert untouched.verify_integrity() is True

    raw = path.read_bytes()
    assert b"DECISION_MARKER_VALUE" in raw
    tampered = raw.replace(b"DECISION_MARKER_VALUE", b"DECISION_MARKER_VALUX", 1)
    assert tampered != raw
    assert len(tampered) == len(raw)
    path.write_bytes(tampered)

    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is False


def test_tamper_detection_catches_caused_by_mutation(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write_monitor(identity_key="sys-1", instance_id="inst-1", drift_detected=True)
    ledger.write(
        LedgerEntryType.PRE_NODE,
        identity_key="sys-1",
        instance_id="inst-1",
        caused_by="CAUSED_BY_MARKER_VALUE",
        payload={},
    )

    untouched = VerbaLedger(JsonlLedgerStore(path))
    assert untouched.verify_integrity() is True

    raw = path.read_bytes()
    assert b"CAUSED_BY_MARKER_VALUE" in raw
    tampered = raw.replace(b"CAUSED_BY_MARKER_VALUE", b"CAUSED_BY_MARKER_VALUX", 1)
    assert tampered != raw
    assert len(tampered) == len(raw)
    path.write_bytes(tampered)

    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is False


def test_from_dict_defaults_missing_causal_fields_to_none():
    # Simulates loading an entry persisted before decision_id/caused_by
    # existed -- must not raise a KeyError, and must default cleanly.
    from vsl_core.ledger import LedgerEntry

    legacy_data = {
        "entry_id": "e1",
        "sequence": 0,
        "entry_type": "MONITOR",
        "identity_key": "sys-1",
        "cluster_key": None,
        "instance_id": None,
        "payload": {},
        "timestamp": 0.0,
        "prev_hash": GENESIS_HASH,
        "entry_hash": "irrelevant-for-this-test",
    }
    entry = LedgerEntry.from_dict(legacy_data)
    assert entry.decision_id is None
    assert entry.caused_by is None


def test_decision_id_and_caused_by_round_trip_through_jsonl(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    monitor = ledger.write_monitor(
        identity_key="sys-1", instance_id="inst-1", drift_detected=True, decision_id="dec-1"
    )
    ledger.write(
        LedgerEntryType.PRE_NODE,
        identity_key="sys-1",
        instance_id="inst-1",
        decision_id="dec-1",
        caused_by=monitor.entry_id,
        payload={},
    )

    reopened = VerbaLedger(JsonlLedgerStore(path))
    entries = list(reopened.store.all_entries())
    assert entries[0].decision_id == "dec-1"
    assert entries[1].decision_id == "dec-1"
    assert entries[1].caused_by == monitor.entry_id
    assert reopened.verify_integrity() is True


def test_write_stamps_current_schema_version():
    ledger = VerbaLedger()
    entry = ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})
    assert entry.schema_version == LEDGER_SCHEMA_VERSION


def test_bare_ledger_entry_construction_does_not_assume_a_schema_version():
    # A LedgerEntry built directly (not through VerbaLedger.write()) should
    # not silently claim the current schema version -- only write() stamps
    # it, so a bare construction (e.g. reconstructing a legacy entry) stays
    # honest about not actually knowing which version it was written under.
    from vsl_core.ledger import LedgerEntry

    entry = LedgerEntry(entry_type=LedgerEntryType.MONITOR, identity_key="sys-1")
    assert entry.schema_version is None


def test_tamper_detection_catches_schema_version_mutation(tmp_path):
    import json

    path = tmp_path / "ledger.jsonl"
    ledger = VerbaLedger(JsonlLedgerStore(path))
    ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})

    untouched = VerbaLedger(JsonlLedgerStore(path))
    assert untouched.verify_integrity() is True

    lines = path.read_text(encoding="utf-8").splitlines()
    data = json.loads(lines[0])
    assert data["schema_version"] == LEDGER_SCHEMA_VERSION
    data["schema_version"] = "9.9"
    lines[0] = json.dumps(data, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    reopened = VerbaLedger(JsonlLedgerStore(path))
    assert reopened.verify_integrity() is False


def test_current_checkpoint_none_on_empty_ledger():
    ledger = VerbaLedger()
    assert ledger.current_checkpoint() is None


def test_current_checkpoint_matches_last_entry_and_updates_on_new_writes():
    ledger = VerbaLedger()
    e1 = ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})
    cp1 = ledger.current_checkpoint()
    assert cp1 is not None
    assert cp1.sequence == e1.sequence
    assert cp1.entry_hash == e1.entry_hash

    e2 = ledger.write(LedgerEntryType.MONITOR, identity_key="sys-1", payload={})
    cp2 = ledger.current_checkpoint()
    assert cp2.sequence == e2.sequence
    assert cp2.entry_hash == e2.entry_hash
    assert cp2.sequence != cp1.sequence
    assert cp2.entry_hash != cp1.entry_hash


def test_jsonl_store_is_safe_under_concurrent_writers_from_separate_instances(tmp_path):
    # Each worker builds its OWN JsonlLedgerStore pointed at the same file --
    # exactly the shape of race that a threading.RLock scoped to one Python
    # object cannot prevent, and that _CrossProcessFileLock now closes.
    # Before that lock existed, this was a real, reproducible way to corrupt
    # the chain (duplicate/skipped sequence numbers from two writers reading
    # the same last_entry() before either appended).
    import concurrent.futures

    path = tmp_path / "ledger.jsonl"
    writes_per_worker = 25
    workers = 4

    def write_many(worker_id: int) -> None:
        ledger = VerbaLedger(JsonlLedgerStore(path))
        for _ in range(writes_per_worker):
            ledger.write_monitor(identity_key=f"worker-{worker_id}", drift_detected=False)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(write_many, w) for w in range(workers)]
        for f in futures:
            f.result()

    final = VerbaLedger(JsonlLedgerStore(path))
    entries = list(final.store.all_entries())
    assert len(entries) == writes_per_worker * workers
    assert final.verify_integrity() is True
    # Sequence numbers must be a contiguous 0..N-1 run with no duplicates or
    # gaps -- exactly what a lost race would corrupt.
    assert sorted(e.sequence for e in entries) == list(range(writes_per_worker * workers))
