"""Layer 3 quantitative backbone: Delta, Gamma, GES, EEF.

Pure computation over floats/dataclasses. No I/O, no framework or model
SDK dependency of any kind.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

# VERBA's default Robust Gamma Threshold: Gamma_threshold = 1.1, corresponding
# to a 10% relative estimation-error tolerance (delta = 0.1). This is the
# maximum estimation error the framework can absorb while still guaranteeing
# Gamma* > 1, not an arbitrarily rounded-up safety margin.
ROBUST_GAMMA_DEFAULT_THRESHOLD: float = 1.1

# The source spec's stated recommendation for high-stakes deployments
# (delta = 0.2).
ROBUST_GAMMA_HIGH_STAKES_THRESHOLD: float = 1.2


class AssuranceLevel(str, Enum):
    """HIGH / MEDIUM / LOW confidence rating per the F1/F2 test.

    A mechanism satisfying F1 (pre-commitment) but only partial F2 (energy-
    landscape modification) -- e.g. a system prompt or blocking guardrail
    against a hosted model API -- caps at MEDIUM, never HIGH. This
    distinction must never be blurred by any code or docs built on top of
    this package.

    Prefer constructing this via AssuranceBasis.derived_level rather than
    setting it directly -- see AssuranceBasis below.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class F2Modification(str, Enum):
    """How fully an intervention modifies the energy function E_gov(x) =
    E_0(x) + U(x), per the source spec's F2 test.

    FULL: directly modifies the energy function (logit adjustment,
    activation steering, fine-tuning, constitutional training).
    PARTIAL: shapes output through attention/context rather than direct
    energy modification (system prompts, RAG context injection).
    INDIRECT: affects sampling without touching the energy function itself
    (temperature adjustment).
    NONE: no claimed effect on the energy function at all.
    """

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    INDIRECT = "INDIRECT"
    NONE = "NONE"


@dataclass(frozen=True)
class AssuranceBasis:
    """The F1/F2 facts an AssuranceLevel must be derived from, rather than
    asserted directly.

    Before this type existed, AllowedState.assurance_level and
    PreNode.assurance_level were freely-settable fields -- nothing stopped
    a caller from writing assurance_level=AssuranceLevel.HIGH on a
    mechanism that was actually output-layer. AssuranceBasis makes the two
    load-bearing facts (F1: does this run before commitment? F2: how fully
    does it modify the energy function?) the only inputs, and derives the
    level from them.

    derived_level implements the source table exhaustively:
      F1=False                       -> LOW,  for any F2 value
      F1=True,  F2=FULL               -> HIGH
      F1=True,  F2 in {PARTIAL, INDIRECT} -> MEDIUM
      F1=True,  F2=NONE               -> LOW

    That last row (F1=True, F2=NONE) is not in the source paper's table --
    the paper never covers a mechanism that runs before commitment but
    claims zero energy-landscape effect. This is a deliberate interpretive
    extension, not a spec fact: a check that runs early but does nothing to
    the distribution isn't governance in the Gamma-sufficiency sense, so it
    is treated the same as output-layer (LOW) rather than left undefined.
    """

    f1_pre_commitment: bool
    f2_modification: F2Modification

    @property
    def derived_level(self) -> AssuranceLevel:
        if not self.f1_pre_commitment:
            return AssuranceLevel.LOW
        if self.f2_modification == F2Modification.FULL:
            return AssuranceLevel.HIGH
        if self.f2_modification in (F2Modification.PARTIAL, F2Modification.INDIRECT):
            return AssuranceLevel.MEDIUM
        return AssuranceLevel.LOW


@dataclass(frozen=True)
class GammaEstimate:
    """A point estimate of Gamma (Governance-to-Drift Ratio) plus its
    estimation-error bound, so sufficiency can be judged against the
    Robust Gamma Threshold rather than the raw estimate.
    """

    gamma_hat: float
    delta_estimation_error: float = 0.0
    energy_gap_estimate: float | None = None
    measured_at: float = field(default_factory=time.time)

    def robust_gamma(self) -> float:
        """Gamma* = Gamma_hat * (1 / (1 + delta)), the worst-case Gamma
        after accounting for estimation error in the energy gap.
        """
        return self.gamma_hat * (1.0 / (1.0 + self.delta_estimation_error))

    def sufficient(self, threshold: float = ROBUST_GAMMA_DEFAULT_THRESHOLD) -> bool:
        """True iff the robust (worst-case) Gamma exceeds the threshold.

        This exact name and signature is load-bearing: it is called
        directly by PlainPythonReferenceAdapter.compile_pre_node and by
        any other adapter's compiled gate.
        """
        return self.robust_gamma() > threshold


@dataclass(frozen=True)
class Delta:
    """Governance potential: the energy contribution of the governance
    mechanism to the governed landscape.
    """

    value: float

    @classmethod
    def from_gamma(cls, gamma: float, energy_gap: float) -> "Delta":
        """Delta = Gamma * (E_high - E_drift)."""
        return cls(value=gamma * energy_gap)


@dataclass(frozen=True)
class GES:
    """Governance Effectiveness Score: a runtime-measurable proxy for
    whether governance is actually working.

    GES = 0: no effect. GES = 1: divergence eliminated. GES < 0: governance
    made things worse.
    """

    score: float

    @classmethod
    def compute(cls, governed_kl_integral: float, ungoverned_kl_integral: float) -> "GES":
        """GES = 1 - (integral of governed KL divergence / integral of
        ungoverned KL divergence).
        """
        if ungoverned_kl_integral == 0:
            raise ValueError(
                "ungoverned_kl_integral must be nonzero -- a zero-divergence "
                "ungoverned baseline makes GES undefined, not zero."
            )
        return cls(score=1.0 - (governed_kl_integral / ungoverned_kl_integral))

    def triggers_specification_update(self, theta: float) -> bool:
        """True iff GES < theta, the spec's trigger for a Specification
        Update.
        """
        return self.score < theta


class EEFZone(str, Enum):
    """The three zones of Enforcement Effectiveness Factor.

    Zone 1 (Gamma < 1): insufficient governance.
    Zone 2 (Gamma > 1, EEF <= 1): optimal -- VERBA's target state at all times.
    Zone 3 (EEF > 1): over-governance; new Drift Nodes form in unspecified gaps.
    """

    INSUFFICIENT = "INSUFFICIENT"
    OPTIMAL = "OPTIMAL"
    OVER_GOVERNANCE = "OVER_GOVERNANCE"


@dataclass(frozen=True)
class EEF:
    """Enforcement Effectiveness Factor: ratio of governance cost to
    maximum sustainable governance cost.
    """

    value: float

    @classmethod
    def compute(cls, cost_of_pre_node: float, max_sustainable_cost: float) -> "EEF":
        """EEF = C(U_PN) / C_max."""
        if max_sustainable_cost == 0:
            raise ValueError("max_sustainable_cost must be nonzero.")
        return cls(value=cost_of_pre_node / max_sustainable_cost)

    def zone(self, gamma_estimate: GammaEstimate) -> EEFZone:
        """Classify into the spec's three zones: Zone 1 (Gamma<=1) is
        insufficient regardless of EEF; Zone 2 (Gamma>1, EEF<=1) is
        optimal; Zone 3 (EEF>1) is over-governance.
        """
        if gamma_estimate.robust_gamma() <= 1.0:
            return EEFZone.INSUFFICIENT
        if self.value <= 1.0:
            return EEFZone.OPTIMAL
        return EEFZone.OVER_GOVERNANCE


@dataclass(frozen=True)
class Beta:
    """Inverse temperature: inverse of effective system "temperature."
    Higher Beta means lower volatility -- probability concentrates more
    strongly on energy minima. Systems tuned at a normal Beta may fail at
    crisis (lower) Beta, requiring higher Delta to hold Gamma > 1.

    The source spec describes this relationship only qualitatively -- it
    gives no closed-form formula relating Beta to Delta or Gamma the way it
    does for Gamma/GES/EEF. This type deliberately holds nothing but the
    raw value: it exists so Beta can be named and logged (e.g. "measured at
    crisis Beta=X"), not to compute anything from it. Do not add a formula
    here that the source paper doesn't actually provide.
    """

    value: float


@dataclass(frozen=True)
class Threshold:
    """A named quantitative limit. Exceeding (or falling below, depending
    on the quantity) it invalidates a transition.
    """

    name: str
    value: float
    unit: str = ""


# The three concrete default thresholds the source spec names. Only Gamma's
# was previously represented anywhere in this module (as
# ROBUST_GAMMA_DEFAULT_THRESHOLD); Jacobian and KL are reference constants
# only -- computing lambda_min(J_gov) or a KL divergence is inherently
# model-specific and stays out of core, the same way Gamma estimation itself
# does. These exist so a DriftMonitor implementer has the spec's own
# defaults available instead of re-deriving or mistyping them.
GAMMA_MONITORING_THRESHOLD = Threshold(name="Gamma monitoring threshold", value=ROBUST_GAMMA_DEFAULT_THRESHOLD)
JACOBIAN_RED_FLAG_THRESHOLD = Threshold(name="Jacobian red flag (lambda_min)", value=0.05)
KL_MONITORING_THRESHOLD = Threshold(name="KL monitoring threshold", value=0.15, unit="nats")
