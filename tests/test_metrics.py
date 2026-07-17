import math

import pytest

from vsl_core.metrics import (
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


def test_robust_gamma_formula():
    # Gamma* = Gamma_hat * (1 / (1 + delta))
    estimate = GammaEstimate(gamma_hat=1.2, delta_estimation_error=0.1)
    assert math.isclose(estimate.robust_gamma(), 1.2 * (1 / 1.1))


def test_sufficient_uses_robust_gamma_not_raw_gamma_hat():
    # gamma_hat=1.15 with 10% error -> robust gamma = 1.15/1.1 = 1.0454..., below 1.1 threshold
    estimate = GammaEstimate(gamma_hat=1.15, delta_estimation_error=0.1)
    assert not estimate.sufficient(ROBUST_GAMMA_DEFAULT_THRESHOLD)
    # gamma_hat=1.3 with 10% error -> robust gamma = 1.1818, above 1.1 threshold
    estimate2 = GammaEstimate(gamma_hat=1.3, delta_estimation_error=0.1)
    assert estimate2.sufficient(ROBUST_GAMMA_DEFAULT_THRESHOLD)


def test_sufficient_default_threshold_is_robust_default():
    estimate = GammaEstimate(gamma_hat=1.3, delta_estimation_error=0.1)
    assert estimate.sufficient() == estimate.sufficient(ROBUST_GAMMA_DEFAULT_THRESHOLD)


def test_zero_estimation_error_means_robust_equals_raw():
    estimate = GammaEstimate(gamma_hat=1.1)
    assert estimate.robust_gamma() == 1.1


def test_high_stakes_threshold_is_stricter():
    assert ROBUST_GAMMA_HIGH_STAKES_THRESHOLD > ROBUST_GAMMA_DEFAULT_THRESHOLD


def test_delta_from_gamma():
    delta = Delta.from_gamma(gamma=1.5, energy_gap=2.0)
    assert delta.value == 3.0


def test_ges_compute_and_trigger():
    ges = GES.compute(governed_kl_integral=0.5, ungoverned_kl_integral=1.0)
    assert ges.score == 0.5
    assert not ges.triggers_specification_update(theta=0.3)
    assert ges.triggers_specification_update(theta=0.6)


def test_ges_governance_made_things_worse():
    ges = GES.compute(governed_kl_integral=1.5, ungoverned_kl_integral=1.0)
    assert ges.score < 0


def test_ges_rejects_zero_baseline():
    with pytest.raises(ValueError):
        GES.compute(governed_kl_integral=0.5, ungoverned_kl_integral=0.0)


def test_eef_zones():
    insufficient_gamma = GammaEstimate(gamma_hat=0.5)
    sufficient_gamma = GammaEstimate(gamma_hat=2.0)

    optimal_eef = EEF.compute(cost_of_pre_node=1.0, max_sustainable_cost=2.0)
    over_eef = EEF.compute(cost_of_pre_node=3.0, max_sustainable_cost=2.0)

    assert optimal_eef.zone(insufficient_gamma) == EEFZone.INSUFFICIENT
    assert optimal_eef.zone(sufficient_gamma) == EEFZone.OPTIMAL
    assert over_eef.zone(sufficient_gamma) == EEFZone.OVER_GOVERNANCE


def test_eef_rejects_zero_max_cost():
    with pytest.raises(ValueError):
        EEF.compute(cost_of_pre_node=1.0, max_sustainable_cost=0.0)


def test_assurance_level_string_values():
    assert AssuranceLevel.HIGH.value == "HIGH"
    assert AssuranceLevel.MEDIUM.value == "MEDIUM"
    assert AssuranceLevel.LOW.value == "LOW"


@pytest.mark.parametrize(
    "f1, f2, expected",
    [
        (False, F2Modification.FULL, AssuranceLevel.LOW),
        (False, F2Modification.PARTIAL, AssuranceLevel.LOW),
        (False, F2Modification.INDIRECT, AssuranceLevel.LOW),
        (False, F2Modification.NONE, AssuranceLevel.LOW),
        (True, F2Modification.FULL, AssuranceLevel.HIGH),
        (True, F2Modification.PARTIAL, AssuranceLevel.MEDIUM),
        (True, F2Modification.INDIRECT, AssuranceLevel.MEDIUM),
        (True, F2Modification.NONE, AssuranceLevel.LOW),
    ],
)
def test_assurance_basis_derived_level_full_table(f1, f2, expected):
    basis = AssuranceBasis(f1_pre_commitment=f1, f2_modification=f2)
    assert basis.derived_level == expected


def test_assurance_basis_logit_adjustment_is_high():
    # Concrete spec example: logit adjustment before sampling -- F1 yes, F2 yes -> HIGH.
    basis = AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.FULL)
    assert basis.derived_level == AssuranceLevel.HIGH


def test_assurance_basis_system_prompt_is_medium():
    # Concrete spec example: system prompt -- F1 yes, F2 partial -> MEDIUM.
    basis = AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.PARTIAL)
    assert basis.derived_level == AssuranceLevel.MEDIUM


def test_assurance_basis_output_filtering_is_low():
    # Concrete spec example: output filtering (post-generation) -- F1 no -> LOW.
    basis = AssuranceBasis(f1_pre_commitment=False, f2_modification=F2Modification.NONE)
    assert basis.derived_level == AssuranceLevel.LOW


def test_beta_is_a_bare_value_holder():
    beta = Beta(value=2.5)
    assert beta.value == 2.5


def test_threshold_construction():
    threshold = Threshold(name="custom", value=0.42, unit="nats")
    assert threshold.name == "custom"
    assert threshold.value == 0.42
    assert threshold.unit == "nats"


def test_threshold_default_unit_is_empty_string():
    threshold = Threshold(name="dimensionless", value=1.1)
    assert threshold.unit == ""


def test_gamma_monitoring_threshold_derives_from_existing_constant():
    assert GAMMA_MONITORING_THRESHOLD.value == ROBUST_GAMMA_DEFAULT_THRESHOLD


def test_jacobian_red_flag_threshold_value():
    assert JACOBIAN_RED_FLAG_THRESHOLD.value == 0.05


def test_kl_monitoring_threshold_value_and_unit():
    assert KL_MONITORING_THRESHOLD.value == 0.15
    assert KL_MONITORING_THRESHOLD.unit == "nats"
