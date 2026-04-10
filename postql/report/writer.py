from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..codeql_sarif import CodeQLResultRow
from .models import SingleFindingReport

DEFAULT_TYPST_PATHS: tuple[str, ...] = (
    "typst",
    "/home/admin/.cargo/bin/typst",
)


@dataclass(slots=True)
class ReportBundle:
    json_path: Path
    pdf_path: Path
    pdf_generated: bool
    typst_command: str | None
    pdf_error: str | None


def _find_typst_binary() -> str | None:
    for candidate in DEFAULT_TYPST_PATHS:
        resolved: str | None = shutil.which(candidate)
        if resolved:
            return resolved
        candidate_path = Path(candidate)
        if candidate_path.is_file():
            return str(candidate_path)
    return None


def _template_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _workspace_input_path(
    template_path: Path,
    workspace_dir: Path,
) -> tuple[str | None, str | None]:
    workspace_dir = workspace_dir.resolve()
    root_dir = template_path.parents[3]
    try:
        workspace_relative: Path = workspace_dir.relative_to(root_dir)
        return "/" + str(workspace_relative), None
    except ValueError:
        return (
            None,
            f"workspace_dir must be under typst root: "
            f"workspace_dir={workspace_dir} root={root_dir}",
        )


def _compile_typst_template(
    template_path: Path,
    output_pdf_path: Path,
    input_name: str,
    input_json_path: Path,
    workspace_dir: Path,
) -> tuple[bool, str | None, str | None]:
    typst_command: str | None = _find_typst_binary()
    if typst_command is None:
        return False, None, "typst binary not found"

    template_path = template_path.resolve()
    output_pdf_path = output_pdf_path.resolve()
    input_json_path = input_json_path.resolve()
    root_dir = template_path.parents[3]
    workspace_input, workspace_error = _workspace_input_path(
        template_path=template_path,
        workspace_dir=workspace_dir,
    )
    if workspace_error is not None or workspace_input is None:
        return False, typst_command, workspace_error or "invalid workspace input"
    input_json: str = input_json_path.read_text(encoding="utf-8")
    completed = subprocess.run(
        [
            typst_command,
            "compile",
            str(template_path),
            str(output_pdf_path),
            "--root",
            str(root_dir),
            "--input",
            f"{input_name}={input_json}",
            "--input",
            f"workspace_dir={workspace_input}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return (
            False,
            typst_command,
            completed.stderr.strip() or "unknown typst compile error",
        )
    return True, typst_command, None


def write_single_finding_report(
    output_dir: Path,
    row: CodeQLResultRow,
    report: SingleFindingReport,
    workspace_dir: Path,
) -> ReportBundle:
    json_path: Path = output_dir / "report.json"
    pdf_path: Path = output_dir / "report.pdf"
    persisted_report = SingleFindingReport(
        verdict=report.verdict,
        severity=report.severity,
        explanation=report.explanation,
        initial_hypothesis=report.initial_hypothesis,
        hypothesis_validation=report.hypothesis_validation,
        triggerability=report.triggerability,
        trigger_path=report.trigger_path,
        impact=report.impact,
        remediation=report.remediation,
        raw_row=row,
    )

    json_path.write_text(
        json.dumps(asdict(persisted_report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    pdf_generated, typst_command, pdf_error = _compile_typst_template(
        template_path=_template_dir() / "single-report.typ",
        output_pdf_path=pdf_path,
        input_name="report_json",
        input_json_path=json_path,
        workspace_dir=workspace_dir,
    )
    return ReportBundle(
        json_path=json_path,
        pdf_path=pdf_path,
        pdf_generated=pdf_generated,
        typst_command=typst_command,
        pdf_error=pdf_error,
    )


def write_full_report(
    output_dir: Path,
    report_json_paths: list[Path],
    workspace_dir: Path,
) -> ReportBundle:
    json_path: Path = output_dir / "full_report.json"
    pdf_path: Path = output_dir / "full_report.pdf"
    reports: list[Any] = [
        json.loads(report_json_path.read_text(encoding="utf-8"))
        for report_json_path in report_json_paths
    ]
    json_path.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    pdf_generated, typst_command, pdf_error = _compile_typst_template(
        template_path=_template_dir() / "full_report.typ",
        output_pdf_path=pdf_path,
        input_name="reports_json",
        input_json_path=json_path,
        workspace_dir=workspace_dir,
    )
    return ReportBundle(
        json_path=json_path,
        pdf_path=pdf_path,
        pdf_generated=pdf_generated,
        typst_command=typst_command,
        pdf_error=pdf_error,
    )
