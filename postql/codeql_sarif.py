# type: ignore
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import sarif_schema_models
from .sarif_schema_models import Location, ReportingDescriptor, Result, Run, SarifLog


@dataclass(slots=True)
class SourceLocation:
    line: int
    column: int


@dataclass(slots=True)
class SupportingLocation:
    file_path: str
    start: SourceLocation
    end: SourceLocation
    message: str
    location_id: int | None = None


@dataclass(slots=True)
class CodeFlowStep:
    file_path: str
    start: SourceLocation
    end: SourceLocation
    message: str


@dataclass(slots=True)
class CodeFlowPath:
    thread_flow_index: int
    steps: list[CodeFlowStep] = field(default_factory=list)


@dataclass(slots=True)
class CodeQLResultRow:
    row_index: int
    rule_name: str
    rule_description: str
    rule_full_description: str
    rule_precision: str | None
    rule_problem_severity: str | None
    rule_security_severity: str | None
    severity: str
    message: str
    relative_file_path: str
    start: SourceLocation
    end: SourceLocation
    related_locations: list[SupportingLocation] = field(default_factory=list)
    code_flows: list[CodeFlowPath] = field(default_factory=list)

    def resolved_path(self, project_root: Path) -> Path:
        return project_root / self.relative_file_path.lstrip("/")


def _normalized_file_path(uri: str | None) -> str:
    if uri is None:
        return "/unknown"
    return "/" + uri.lstrip("/")


def _message_text(message: object) -> str:
    root: object = getattr(message, "root", None)
    if root is not None:
        text: object = getattr(root, "text", None)
        if isinstance(text, str):
            return text
    text: object = getattr(message, "text", None)
    if isinstance(text, str):
        return text
    return ""


def _physical_location(location: Location) -> object:
    return location.physicalLocation.root


def _region_start(location: Location) -> SourceLocation:
    region = _physical_location(location).region
    start_line: int = int(region.startLine or 1)
    start_column: int = int(region.startColumn or 1)
    return SourceLocation(line=start_line, column=start_column)


def _region_end(location: Location) -> SourceLocation:
    region = _physical_location(location).region
    end_line: int = int(region.endLine or region.startLine or 1)
    end_column: int = int(region.endColumn or region.startColumn or 1)
    return SourceLocation(line=end_line, column=end_column)


def _supporting_location(location: Location) -> SupportingLocation:
    physical_location = _physical_location(location)
    return SupportingLocation(
        file_path=_normalized_file_path(physical_location.artifactLocation.uri),
        start=_region_start(location),
        end=_region_end(location),
        message=_message_text(location.message),
        location_id=location.id,
    )


def _code_flow_step(location: Location) -> CodeFlowStep:
    physical_location = _physical_location(location)
    return CodeFlowStep(
        file_path=_normalized_file_path(physical_location.artifactLocation.uri),
        start=_region_start(location),
        end=_region_end(location),
        message=_message_text(location.message),
    )


def _property_value(rule: ReportingDescriptor | None, key: str) -> str | None:
    if rule is None or rule.properties is None or rule.properties.model_extra is None:
        return None
    value: object = rule.properties.model_extra.get(key)
    return value if isinstance(value, str) else None


def _rule_for_result(run: Run, result: Result) -> ReportingDescriptor | None:
    rules = run.tool.driver.rules or []
    if result.ruleIndex is not None and 0 <= result.ruleIndex < len(rules):
        return rules[result.ruleIndex]
    if result.ruleId is None:
        return None
    for rule in rules:
        if rule.id == result.ruleId:
            return rule
    return None


def _result_severity(rule: ReportingDescriptor | None, result: Result) -> str:
    problem_severity: str | None = _property_value(rule, "problem.severity")
    if problem_severity is not None:
        return problem_severity
    level: object = result.level
    if hasattr(level, "value") and isinstance(level.value, str):
        return level.value
    if isinstance(level, str):
        return level
    if rule is not None and rule.defaultConfiguration is not None:
        default_level: object = rule.defaultConfiguration.level
        if hasattr(default_level, "value") and isinstance(default_level.value, str):
            return default_level.value
        if isinstance(default_level, str):
            return default_level
    return "warning"


def parse_sarif_result(row_index: int, run: Run, result: Result) -> CodeQLResultRow:
    if not result.locations:
        raise ValueError(f"SARIF result {row_index} does not have a primary location")
    primary_location: Location = result.locations[0]
    rule: ReportingDescriptor | None = _rule_for_result(run=run, result=result)
    rule_name: str = (
        (rule.name if rule is not None else None)
        or (rule.id if rule is not None else None)
        or result.ruleId
        or "unknown-rule"
    )
    short_description: str = (
        rule.shortDescription.text
        if rule is not None and rule.shortDescription is not None
        else ""
    )
    full_description: str = (
        rule.fullDescription.text
        if rule is not None and rule.fullDescription is not None
        else ""
    )
    rule_description: str = (
        short_description or _property_value(rule, "description") or full_description
    )
    rule_full_description: str = full_description or rule_description
    related_locations: list[SupportingLocation] = [
        _supporting_location(location)
        for location in (result.relatedLocations or [])
        if location.physicalLocation is not None
        and location.physicalLocation.root.artifactLocation is not None
        and location.physicalLocation.root.region is not None
    ]
    code_flows: list[CodeFlowPath] = []
    for code_flow in result.codeFlows or []:
        for thread_flow_index, thread_flow in enumerate(code_flow.threadFlows or []):
            steps: list[CodeFlowStep] = []
            for thread_flow_location in thread_flow.locations or []:
                location = thread_flow_location.location
                if (
                    location is None
                    or location.physicalLocation is None
                    or location.physicalLocation.root.artifactLocation is None
                    or location.physicalLocation.root.region is None
                ):
                    continue
                steps.append(_code_flow_step(location))
            if steps:
                code_flows.append(
                    CodeFlowPath(
                        thread_flow_index=thread_flow_index,
                        steps=steps,
                    )
                )

    return CodeQLResultRow(
        row_index=row_index,
        rule_name=rule_name,
        rule_description=rule_description,
        rule_full_description=rule_full_description,
        rule_precision=_property_value(rule, "precision"),
        rule_problem_severity=_property_value(rule, "problem.severity"),
        rule_security_severity=_property_value(rule, "security-severity"),
        severity=_result_severity(rule=rule, result=result),
        message=_message_text(result.message),
        relative_file_path=_normalized_file_path(
            _physical_location(primary_location).artifactLocation.uri
        ),
        start=_region_start(primary_location),
        end=_region_end(primary_location),
        related_locations=related_locations,
        code_flows=code_flows,
    )


def read_codeql_sarif(sarif_path: Path) -> list[CodeQLResultRow]:
    SarifLog.model_rebuild(_types_namespace=vars(sarif_schema_models), force=True)
    sarif_log = SarifLog.model_validate(json.loads(sarif_path.read_text()))
    if not sarif_log.runs:
        return []
    run: Run = sarif_log.runs[0]
    return [
        parse_sarif_result(row_index=row_index, run=run, result=result)
        for row_index, result in enumerate(run.results or [])
    ]
