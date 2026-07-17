from vsl_core.catalog import loader


EXPECTED_EMPTY_LEGION_CODES = {
    "DC-S1", "DC-S2", "DC-S3", "DC-S4", "DC-S5", "DC-S6",
    "DC-L1", "DC-L2", "DC-L3", "DC-A1",
}


def test_load_drift_classes_exact_count():
    assert len(loader.load_drift_classes()) == 45


def test_load_drift_classes_category_breakdown():
    dcs = loader.load_drift_classes()
    counts = {}
    for dc in dcs.values():
        counts[dc.category] = counts.get(dc.category, 0) + 1
    assert counts == {"external": 15, "internal": 19, "systemic": 7, "linguistic": 3, "authority": 1}


def test_get_drift_class_known_code():
    dc = loader.get_drift_class("DC-E1")
    assert dc.name == "Threshold Assault"
    assert dc.tier == "A"


def test_get_drift_class_unknown_code_raises_keyerror():
    try:
        loader.get_drift_class("DC-DOES-NOT-EXIST")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_classes_by_tier():
    tier_a = loader.classes_by_tier("A")
    assert all(dc.tier == "A" for dc in tier_a)
    assert len(tier_a) > 0


def test_primary_so_codes_splits_compound_string():
    dc = loader.get_drift_class("DC-E2")  # primary_so = "SO-6, SO-4"
    assert dc.primary_so_codes == ("SO-6", "SO-4")


def test_primary_so_codes_strips_parenthetical_annotation():
    dc = loader.get_drift_class("DC-A1")  # primary_so = "SO-9 (external oversight)"
    assert dc.primary_so_codes == ("SO-9",)


def test_load_stabilisation_operators_exact_count_and_codes():
    sos = loader.load_stabilisation_operators()
    assert len(sos) == 10
    assert set(sos) == {
        "SO-1", "SO-2", "SO-3", "SO-4", "SO-5", "SO-6", "SO-7", "SO-8", "SO-8b", "SO-9",
    }


def test_get_stabilisation_operator_unknown_raises():
    try:
        loader.get_stabilisation_operator("SO-DOES-NOT-EXIST")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_load_compound_drift_modes_populates_code_from_dict_key():
    modes = loader.load_compound_drift_modes()
    assert len(modes) == 10
    assert modes["CDM-1"].code == "CDM-1"


def test_load_boundary_cases_count():
    assert len(loader.load_boundary_cases()) == 4


def test_load_critical_contraindications_count():
    assert len(loader.load_critical_contraindications()) == 3


def test_load_case_studies_count():
    assert len(loader.load_case_studies()) == 5


def test_tier_definitions_has_four_tiers():
    assert set(loader.TIER_DEFINITIONS) == {"A", "B", "C", "D"}


def test_load_legion_patterns_exact_count():
    assert len(loader.load_legion_patterns()) == 46


def test_orphan_cluster_handover_has_no_matching_drift_class():
    legions = loader.load_legion_patterns()
    dcs = loader.load_drift_classes()
    assert set(legions) - set(dcs) == {"CLUSTER-HANDOVER"}


def test_empty_legion_drift_classes_exact_set():
    legions = loader.load_legion_patterns()
    empty = {code for code, entry in legions.items() if not entry.legions}
    assert empty == EXPECTED_EMPTY_LEGION_CODES


def test_only_validated_heuristics_exact_total_and_spread():
    validated = loader.only_validated_heuristics()
    total = sum(len(v) for v in validated.values())
    assert total == 7
    assert {code: len(v) for code, v in validated.items()} == {
        "DC-E13": 3,
        "DC-I11": 2,
        "CLUSTER-HANDOVER": 2,
    }


def test_only_validated_heuristics_excludes_speculative():
    validated = loader.only_validated_heuristics()
    for matches in validated.values():
        for _legion_code, heuristic in matches:
            assert heuristic.confidence in ("HIGH", "MEDIUM")


def test_validate_surfaces_metadata_count_bug():
    findings = " ".join(loader.validate())
    assert "claims 36" in findings
    assert "is 45" in findings


def test_validate_surfaces_cluster_handover_orphan():
    findings = " ".join(loader.validate())
    assert "CLUSTER-HANDOVER" in findings


def test_validate_surfaces_empty_legion_coverage_gap():
    findings = " ".join(loader.validate())
    assert "10 drift classes have zero Legion" in findings
    for code in sorted(EXPECTED_EMPTY_LEGION_CODES):
        assert code in findings


def test_validate_does_not_report_cross_file_mismatches_currently():
    # As of the real source data, name/tier/category agree across both
    # files for every shared code -- this test guards against silent
    # future drift if either JSON file is hand-edited without the other.
    findings = " ".join(loader.validate())
    assert "mismatch" not in findings
