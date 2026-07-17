from vsl_core.exceptions import (
    AutomationDeniedException,
    CatalogValidationError,
    ConformanceError,
    InvariantViolation,
    LedgerIntegrityError,
    VSLError,
)


def test_automation_denied_is_a_vsl_error():
    exc = AutomationDeniedException(reason="Gamma below threshold", identity_key="id-1")
    assert isinstance(exc, VSLError)
    assert isinstance(exc, Exception)
    assert exc.reason == "Gamma below threshold"
    assert exc.identity_key == "id-1"
    assert "Gamma below threshold" in str(exc)
    assert "id-1" in str(exc)


def test_automation_denied_defaults():
    exc = AutomationDeniedException(reason="r", identity_key="k")
    assert exc.instance_id is None
    assert exc.timestamp > 0


def test_automation_denied_is_actually_raisable_and_catchable():
    try:
        raise AutomationDeniedException(reason="denied", identity_key="k")
    except AutomationDeniedException as caught:
        assert caught.reason == "denied"
    else:
        raise AssertionError("expected AutomationDeniedException to be raised")


def test_invariant_violation_is_subclass_of_automation_denied():
    exc = InvariantViolation(reason="violated", identity_key="k", invariant_name="inv-1")
    assert isinstance(exc, AutomationDeniedException)
    assert isinstance(exc, VSLError)
    assert exc.invariant_name == "inv-1"


def test_invariant_violation_caught_by_generic_automation_denied_handler():
    caught_type = None
    try:
        raise InvariantViolation(reason="violated", identity_key="k", invariant_name="inv-1")
    except AutomationDeniedException as caught:
        caught_type = type(caught)
    assert caught_type is InvariantViolation


def test_invariant_violation_distinguishable_from_plain_automation_denied():
    plain = AutomationDeniedException(reason="fallback exhausted", identity_key="k")
    invariant = InvariantViolation(reason="violated", identity_key="k", invariant_name="inv-1")
    assert not isinstance(plain, InvariantViolation)
    assert isinstance(invariant, InvariantViolation)


def test_other_exceptions_are_vsl_errors_and_distinct():
    assert issubclass(LedgerIntegrityError, VSLError)
    assert issubclass(CatalogValidationError, VSLError)
    assert issubclass(ConformanceError, VSLError)
    assert not issubclass(LedgerIntegrityError, AutomationDeniedException)
    assert not issubclass(CatalogValidationError, AutomationDeniedException)
    assert not issubclass(ConformanceError, AutomationDeniedException)
