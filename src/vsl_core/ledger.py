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
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Iterator, Protocol

from .exceptions import LedgerIntegrityError

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

GENESIS_HASH: str = "0" * 64

# The current shape/version of LedgerEntry's recorded fields. Bump this
# whenever a field is added, removed, or reinterpreted, so an entry is
# self-describing about which format it was written under rather than
# leaving a reader to guess from which fields happen to be present. Entries
# persisted before this field existed load with schema_version=None (see
# LedgerEntry.from_dict) -- that absence is itself meaningful, not a bug.
LEDGER_SCHEMA_VERSION: str = "1.0"


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

    `decision_id`/`caused_by` are optional causal-correlation fields, not
    part of the source spec. Without them, audit()'s cross-referencing
    checks can only match entries by "same identity_key/instance_id and a
    later timestamp" -- which silently mismatches when a single Instance
    has more than one decision in flight at once (e.g. a payment check and
    an email verification interleaved on the same agent). `caused_by` lets
    an entry name the exact prior entry_id it resolves, so audit() can
    match causally instead of guessing from timing; `decision_id` is purely
    descriptive grouping metadata for querying/display and is not itself
    read by any audit check. Both are optional and default to None so
    existing single-decision-at-a-time callers are unaffected -- audit()
    falls back to the old timestamp-based heuristic whenever caused_by is
    unset.

    `schema_version` records which shape of LedgerEntry wrote this entry
    (see LEDGER_SCHEMA_VERSION). It defaults to None here deliberately --
    VerbaLedger.write() is what stamps the current constant onto every
    entry it constructs; a bare LedgerEntry(...) built directly (e.g. in a
    test, or by from_dict() reconstructing a legacy entry with no recorded
    version) should not silently claim a version it wasn't actually written
    under.
    """

    entry_type: LedgerEntryType
    identity_key: str
    cluster_key: str | None = None
    instance_id: str | None = None
    decision_id: str | None = None
    caused_by: str | None = None
    schema_version: str | None = None
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
            "decision_id": self.decision_id,
            "caused_by": self.caused_by,
            "schema_version": self.schema_version,
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

        `.get()` on decision_id/caused_by/schema_version so entries
        persisted before these fields existed still load cleanly, as None.
        """
        return cls(
            entry_type=LedgerEntryType(data["entry_type"]),
            identity_key=data["identity_key"],
            cluster_key=data.get("cluster_key"),
            instance_id=data.get("instance_id"),
            decision_id=data.get("decision_id"),
            caused_by=data.get("caused_by"),
            schema_version=data.get("schema_version"),
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
        "decision_id": entry.decision_id,
        "caused_by": entry.caused_by,
        "schema_version": entry.schema_version,
        "payload": entry.payload,
        "timestamp": entry.timestamp,
        "prev_hash": entry.prev_hash,
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _causally_resolves(candidate: LedgerEntry, source: LedgerEntry, *, check_instance: bool) -> bool:
    """True if `candidate` counts as resolving `source` in an audit check.

    If `candidate.caused_by` is set, it must reference `source.entry_id`
    exactly -- an explicit causal claim is authoritative and overrides the
    fallback heuristic below, even when timestamps/identity/instance would
    otherwise coincidentally match a *different*, unrelated entry. This is
    what closes the false-pass gap: once a candidate declares its real
    cause, it stops being available to satisfy an unrelated check just
    because it happens to share an identity/instance and come later.

    If `candidate.caused_by` is unset, falls back to the pre-existing
    timestamp + identity_key (+ instance_id, when check_instance) heuristic,
    so callers that don't populate the causal fields see unchanged
    behavior.
    """
    if candidate.caused_by is not None:
        return candidate.caused_by == source.entry_id
    if candidate.timestamp < source.timestamp:
        return False
    if candidate.identity_key != source.identity_key:
        return False
    if check_instance and candidate.instance_id != source.instance_id:
        return False
    return True


def _seal(entry: LedgerEntry, sequence: int, prev_hash: str) -> LedgerEntry:
    """Assign chain position and compute the entry's hash. Used by both
    LedgerStore implementations' append() so sealing logic exists exactly
    once.
    """
    positioned = replace(entry, sequence=sequence, prev_hash=prev_hash)
    return replace(positioned, entry_hash=_compute_entry_hash(positioned))


class _CrossProcessFileLock:
    """An OS-level advisory lock on a sibling `.lock` file, held for the
    duration of a `with` block.

    JsonlLedgerStore's own `threading.RLock` only protects concurrent
    writers that share the same Python object -- it does nothing for two
    separate `JsonlLedgerStore` instances (in one process or several)
    pointed at the same file, which can otherwise race: both read the same
    `last_entry()` before either appends, both compute the same sequence/
    prev_hash, and both write, corrupting the chain. This lock closes that
    gap by making the read-last-entry-then-append sequence mutually
    exclusive across every writer of the file, not just within one object.

    Uses `fcntl.flock` (POSIX) / `msvcrt.locking` (Windows) rather than a
    plain `O_CREAT|O_EXCL` lockfile mutex on purpose: both are tied to the
    open file descriptor's lifetime, so the OS releases the lock
    automatically if the holding process dies mid-write, instead of
    leaving a stale lock file that blocks every future writer forever.
    """

    def __init__(self, path: Path) -> None:
        self._lock_path = path.with_name(path.name + ".lock")
        self._file = None

    def __enter__(self) -> "_CrossProcessFileLock":
        if sys.platform == "win32":
            # msvcrt.locking locks a real byte range starting at the
            # current file position -- the file needs that byte to exist
            # before any lock is attempted. Ensuring that via a separate,
            # short-lived handle (not the one we go on to lock) matters:
            # Windows' byte-range locks are mandatory, not advisory, so a
            # *read* of an already-locked byte from another handle raises
            # PermissionError immediately rather than blocking like POSIX
            # advisory locks do. Checking existence/size via stat() only
            # touches filesystem metadata, never the locked byte range, so
            # it can't collide with a lock another thread/process holds.
            if not self._lock_path.exists() or self._lock_path.stat().st_size == 0:
                with open(self._lock_path, "ab") as touch:
                    touch.write(b"\0")
                    touch.flush()
            self._file = open(self._lock_path, "r+b")
            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            self._file = open(self._lock_path, "a+b")
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._file is None:
            return
        if sys.platform == "win32":
            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        self._file.close()
        self._file = None


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

    `self._lock` (a `threading.RLock`) only ever protected concurrent
    writers sharing this exact Python object -- it did nothing for two
    separate `JsonlLedgerStore` instances pointed at the same file, which
    is an entirely ordinary situation across processes (and even across
    threads that each construct their own store). `append()` now also
    holds a `_CrossProcessFileLock` on a sibling `.lock` file for its whole
    read-last-entry-then-write critical section, so that race is closed
    for real, not just documented.
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
        with self._lock, _CrossProcessFileLock(self.path):
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
class LedgerCheckpoint:
    """The chain's current tip: just enough for an external party to
    independently witness that the chain hasn't been rolled back or
    replaced wholesale, without vsl-core itself doing any anchoring,
    signing, or networking.

    `verify_integrity()` only proves internal consistency of whatever
    entries the store currently holds -- it can't detect truncation
    (deleting the last N entries) or wholesale replacement with an older,
    still-internally-consistent snapshot, because a shortened or replaced
    chain is still a valid chain on its own terms. An external anchor that
    records this checkpoint's (sequence, entry_hash) at intervals, outside
    the operator's control, is what closes that gap: a later checkpoint
    with a lower sequence, or the same sequence with a different hash,
    proves the local chain was altered after the fact. vsl-core deliberately
    stops at exposing this value -- storing it externally, signing it, or
    comparing it over time is a different system's job.
    """

    sequence: int
    entry_hash: str
    checked_at: float


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
        decision_id: str | None = None,
        caused_by: str | None = None,
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
            decision_id=decision_id,
            caused_by=caused_by,
            schema_version=LEDGER_SCHEMA_VERSION,
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
        decision_id: str | None = None,
        caused_by: str | None = None,
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
            decision_id=decision_id,
            caused_by=caused_by,
            payload=payload,
        )

    def write_verification(
        self,
        *,
        identity_key: str,
        result: VerificationResult,
        cluster_key: str | None = None,
        instance_id: str | None = None,
        decision_id: str | None = None,
        caused_by: str | None = None,
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
            decision_id=decision_id,
            caused_by=caused_by,
            payload=payload,
        )

    def current_checkpoint(self) -> LedgerCheckpoint | None:
        """Return the chain's current tip, or None for an empty ledger.

        This is the one fact an external anchoring service would need to
        witness the chain independently over time (see LedgerCheckpoint) --
        vsl-core exposes the value and stops there; it does not sign,
        transmit, or store it anywhere itself.
        """
        last = self.store.last_entry()
        if last is None:
            return None
        return LedgerCheckpoint(sequence=last.sequence, entry_hash=last.entry_hash, checked_at=time.time())

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

        Checks 2-5 match causally via `caused_by` whenever a candidate
        entry sets it (see `_causally_resolves`), falling back to the
        original same-identity/instance-and-later-timestamp heuristic only
        when it's unset. Without `caused_by`, two unrelated decisions
        overlapping on the same identity/instance can be mismatched -- e.g.
        an unrelated PRE_NODE that merely happens to come after a
        drift-flagged MONITOR can look like it resolves that MONITOR. This
        is a real limitation of the fallback path, not a fabricated one:
        populate `caused_by` on every write once more than one decision can
        be in flight at a time for the same identity/instance.
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
            and not any(_causally_resolves(pn, m, check_instance=True) for pn in pre_node_entries)
        ]
        if check2:
            violations["drift_flagged_monitor_has_pre_node"] = check2

        verification_entries = [e for e in entries if e.entry_type == LedgerEntryType.VERIFICATION]
        check3 = [
            pn.entry_id
            for pn in pre_node_entries
            if not any(_causally_resolves(v, pn, check_instance=True) for v in verification_entries)
        ]
        if check3:
            violations["pre_node_has_verification"] = check3

        spec_update_entries = [e for e in entries if e.entry_type == LedgerEntryType.SPECIFICATION_UPDATE]
        check4 = [
            v.entry_id
            for v in verification_entries
            if v.payload.get(VERIFICATION_RESULT_KEY) == VerificationResult.INSUFFICIENT.value
            and not any(_causally_resolves(s, v, check_instance=False) for s in spec_update_entries)
        ]
        if check4:
            violations["insufficient_verification_has_specification_update"] = check4

        terminal_entries = [e for e in entries if e.entry_type == LedgerEntryType.TERMINAL]
        hat_entries = [e for e in entries if e.entry_type == LedgerEntryType.HUMAN_AUTHORISED_TRANSITION]
        check5 = [
            t.entry_id
            for t in terminal_entries
            if not any(_causally_resolves(h, t, check_instance=False) for h in hat_entries)
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
