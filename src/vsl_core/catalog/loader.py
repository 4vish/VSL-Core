"""Loader for the Drift Class (DC) / Stabilisation Operator (SO) / Legion
detection-heuristic catalog (Paper 5: "Toward a Basis Representation of
Drift Forensics").

This module surfaces, deliberately and prominently, three real
data-quality findings in the source JSON rather than silently fixing them
-- see validate(). Do not trust drift_classes.json's own
metadata.total_drift_classes field; compute counts from the data itself.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

CATEGORIES: tuple[str, ...] = ("external", "internal", "systemic", "linguistic", "authority")


@dataclass(frozen=True)
class DriftClass:
    code: str
    name: str
    category: str
    tier: str
    operational_definition: str
    primary_legions: tuple[str, ...]
    primary_so: str
    contraindications: str | None = None
    notes: str | None = None
    references: str = ""

    @property
    def primary_so_codes(self) -> tuple[str, ...]:
        """Split a possibly-compound primary_so string (e.g. "SO-7, SO-8"
        or "SO-9 (external oversight)") into individual SO codes.
        """
        codes = []
        for part in self.primary_so.split(","):
            part = part.strip()
            if "(" in part:
                part = part.split("(")[0].strip()
            if part:
                codes.append(part)
        return tuple(codes)


@dataclass(frozen=True)
class StabilisationOperator:
    code: str
    name: str
    proposed_function: str
    primary_dc_targets: tuple[str, ...]
    contraindicated_on: tuple[str, ...]


@dataclass(frozen=True)
class CompoundDriftMode:
    code: str
    name: str
    components: tuple[str, ...]
    mechanism: str
    confidence: str


@dataclass(frozen=True)
class BoundaryCase:
    key: str
    classes: tuple[str, ...]
    distinguishing_test: str
    misdiagnosis_risk: str
    why_it_matters: str


@dataclass(frozen=True)
class CriticalContraindication:
    key: str
    prohibition: str
    predicted_failure_state: str
    description: str
    observable_signature: str


@dataclass(frozen=True)
class CaseStudy:
    key: str
    primary_dc: str
    secondary_dc: tuple[str, ...]
    compound_mode: str
    proposed_so: str
    confidence: str
    reference: str


@dataclass(frozen=True)
class LegionHeuristic:
    pattern_type: str
    patterns: tuple[str, ...]
    confidence: str
    description: str


@dataclass(frozen=True)
class Legion:
    code: str
    name: str
    heuristics: tuple[LegionHeuristic, ...]


@dataclass(frozen=True)
class LegionEntry:
    code: str
    name: str
    tier: str
    category: str
    legions: tuple[Legion, ...] = field(default_factory=tuple)


def _read_json(filename: str) -> dict[str, Any]:
    raw = resources.files(__package__).joinpath(filename).read_text(encoding="utf-8")
    return json.loads(raw)


@functools.lru_cache(maxsize=1)
def _raw_drift_classes() -> dict[str, Any]:
    return _read_json("drift_classes.json")


@functools.lru_cache(maxsize=1)
def _raw_legion_patterns() -> dict[str, Any]:
    return _read_json("legion_patterns.json")


def _drift_class_from_dict(code: str, data: dict[str, Any]) -> DriftClass:
    return DriftClass(
        code=data.get("code", code),
        name=data["name"],
        category=data["category"],
        tier=data["tier"],
        operational_definition=data["operational_definition"],
        primary_legions=tuple(data.get("primary_legions", ())),
        primary_so=data["primary_so"],
        contraindications=data.get("contraindications"),
        notes=data.get("notes"),
        references=data.get("references", ""),
    )


@functools.lru_cache(maxsize=1)
def load_drift_classes() -> dict[str, DriftClass]:
    """Flatten all five categories into one dict keyed by DC code.

    Real count: 45 (external=15, internal=19, systemic=7, linguistic=3,
    authority=1) -- NOT the 36 claimed by metadata.total_drift_classes.
    """
    raw = _raw_drift_classes()
    result: dict[str, DriftClass] = {}
    for category in CATEGORIES:
        for code, entry in raw["drift_classes"].get(category, {}).items():
            result[code] = _drift_class_from_dict(code, entry)
    return result


def get_drift_class(code: str) -> DriftClass:
    classes = load_drift_classes()
    try:
        return classes[code]
    except KeyError:
        raise KeyError(f"No Drift Class with code {code!r}.") from None


def classes_by_tier(tier: str) -> list[DriftClass]:
    return [dc for dc in load_drift_classes().values() if dc.tier == tier]


@functools.lru_cache(maxsize=1)
def load_stabilisation_operators() -> dict[str, StabilisationOperator]:
    """10 entries: SO-1..SO-9 plus SO-8b (not a clean SO-1..SO-10
    sequence -- see validate()).
    """
    raw = _raw_drift_classes()
    result: dict[str, StabilisationOperator] = {}
    for code, data in raw["stabilisation_operators"].items():
        result[code] = StabilisationOperator(
            code=data.get("code", code),
            name=data["name"],
            proposed_function=data["proposed_function"],
            primary_dc_targets=tuple(data.get("primary_dc_targets", ())),
            contraindicated_on=tuple(data.get("contraindicated_on", ())),
        )
    return result


def get_stabilisation_operator(code: str) -> StabilisationOperator:
    operators = load_stabilisation_operators()
    try:
        return operators[code]
    except KeyError:
        raise KeyError(f"No Stabilisation Operator with code {code!r}.") from None


@functools.lru_cache(maxsize=1)
def load_compound_drift_modes() -> dict[str, CompoundDriftMode]:
    raw = _raw_drift_classes()
    result: dict[str, CompoundDriftMode] = {}
    for code, data in raw.get("compound_drift_modes", {}).items():
        result[code] = CompoundDriftMode(
            code=code,
            name=data["name"],
            components=tuple(data.get("components", ())),
            mechanism=data["mechanism"],
            confidence=data["confidence"],
        )
    return result


@functools.lru_cache(maxsize=1)
def load_boundary_cases() -> dict[str, BoundaryCase]:
    raw = _raw_drift_classes()
    result: dict[str, BoundaryCase] = {}
    for key, data in raw.get("boundary_cases", {}).items():
        result[key] = BoundaryCase(
            key=key,
            classes=tuple(data.get("classes", ())),
            distinguishing_test=data["distinguishing_test"],
            misdiagnosis_risk=data["misdiagnosis_risk"],
            why_it_matters=data["why_it_matters"],
        )
    return result


@functools.lru_cache(maxsize=1)
def load_critical_contraindications() -> dict[str, CriticalContraindication]:
    raw = _raw_drift_classes()
    result: dict[str, CriticalContraindication] = {}
    for key, data in raw.get("critical_contraindications", {}).items():
        result[key] = CriticalContraindication(
            key=key,
            prohibition=data["prohibition"],
            predicted_failure_state=data["predicted_failure_state"],
            description=data["description"],
            observable_signature=data["observable_signature"],
        )
    return result


@functools.lru_cache(maxsize=1)
def load_case_studies() -> dict[str, CaseStudy]:
    raw = _raw_drift_classes()
    result: dict[str, CaseStudy] = {}
    for key, data in raw.get("case_studies", {}).items():
        result[key] = CaseStudy(
            key=key,
            primary_dc=data["primary_dc"],
            secondary_dc=tuple(data.get("secondary_dc", ())),
            compound_mode=data["compound_mode"],
            proposed_so=data["proposed_so"],
            confidence=data["confidence"],
            reference=data["reference"],
        )
    return result


@functools.lru_cache(maxsize=1)
def load_monitoring_frequency() -> dict[str, tuple[str, ...]]:
    raw = _raw_drift_classes()
    return {label: tuple(codes) for label, codes in raw.get("monitoring_frequency_by_dc", {}).items()}


TIER_DEFINITIONS: dict[str, str] = dict(_raw_drift_classes()["tier_definitions"])


def _legion_from_dict(code: str, data: dict[str, Any]) -> Legion:
    heuristics = tuple(
        LegionHeuristic(
            pattern_type=h["pattern_type"],
            patterns=tuple(h.get("patterns", ())),
            confidence=h["confidence"],
            description=h["description"],
        )
        for h in data.get("heuristics", [])
    )
    return Legion(code=code, name=data["name"], heuristics=heuristics)


@functools.lru_cache(maxsize=1)
def load_legion_patterns() -> dict[str, LegionEntry]:
    """46 top-level entries: the 45 real DC codes plus one orphan,
    CLUSTER-HANDOVER, which has no corresponding entry in
    drift_classes.json -- see validate().
    """
    raw = _raw_legion_patterns()
    result: dict[str, LegionEntry] = {}
    for code, data in raw.items():
        legions = tuple(
            _legion_from_dict(legion_code, legion_data) for legion_code, legion_data in data.get("legions", {}).items()
        )
        result[code] = LegionEntry(
            code=code,
            name=data["name"],
            tier=data["tier"],
            category=data["category"],
            legions=legions,
        )
    return result


@functools.lru_cache(maxsize=1)
def only_validated_heuristics() -> dict[str, list[tuple[str, LegionHeuristic]]]:
    """Filter to heuristics with confidence in (HIGH, MEDIUM) only -- the
    function a cautious integrator should reach for, since 106 of 113
    heuristics in the source data are self-labeled SPECULATIVE.

    Keyed by the top-level code (DC or CLUSTER-HANDOVER); each value is a
    list of (legion_code, heuristic) pairs so callers can still tell which
    Legion within that entry produced the finding.
    """
    result: dict[str, list[tuple[str, LegionHeuristic]]] = {}
    for code, entry in load_legion_patterns().items():
        matches = [
            (legion.code, heuristic)
            for legion in entry.legions
            for heuristic in legion.heuristics
            if heuristic.confidence in ("HIGH", "MEDIUM")
        ]
        if matches:
            result[code] = matches
    return result


def validate() -> list[str]:
    """Human-readable data-quality findings, computed at call time from the
    real data -- never fixed, only surfaced. Returns an empty list only if
    a future revision of the source JSON genuinely resolves every finding
    below.
    """
    findings: list[str] = []

    raw = _raw_drift_classes()
    drift_classes = load_drift_classes()
    real_count = len(drift_classes)
    claimed_count = raw.get("metadata", {}).get("total_drift_classes")
    if claimed_count != real_count:
        by_category = {
            category: len(raw["drift_classes"].get(category, {})) for category in CATEGORIES
        }
        breakdown = ", ".join(f"{cat}={n}" for cat, n in by_category.items())
        findings.append(
            f"metadata.total_drift_classes claims {claimed_count} but the real "
            f"computed count across all five categories ({breakdown}) is "
            f"{real_count}. Do not trust the metadata field."
        )

    legion_patterns = load_legion_patterns()
    orphans = sorted(set(legion_patterns) - set(drift_classes))
    if orphans:
        findings.append(
            f"legion_patterns.json contains {orphans} with no corresponding "
            f"entry in drift_classes.json. Treat as a real finding worth "
            f"promoting to a formal DC in a future spec revision, not a data "
            f"error to silently drop."
        )

    empty_legion_codes = sorted(code for code, entry in legion_patterns.items() if not entry.legions)
    if empty_legion_codes:
        findings.append(
            f"{len(empty_legion_codes)} drift classes have zero Legion "
            f"detection heuristics defined at all: {', '.join(empty_legion_codes)}. "
            f"This is a coverage gap, not a data error -- these are "
            f"predominantly tier B/C/D (theoretical/hypothesised/limit) "
            f"classes where no detection heuristic has been proposed yet. "
            f"only_validated_heuristics() naturally excludes them too, since "
            f"there is nothing to filter."
        )

    mismatches = []
    for code in sorted(set(legion_patterns) & set(drift_classes)):
        dc = drift_classes[code]
        entry = legion_patterns[code]
        if (dc.name, dc.tier, dc.category) != (entry.name, entry.tier, entry.category):
            mismatches.append(code)
    if mismatches:
        findings.append(
            f"name/tier/category mismatch between drift_classes.json and "
            f"legion_patterns.json for: {', '.join(mismatches)}."
        )

    so_codes = sorted(load_stabilisation_operators())
    if so_codes and not all(c.startswith("SO-") for c in so_codes):
        findings.append(f"Unexpected Stabilisation Operator code format among: {so_codes}.")
    elif len(so_codes) != 10 or "SO-8b" not in so_codes:
        findings.append(
            f"Expected 10 Stabilisation Operators (SO-1..SO-9 plus the "
            f"lettered variant SO-8b, not a clean SO-1..SO-10 sequence); "
            f"found {len(so_codes)}: {so_codes}."
        )

    return findings
