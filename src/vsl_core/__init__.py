"""vsl-core: the framework-agnostic and model-agnostic foundation of VSL
(VERBA Specification Language) -- a governance vocabulary for deciding
whether an automated system's next action is allowed to happen, and
proving that decision was made.

Zero third-party runtime dependencies. Never imports any agent-framework
package (agents, langgraph, langchain, ...) or model-provider SDK (openai,
anthropic, ...) anywhere under this package. Framework adapters that wire
this vocabulary into a specific agent framework are separate packages
(vsl-<framework>), out of scope here -- see vsl_core.conformance for the
contract those adapters must satisfy.
"""

from .cluster import Cluster, ClusterInadmissibleState, ClusterPreNode
from .constructs import (
    AllowedState,
    DriftMonitor,
    Fallback,
    FormationLayerIntervention,
    InadmissibleState,
    Invariant,
    PreNode,
    TerminalState,
    register_invariant,
    registered_invariants,
)
from .exceptions import (
    AutomationDeniedException,
    CatalogValidationError,
    ConformanceError,
    InvariantViolation,
    LedgerIntegrityError,
    VSLError,
)
from .governance import (
    Binding,
    GovernanceAuthority,
    HumanAuthorisedTransition,
    Proofing,
    Specification,
    request_re_enablement,
)
from .identity import ClusterKey, Evidence, IdentityKey, Instance
from .ledger import (
    DRIFT_DETECTED_KEY,
    GENESIS_HASH,
    HUMAN_AUTHORISED_TRANSITION,
    LEDGER_SCHEMA_VERSION,
    RE_ENABLEMENT,
    VERIFICATION_RESULT_KEY,
    InMemoryLedgerStore,
    JsonlLedgerStore,
    LedgerAuditReport,
    LedgerCheckpoint,
    LedgerEntry,
    LedgerEntryType,
    LedgerStore,
    VerbaCertificate,
    VerbaLedger,
    VerificationResult,
)
from .metrics import (
    EEF,
    GAMMA_MONITORING_THRESHOLD,
    GES,
    JACOBIAN_RED_FLAG_THRESHOLD,
    KL_MONITORING_THRESHOLD,
    ROBUST_GAMMA_DEFAULT_THRESHOLD,
    ROBUST_GAMMA_HIGH_STAKES_THRESHOLD,
    AssuranceBasis,
    AssuranceLevel,
    Beta,
    Delta,
    EEFZone,
    F2Modification,
    GammaEstimate,
    Threshold,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # constructs
    "AllowedState",
    "InadmissibleState",
    "Fallback",
    "Invariant",
    "PreNode",
    "TerminalState",
    "DriftMonitor",
    "FormationLayerIntervention",
    "register_invariant",
    "registered_invariants",
    # cluster
    "Cluster",
    "ClusterInadmissibleState",
    "ClusterPreNode",
    # identity
    "IdentityKey",
    "ClusterKey",
    "Instance",
    "Evidence",
    # governance
    "GovernanceAuthority",
    "HumanAuthorisedTransition",
    "Proofing",
    "Binding",
    "Specification",
    "request_re_enablement",
    # ledger
    "GENESIS_HASH",
    "LedgerEntryType",
    "LedgerEntry",
    "LedgerStore",
    "InMemoryLedgerStore",
    "JsonlLedgerStore",
    "LedgerAuditReport",
    "LedgerCheckpoint",
    "VerbaCertificate",
    "VerbaLedger",
    "HUMAN_AUTHORISED_TRANSITION",
    "RE_ENABLEMENT",
    "DRIFT_DETECTED_KEY",
    "VERIFICATION_RESULT_KEY",
    "VerificationResult",
    "LEDGER_SCHEMA_VERSION",
    # metrics
    "AssuranceLevel",
    "AssuranceBasis",
    "F2Modification",
    "GammaEstimate",
    "Delta",
    "GES",
    "EEF",
    "EEFZone",
    "Beta",
    "Threshold",
    "ROBUST_GAMMA_DEFAULT_THRESHOLD",
    "ROBUST_GAMMA_HIGH_STAKES_THRESHOLD",
    "GAMMA_MONITORING_THRESHOLD",
    "JACOBIAN_RED_FLAG_THRESHOLD",
    "KL_MONITORING_THRESHOLD",
    # exceptions
    "VSLError",
    "AutomationDeniedException",
    "InvariantViolation",
    "LedgerIntegrityError",
    "CatalogValidationError",
    "ConformanceError",
]
