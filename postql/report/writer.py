from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import shutil
import subprocess
from pathlib import Path

from ..codeql_csv import CodeQLResultRow
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


def _compile_typst_template(
    template_path: Path,
    output_pdf_path: Path,
    report_json_path: Path,
) -> tuple[bool, str | None, str | None]:
    typst_command: str | None = _find_typst_binary()
    if typst_command is None:
        return False, None, "typst binary not found"

    template_path = template_path.resolve()
    output_pdf_path = output_pdf_path.resolve()
    report_json_path = report_json_path.resolve()
    root_dir = template_path.parents[3]
    report_json_input: str = report_json_path.read_text(encoding="utf-8")
    completed = subprocess.run(
        [
            typst_command,
            "compile",
            str(template_path),
            str(output_pdf_path),
            "--root",
            str(root_dir),
            "--input",
            f"report_json={report_json_input}",
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
        report_json_path=json_path,
    )
    return ReportBundle(
        json_path=json_path,
        pdf_path=pdf_path,
        pdf_generated=pdf_generated,
        typst_command=typst_command,
        pdf_error=pdf_error,
    )
