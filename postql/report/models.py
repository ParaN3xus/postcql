from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..codeql_sarif import CodeQLResultRow


@dataclass(slots=True)
class TriggerPathItem:
    file_path: str
    start_line: int
    message: str
    end_line: int | None = None


@dataclass(slots=True)
class HypothesisValidationStep:
    message: str
    evidence: list[TriggerPathItem] = field(default_factory=list)


@dataclass(slots=True)
class SingleFindingReport:
    verdict: Literal["real", "false_positive", "uncertain"]
    severity: Literal["low", "medium", "high", "critical"]
    explanation: str
    initial_hypothesis: str
    hypothesis_validation: list[HypothesisValidationStep] | Literal["none"]
    triggerability: str
    trigger_path: list[TriggerPathItem] | Literal["none"]
    impact: str
    remediation: str
    raw_row: CodeQLResultRow | None = None
