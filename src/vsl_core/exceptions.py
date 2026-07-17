"""Exception hierarchy for vsl-core.

Stdlib only. No agent-framework or model-provider SDK imports.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class VSLError(Exception):
    """Root of every exception raised by vsl-core."""


@dataclass
class AutomationDeniedException(VSLError):
    """Raised when a Fallback is exhausted or a Terminal State is entered.

    The source specification describes this as an exception that "cannot be
    silently caught." That is a convention, not a language-enforced
    guarantee: Python has no mechanism to prevent ``except Exception: pass``.
    The guarantee this class actually provides is narrower and real: it is a
    distinctive, purpose-built type that is never reused for anything else,
    so a blanket handler that swallows it is conspicuous in code review.
    """

    reason: str
    identity_key: str
    instance_id: str | None = None
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        VSLError.__init__(self, self.reason)

    def __str__(self) -> str:
        return f"{self.reason} (identity_key={self.identity_key!r})"


@dataclass
class InvariantViolation(AutomationDeniedException):
    """Raised when an Invariant's rule returns False.

    Subclasses AutomationDeniedException (not a sibling) so that generic
    handlers catching AutomationDeniedException still catch this, while
    callers that need to distinguish "no Fallback path, straight to
    Terminal" (the Invariant case) from an ordinary Pre-Node Fallback
    exhaustion can catch this narrower type specifically.
    """

    invariant_name: str = ""


class LedgerIntegrityError(VSLError):
    """Raised by VerbaLedger.write() when an operation assumes an intact
    chain that the ledger can already tell is broken (e.g. appending to a
    store whose last entry's hash doesn't match its own prev_hash pointer).

    This is distinct from VerbaLedger.verify_integrity(), which never
    raises -- it returns a bool, so a caller can inspect a chain that is
    already known (or suspected) to be tampered with, without an exception
    interrupting the audit.
    """


class CatalogValidationError(VSLError):
    """Raised only for structural catalog-loading errors: malformed JSON,
    a missing required key, a file that doesn't parse.

    Never raised for the catalog's known, expected data-quality findings
    (e.g. the stale drift-class count, the orphaned CLUSTER-HANDOVER
    entry) -- those are surfaced by catalog.loader.validate() as strings,
    on purpose, so they can be inspected rather than raised past.
    """


class ConformanceError(VSLError):
    """Raised by run_conformance_suite() only when an adapter's own
    programming error prevents the suite from running at all (e.g.
    compile_pre_node returning None instead of a callable gate).

    Ordinary conformance failures -- an adapter that runs but behaves
    incorrectly -- are reported as strings in the suite's returned list,
    never raised, so a partially-conformant adapter can still be fully
    inspected in one pass.
    """
