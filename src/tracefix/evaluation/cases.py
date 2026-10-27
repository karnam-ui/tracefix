"""Typed, read-only view over a frozen evaluation case set (A6a).

This module implements the Workstream-B-independent part of
`contracts/evaluation.json` (C4, v0.1.0-draft): a typed model of the frozen
candidate pool produced by ``scripts/validate_cases.py``, explicit validation
errors, and deterministic fingerprinting.

Non-finalization
----------------
Loading a case set does **not** finalize C4. Ground truth remains *provisional*
(Q-B7), the primary ``k`` values and file-level requirements (Q-B8/Q-B9) are not
chosen here, and the dataset/contamination policy (Q-B12/D8) is untouched.
The loader never rewrites the pool and never changes inclusion/exclusion policy.

Fingerprint
-----------
The contract defines the case-set fingerprint as ``sha256`` over the sorted list
of ``(case_id, revision)`` pairs plus the evaluation contract version. The
existing pool (and ``scripts/validate_cases.py``) computes this over the
**localizable** cases only, omitting excluded cases. That behavior is preserved
and made explicit here: :meth:`CaseSet.fingerprint` excludes non-localizable
cases by default (``include_excluded=False``), so it reproduces the frozen pool's
recorded value. Whether excluded cases should participate is an open contract
question (Q-B10); it is documented, not decided.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


class EvaluationError(ValueError):
    """A case set could not be read or failed validation."""


class CaseRecord(BaseModel):
    """One evaluation case, mirroring the C4 draft ``case_record`` plus the
    provisional/provenance fields the frozen pool carries."""

    case_id: str = Field(min_length=1)
    repo: str = ""
    revision: str = Field(min_length=1)
    bug_report: str = ""
    ground_truth_files: list[str] = Field(default_factory=list)
    ground_truth_functions: list[str] = Field(default_factory=list)
    localizable: bool
    excluded_reason: str | None = None
    dataset_source: str | None = None
    dataset_instance_id: str | None = None
    fix_commit: str | None = None
    fail_to_pass_tests: list[str] = Field(default_factory=list)
    # Provisional / provenance metadata (not part of the C4 draft schema).
    ground_truth_policy: str | None = None
    pre_cutoff: bool | None = None
    created_at: str | None = None
    validation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_consistency(self) -> CaseRecord:
        if not self.localizable and not self.excluded_reason:
            raise ValueError(f"{self.case_id}: non-localizable case must carry excluded_reason")
        if self.localizable and not self.ground_truth_files:
            raise ValueError(f"{self.case_id}: localizable case must list ground_truth_files")
        if self.localizable and not self.ground_truth_functions:
            raise ValueError(f"{self.case_id}: localizable case must list ground_truth_functions")
        return self

    @property
    def is_provisional_ground_truth(self) -> bool:
        policy = self.ground_truth_policy or ""
        return "provisional" in policy.lower()


class CaseSet(BaseModel):
    """A validated, read-only case set loaded from the frozen candidate pool."""

    contract_version: str
    repo: str | None = None
    dataset_source: str | None = None
    license: str | None = None
    ground_truth_status: str | None = None
    generated_at: str | None = None
    fingerprint_recorded: str | None = None
    counts: dict[str, Any] = Field(default_factory=dict)
    excluded_tally: dict[str, int] = Field(default_factory=dict)
    cases: list[CaseRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> CaseSet:
        ids = [c.case_id for c in self.cases]
        duplicates = sorted({cid for cid in ids if ids.count(cid) > 1})
        if duplicates:
            raise ValueError(f"duplicate case_id(s): {', '.join(duplicates)}")
        return self

    @property
    def localizable(self) -> list[CaseRecord]:
        return [c for c in self.cases if c.localizable]

    @property
    def excluded(self) -> list[CaseRecord]:
        return [c for c in self.cases if not c.localizable]

    @property
    def ground_truth_is_provisional(self) -> bool:
        if "provisional" in (self.ground_truth_status or "").lower():
            return True
        return any(c.is_provisional_ground_truth for c in self.cases)

    def fingerprint(self, *, include_excluded: bool = False) -> str:
        """Deterministic case-set fingerprint (see module docstring)."""
        selected = self.cases if include_excluded else self.localizable
        return fingerprint_cases(selected, self.contract_version)

    def fingerprint_matches_recorded(self) -> bool:
        """True when the recomputed default fingerprint equals the recorded one."""
        if self.fingerprint_recorded is None:
            return False
        return self.fingerprint() == self.fingerprint_recorded


def fingerprint_cases(cases: list[CaseRecord], contract_version: str) -> str:
    """``sha256`` over sorted ``(case_id, revision)`` pairs + contract version.

    Matches ``scripts/validate_cases.py::fingerprint`` exactly, so the same
    inputs reproduce the same value.
    """
    pairs = sorted((c.case_id, c.revision) for c in cases)
    payload = json.dumps([pairs, contract_version], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_POOL_TO_MODEL_KEYS = {
    "evaluation_contract_version": "contract_version",
    "case_set_fingerprint": "fingerprint_recorded",
}


def load_case_set(path: str | Path) -> CaseSet:
    """Load and validate a frozen case set from JSON.

    Raises :class:`EvaluationError` with an explicit message for missing files,
    invalid JSON, missing required fields, duplicate case ids, or inconsistent
    localizable/excluded records. The file is never modified.
    """
    source = Path(path)
    if not source.is_file():
        raise EvaluationError(f"case set not found: {source}")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"invalid JSON in {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise EvaluationError(f"case set must be a JSON object, got {type(raw).__name__}")

    mapped = dict(raw)
    for pool_key, model_key in _POOL_TO_MODEL_KEYS.items():
        if pool_key in mapped:
            mapped[model_key] = mapped.pop(pool_key)

    try:
        return CaseSet.model_validate(mapped)
    except Exception as exc:  # pydantic.ValidationError and friends
        raise EvaluationError(f"invalid case set in {source}: {exc}") from exc
