"""The VERBA Ledger: an immutable, append-only, hash-chained audit log.

No reference implementation for this module exists anywhere -- it is
designed fresh from the source spec's Layer 4 description and Section 10's
five audit checks. Stdlib only; no agent-framework or model-provider SDK
imports, and (deliberately) no import of vsl_core.identity either -- see
the module-level note below.

Entry-type count note: the source spec's prose says the Ledger has "six
entry types" but then enumerates seven: MONITOR, PRE_NODE, VERIFICATION,
TERMINAL, SPECIFICATION_UPDATE, HUMAN_AUTHORISED_TRANSITION, RE_ENABLEMENT.
This is a stale-count bug in the source document itself, the same shape as
the Drift Class catalog's 36-vs-45 metadata bug. All seven are implemented
here; the enumerated list is trusted over the prose summary count, and
this discrepancy is deliberately not silently resolved to force a "six."
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Iterator, Protocol

from .exceptions import LedgerIntegrityError

GENESIS_HASH: str = "0" * 64


class LedgerEntryType(str, Enum):
    """The Ledger's entry types (seven -- see module docstring)."""

    MONITOR = "MONITOR"
    PRE_NODE = "PRE_NODE"
    VERIFICATION = "VERIFICATION"
    TERMINAL = "TERMINAL"
    SPECIFICATION_UPDATE = "SPECIFICATION_UPDATE"
    HUMAN_AUTHORISED_TRANSITION = "HUMAN_AUTHORISED_TRANSITION"
    RE_ENABLEMENT = "RE_ENABLEMENT"


# Bare module-level aliases, exported alongside the enum, specifically so
# `from vsl_core.ledger import HUMAN_AUTHORISED_TRANSITION, RE_ENABLEMENT`
# works directly -- governance.py relies on this exact import shape.
HUMAN_AUTHORISED_TRANSITION = LedgerEntryType.HUMAN_AUTHORISED_TRANSITION
RE_ENABLEMENT = LedgerEntryType.RE_ENABLEMENT


# Named payload keys for the two ledger checks that previously read magic,
# unexported string literals out of an untyped payload dict. Before these
# existed, audit()'s Drift check read m.payload.get("drift_detected") with
# no canonical spelling anywhere -- a client writing payload={"drift": True}
# instead would silently never trip the check, no error, just quietly wrong.
DRIFT_DETECTED_KEY: str = "drift_detected"
VERIFICATION_RESULT_KEY: str = "result"


class VerificationResult(str, Enum):
    """The two outcomes a VERIFICATION ledger entry's result can carry.
    Used with VERIFICATION_RESULT_KEY / VerbaLedger.write_verification().
    """

    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True)
class LedgerEntry:
    """One entry in the hash chain.

    `identity_key`/`cluster_key` are plain strings, not vsl_core.identity
    objects -- this is deliberate: it keeps the Ledger's only dependency at
    exceptions.py, so the Ledger subtree can be vendored or reused on its
    own without pulling in the rest of the package's object graph. This is
    the structural fix for the exact "importing the Ledger drags in
    unrelated dependencies" problem this package exists to solve.

    `sequence`, `prev_hash`, and `entry_hash` are populated by a
    LedgerStore's append() method, not by the caller -- a caller cannot
    lie about an entry's position in the chain. Until sealed by a store,
    a freshly constructed LedgerEntry has sequence=-1 and empty hashes.
    """

    entry_type: LedgerEntryType
    identity_key: str
    cluster_key: str | None = None
    instance_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    entry_id: str = ""
    sequence: int = -1
    prev_hash: str = ""
    entry_hash: str = ""

    def __post_init__(self) -> None:
        if not self.entry_id:
            object.__setattr__(self, "entry_id", str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "sequence": self.sequence,
            "entry_type": self.entry_type.value,
            "identity_key": self.identity_key,
            "cluster_key": self.cluster_key,
            "instance_id": self.instance_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LedgerEntry":
        """Reconstruct an entry from its serialized form.

        Deliberately does NOT recompute/verify entry_hash -- a store must
        be able to load and inspect a corrupted chain in order to diagnose
        it. Recomputation-and-comparison is verify_integrity()'s job, not
        this constructor's.
        """
        return cls(
            entry_type=LedgerEntryType(data["entry_type"]),
            identity_key=data["identity_key"],
            cluster_key=data.get("cluster_key"),
            instance_id=data.get("instance_id"),
            payload=data.get("payload", {}),
            timestamp=data["timestamp"],
            entry_id=data["entry_id"],
            sequence=data["sequence"],
            prev_hash=data["prev_hash"],
            entry_hash=data["entry_hash"],
        )


def _compute_entry_hash(entry: LedgerEntry) -> str:
    """Deterministic hash over every field of `entry` except entry_hash
    itself. Canonical (sorted-key, fixed-separator) JSON serialization
    guarantees the same logical entry always hashes identically, so a
    single-byte change to any field -- in memory or on disk -- changes
    this hash.
    """
    canonical = {
        "entry_id": entry.entry_id,
        "sequence": entry.sequence,
        "entry_type": entry.entry_type.value,
        "identity_key": entry.identity_key,
        "cluster_key": entry.cluster_key,
        "instance_id": entry.instance_id,
        "payload": entry.payload,
        "timestamp": entry.timestamp,
        "prev_hash": entry.prev_hash,
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _seal(entry: LedgerEntry, sequence: int, prev_hash: str) -> LedgerEntry:
    """Assign chain position and compute the entry's hash. Used by both
    LedgerStore implementations' append() so sealing logic exists exactly
    once.
    """
    positioned = replace(entry, sequence=sequence, prev_hash=prev_hash)
    return replace(positioned, entry_hash=_compute_entry_hash(positioned))


class LedgerStore(Protocol):
    def append(self, entry: LedgerEntry) -> LedgerEntry: ...
    def all_entries(self) -> Iterator[LedgerEntry]: ...
    def entries_for_identity(self, identity_key: str) -> Iterator[LedgerEntry]: ...
    def last_entry(self) -> LedgerEntry | None: ...


class InMemoryLedgerStore:
    """Backing store for tests and short-lived scripts."""

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self._lock = threading.RLock()

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        with self._lock:
            last = self._entries[-1] if self._entries else None
            sequence = 0 if last is None else last.sequence + 1
            prev_hash = GENESIS_HASH if last is None else last.entry_hash
            sealed = _seal(entry, sequence, prev_hash)
            self._entries.append(sealed)
            return sealed

    def all_entries(self) -> Iterator[LedgerEntry]:
        with self._lock:
            snapshot = list(self._entries)
        yield from snapshot

    def entries_for_identity(self, identity_key: str) -> Iterator[LedgerEntry]:
        for entry in self.all_entries():
            if entry.identity_key == identity_key:
                yield entry

    def last_entry(self) -> LedgerEntry | None:
        with self._lock:
            return self._entries[-1] if self._entries else None


class JsonlLedgerStore:
    """One JSON object per line, true append-only file writes (`open(...,
    "a")`, never rewrite-in-place). This is what makes tamper detection
    meaningful: a tamper test reaches into the actual file bytes on disk,
    not through this store's own API.

    Reading does not recompute/verify hashes -- see LedgerEntry.from_dict.

    fsync defaults to False for test speed; production use should pass
    fsync=True so a write survives a crash immediately after it returns.
    """

    def __init__(self, path: Path | str, *, fsync: bool = False) -> None:
        self.path = Path(path)
        self.fsync = fsync
        self._lock = threading.RLock()
        if not self.path.exists():
            self.path.touch()

    def all_entries(self) -> Iterator[LedgerEntry]:
        with self._lock:
            text = self.path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            yield LedgerEntry.from_dict(json.loads(line))

    def entries_for_identity(self, identity_key: str) -> Iterator[LedgerEntry]:
        for entry in self.all_entries():
            if entry.identity_key == identity_key:
                yield entry

    def last_entry(self) -> LedgerEntry | None:
        last: LedgerEntry | None = None
        for entry in self.all_entries():
            last = entry
        return last

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        with self._lock:
            last = self.last_entry()
            sequence = 0 if last is None else last.sequence + 1
            prev_hash = GENESIS_HASH if last is None else last.entry_hash
            sealed = _seal(entry, sequence, prev_hash)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(sealed.to_dict(), sort_keys=True) + "\n")
                f.flush()
                if self.fsync:
                    os.fsync(f.fileno())
            return sealed


@dataclass(frozen=True)
class LedgerAuditReport:
    """Result of VerbaLedger.audit(): which of the spec's five checks
    passed/failed, and which specific entries violated a failed check.
    """

    checks_passed: tuple[str, ...]
    checks_failed: tuple[str, ...]
    violations: dict[str, list[str]]

    @property
    def all_passed(self) -> bool:
        return not self.checks_failed


@dataclass(frozen=True)
class VerbaCertificate:
    """An audit outcome confirming all five Ledger checks pass for a
    period. Certifies the governance PROCESS, not the underlying system --
    see NOTE, which is deliberately surfaced in __str__ so it cannot be
    missed in logs.
    """

    issued_at: float
    period_start: float
    period_end: float
    entries_covered: int
    audit_report: LedgerAuditReport
    certificate_hash: str = ""

    NOTE: ClassVar[str] = (
        "This certificate does not guarantee no Inadmissible State was ever "
        "reached. It certifies that every detected Drift event was addressed, "
        "Terminal States were properly escalated, and governance was "
        "continuously monitored -- it certifies the governance process, not "
        "the underlying system, model, or domain."
    )

    def __post_init__(self) -> None:
        if not self.certificate_hash:
            blob = json.dumps(
                {
                    "issued_at": self.issued_at,
                    "period_start": self.period_start,
                    "period_end": self.period_end,
                    "entries_covered": self.entries_covered,
                    "checks_passed": list(self.audit_report.checks_passed),
                    "checks_failed": list(self.audit_report.checks_failed),
                },
                sort_keys=True,
            )
            object.__setattr__(self, "certificate_hash", hashlib.sha256(blob.encode("utf-8")).hexdigest())

    def __str__(self) -> str:
        return (
            f"VerbaCertificate(entries_covered={self.entries_covered}, "
            f"all_passed={self.audit_report.all_passed}) -- {self.NOTE}"
        )


_AUDIT_CHECKS: tuple[str, ...] = (
    "no_monitoring_gaps",
    "drift_flagged_monitor_has_pre_node",
    "pre_node_has_verification",
    "insufficient_verification_has_specification_update",
    "terminal_has_human_authorised_transition",
)


class VerbaLedger:
    """Façade over a LedgerStore implementing write/verify_integrity/audit."""

    def __init__(self, store: LedgerStore | None = None) -> None:
        self.store: LedgerStore = store if store is not None else InMemoryLedgerStore()

    def write(
        self,
        entry_type: LedgerEntryType,
        *,
        identity_key: str,
        cluster_key: str | None = None,
        instance_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> LedgerEntry:
        last = self.store.last_entry()
        if last is not None and _compute_entry_hash(last) != last.entry_hash:
            raise LedgerIntegrityError(
                "Refusing to append: the ledger's last entry fails its own "
                "hash check, indicating the existing chain has already been "
                "tampered with. Diagnose with verify_integrity()/audit() "
                "before writing further entries."
            )
        draft = LedgerEntry(
            entry_type=entry_type,
            identity_key=identity_key,
            cluster_key=cluster_key,
            instance_id=instance_id,
            payload=payload or {},
        )
        return self.store.append(draft)

    def write_monitor(
        self,
        *,
        identity_key: str,
        drift_detected: bool,
        cluster_key: str | None = None,
        instance_id: str | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> LedgerEntry:
        """Write a MONITOR entry with a correctly-keyed drift_detected
        payload field, so a caller never needs to know DRIFT_DETECTED_KEY
        directly. The load-bearing key is merged in last so extra_payload
        can never silently clobber it.
        """
        payload = {**(extra_payload or {}), DRIFT_DETECTED_KEY: drift_detected}
        return self.write(
            LedgerEntryType.MONITOR,
            identity_key=identity_key,
            cluster_key=cluster_key,
            instance_id=instance_id,
            payload=payload,
        )

    def write_verification(
        self,
        *,
        identity_key: str,
        result: VerificationResult,
        cluster_key: str | None = None,
        instance_id: str | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> LedgerEntry:
        """Write a VERIFICATION entry with a correctly-keyed result payload
        field, so a caller never needs to know VERIFICATION_RESULT_KEY
        directly.
        """
        payload = {**(extra_payload or {}), VERIFICATION_RESULT_KEY: result.value}
        return self.write(
            LedgerEntryType.VERIFICATION,
            identity_key=identity_key,
            cluster_key=cluster_key,
            instance_id=instance_id,
            payload=payload,
        )

    def verify_integrity(self) -> bool:
        """Recompute every entry's hash and chain pointer. Never raises --
        returns False for any mismatch, gap in sequence, or broken chain
        link, so a chain already known to be suspect can still be
        inspected (see audit()) rather than raising past the caller.
        """
        entries = list(self.store.all_entries())
        expected_prev = GENESIS_HASH
        expected_sequence = 0
        for entry in entries:
            if entry.sequence != expected_sequence:
                return False
            if entry.prev_hash != expected_prev:
                return False
            if _compute_entry_hash(entry) != entry.entry_hash:
                return False
            expected_prev = entry.entry_hash
            expected_sequence += 1
        return True

    def audit(self, *, max_monitor_gap_seconds: float | None = None) -> LedgerAuditReport:
        """The spec's Section 10 five audit checks. max_monitor_gap_seconds
        has no universal default -- the DC catalog's own monitoring-
        frequency table shows required cadence varies from per-token to
        continuous-background by drift class, so the caller must supply a
        domain-appropriate value. Passing None skips check 1 entirely
        (reported as passed, since no gap threshold was asked for).
        """
        entries = list(self.store.all_entries())
        violations: dict[str, list[str]] = {}

        monitor_entries = [e for e in entries if e.entry_type == LedgerEntryType.MONITOR]
        if max_monitor_gap_seconds is not None:
            sorted_monitors = sorted(monitor_entries, key=lambda e: e.timestamp)
            gap_violations = [
                f"{prev.entry_id}->{curr.entry_id}"
                for prev, curr in zip(sorted_monitors, sorted_monitors[1:])
                if curr.timestamp - prev.timestamp > max_monitor_gap_seconds
            ]
            if gap_violations:
                violations["no_monitoring_gaps"] = gap_violations

        pre_node_entries = [e for e in entries if e.entry_type == LedgerEntryType.PRE_NODE]
        check2 = [
            m.entry_id
            for m in monitor_entries
            if m.payload.get(DRIFT_DETECTED_KEY)
            and not any(
                pn.timestamp >= m.timestamp
                and pn.identity_key == m.identity_key
                and pn.instance_id == m.instance_id
                for pn in pre_node_entries
            )
        ]
        if check2:
            violations["drift_flagged_monitor_has_pre_node"] = check2

        verification_entries = [e for e in entries if e.entry_type == LedgerEntryType.VERIFICATION]
        check3 = [
            pn.entry_id
            for pn in pre_node_entries
            if not any(
                v.timestamp >= pn.timestamp
                and v.identity_key == pn.identity_key
                and v.instance_id == pn.instance_id
                for v in verification_entries
            )
        ]
        if check3:
            violations["pre_node_has_verification"] = check3

        spec_update_entries = [e for e in entries if e.entry_type == LedgerEntryType.SPECIFICATION_UPDATE]
        check4 = [
            v.entry_id
            for v in verification_entries
            if v.payload.get(VERIFICATION_RESULT_KEY) == VerificationResult.INSUFFICIENT.value
            and not any(s.timestamp >= v.timestamp and s.identity_key == v.identity_key for s in spec_update_entries)
        ]
        if check4:
            violations["insufficient_verification_has_specification_update"] = check4

        terminal_entries = [e for e in entries if e.entry_type == LedgerEntryType.TERMINAL]
        hat_entries = [e for e in entries if e.entry_type == LedgerEntryType.HUMAN_AUTHORISED_TRANSITION]
        check5 = [
            t.entry_id
            for t in terminal_entries
            if not any(h.timestamp >= t.timestamp and h.identity_key == t.identity_key for h in hat_entries)
        ]
        if check5:
            violations["terminal_has_human_authorised_transition"] = check5

        checks_failed = tuple(c for c in _AUDIT_CHECKS if c in violations)
        checks_passed = tuple(c for c in _AUDIT_CHECKS if c not in violations)
        return LedgerAuditReport(checks_passed=checks_passed, checks_failed=checks_failed, violations=violations)

    def issue_certificate(self, *, max_monitor_gap_seconds: float | None = None) -> VerbaCertificate | None:
        """Returns a VerbaCertificate only if the audit fully passes; never
        fabricates a certificate for a failed audit.
        """
        entries = list(self.store.all_entries())
        report = self.audit(max_monitor_gap_seconds=max_monitor_gap_seconds)
        if not report.all_passed:
            return None
        now = time.time()
        return VerbaCertificate(
            issued_at=now,
            period_start=entries[0].timestamp if entries else now,
            period_end=entries[-1].timestamp if entries else now,
            entries_covered=len(entries),
            audit_report=report,
        )
