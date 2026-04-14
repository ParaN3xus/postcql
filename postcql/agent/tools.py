from __future__ import annotations

import fnmatch
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agents import function_tool
from pathspec import PathSpec

from ..codeql_sarif import CodeQLResultRow
from ..report import SingleFindingReport, write_single_finding_report
from ..run_artifacts import RunArtifacts
from .prompting import SUBMIT_TRIAGE_REPORT_DOC

DEFAULT_PAGE_SIZE: int = 32
DEFAULT_SEARCH_RESULTS: int = 32


def _format_source_lines(
    lines: list[str],
    start_line: int,
    end_line: int,
) -> list[str]:
    return [
        f"{line_number:6d}: {lines[line_number - 1]}"
        for line_number in range(start_line, end_line + 1)
    ]


def _build_source_ignore_spec(source_dir: Path) -> PathSpec | None:
    gitignore_path: Path = source_dir / ".gitignore"
    if not gitignore_path.is_file():
        return None
    lines: list[str] = gitignore_path.read_text(encoding="utf-8").splitlines()
    return PathSpec.from_lines("gitwildmatch", lines)


def _is_ignored_by_source_gitignore(
    path: Path,
    source_dir: Path,
    ignore_spec: PathSpec | None,
) -> bool:
    if ignore_spec is None:
        return False
    relative_path: str = path.relative_to(source_dir).as_posix()
    if path.is_dir():
        relative_path += "/"
    return ignore_spec.match_file(relative_path)


def _read_text_lines(path: Path) -> list[str]:
    raw_bytes: bytes = path.read_bytes()
    if b"\x00" in raw_bytes:
        raise ValueError(f"Refusing to read non-text file: {path}")
    raw_lines: list[bytes] = raw_bytes.split(b"\n")
    if raw_lines and raw_lines[-1] == b"":
        raw_lines.pop()
    try:
        return [raw_line.decode("utf-8").rstrip("\r") for raw_line in raw_lines]
    except UnicodeDecodeError as exc:
        raise ValueError(f"Refusing to read non-UTF-8 text file: {path}") from exc


def _resolve_source_path(source_dir: Path, file_path: str) -> Path:
    source_root: Path = source_dir.resolve()
    input_path: Path = Path(file_path)
    if input_path.is_absolute():
        resolved_path: Path = input_path.resolve()
    else:
        normalized_relative_path: str = file_path.lstrip("/")
        resolved_path = (source_dir / normalized_relative_path).resolve()
    try:
        resolved_path.relative_to(source_root)
    except ValueError as exc:
        raise ValueError(f"File path escapes source dir: {file_path}") from exc
    return resolved_path


def _validate_page_size(value: int, field_name: str) -> None:
    if value < 1:
        raise ValueError(f"{field_name} must be >= 1")


def _validate_report_path_item(
    source_dir: Path,
    item: Any,
    field_name: str,
    item_index: int,
) -> None:
    if isinstance(item, dict):
        file_path: object = item.get("file_path")
        start_line: object = item.get("start_line")
        end_line_raw: object = item.get("end_line")
    else:
        file_path = getattr(item, "file_path", None)
        start_line = getattr(item, "start_line", None)
        end_line_raw = getattr(item, "end_line", None)
    if not isinstance(file_path, str):
        raise ValueError(f"{field_name}[{item_index}].file_path must be a string")
    if Path(file_path).is_absolute():
        raise ValueError(
            f"{field_name}[{item_index}].file_path must be source-relative, "
            f"not absolute: {file_path}"
        )
    if not isinstance(start_line, int):
        raise ValueError(f"{field_name}[{item_index}].start_line must be an integer")
    end_line: int
    if end_line_raw is None:
        end_line = start_line
    elif isinstance(end_line_raw, int):
        end_line = end_line_raw
    else:
        raise ValueError(f"{field_name}[{item_index}].end_line must be an integer")
    if start_line < 1:
        raise ValueError(f"{field_name}[{item_index}].start_line must be >= 1")
    if end_line < start_line:
        raise ValueError(
            f"{field_name}[{item_index}] has invalid range: "
            f"start_line={start_line} end_line={end_line}"
        )

    resolved_path: Path = _resolve_source_path(
        source_dir=source_dir,
        file_path=file_path,
    )
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Source file not found: {resolved_path}")
    total_lines: int = len(_read_text_lines(resolved_path))
    if start_line > total_lines or end_line > total_lines:
        raise ValueError(
            f"{field_name}[{item_index}] range {start_line}-{end_line} exceeds "
            f"file length {total_lines}: {file_path}"
        )


def _validate_report_source_references(
    report: SingleFindingReport,
    source_dir: Path,
) -> None:
    hypothesis_validation: object = report.hypothesis_validation
    if isinstance(hypothesis_validation, list):
        for step_index, step in enumerate(hypothesis_validation):
            if isinstance(step, dict):
                evidence: object = step.get("evidence")
            else:
                evidence = getattr(step, "evidence", None)
            if isinstance(evidence, list):
                for evidence_index, item in enumerate(evidence):
                    _validate_report_path_item(
                        source_dir=source_dir,
                        item=item,
                        field_name=(f"hypothesis_validation[{step_index}].evidence"),
                        item_index=evidence_index,
                    )

    trigger_path: object = report.trigger_path
    if isinstance(trigger_path, list):
        for item_index, item in enumerate(trigger_path):
            _validate_report_path_item(
                source_dir=source_dir,
                item=item,
                field_name="trigger_path",
                item_index=item_index,
            )


def build_read_source_context_tool(source_dir: Path) -> Any:
    @function_tool
    def read_source_context(
        file_path: str,
        center_line: int,
        context_lines: int = 20,
    ) -> str:
        """Read source context around a line from the configured source directory."""
        if center_line < 1:
            raise ValueError("center_line must be >= 1")
        if context_lines < 0:
            raise ValueError("context_lines must be >= 0")

        resolved_path: Path = _resolve_source_path(
            source_dir=source_dir,
            file_path=file_path,
        )
        if not resolved_path.is_file():
            raise FileNotFoundError(f"Source file not found: {resolved_path}")

        lines: list[str] = _read_text_lines(resolved_path)
        start_line: int = max(1, center_line - context_lines)
        end_line: int = min(len(lines), center_line + context_lines)

        rendered_lines: list[str] = _format_source_lines(
            lines=lines,
            start_line=start_line,
            end_line=end_line,
        )
        header: str = (
            f"file={resolved_path}\n"
            f"requested_line={center_line}\n"
            f"shown_range={start_line}-{end_line}"
        )
        return header + "\n" + "\n".join(rendered_lines)

    return read_source_context


def build_read_source_span_tool(source_dir: Path) -> Any:
    @function_tool
    def read_source_span(
        file_path: str,
        start_line: int,
        end_line: int,
    ) -> str:
        """Read an explicit source line range from the configured source directory."""
        if start_line < 1:
            raise ValueError("start_line must be >= 1")
        if end_line < start_line:
            raise ValueError("end_line must be >= start_line")

        resolved_path: Path = _resolve_source_path(
            source_dir=source_dir,
            file_path=file_path,
        )
        if not resolved_path.is_file():
            raise FileNotFoundError(f"Source file not found: {resolved_path}")

        lines: list[str] = _read_text_lines(resolved_path)
        bounded_end_line: int = min(len(lines), end_line)
        rendered_lines: list[str] = _format_source_lines(
            lines=lines,
            start_line=start_line,
            end_line=bounded_end_line,
        )
        header: str = (
            f"file={resolved_path}\n"
            f"requested_range={start_line}-{end_line}\n"
            f"shown_range={start_line}-{bounded_end_line}"
        )
        return header + "\n" + "\n".join(rendered_lines)

    return read_source_span


def build_search_source_text_tool(source_dir: Path) -> Any:
    ignore_spec: PathSpec | None = _build_source_ignore_spec(source_dir)

    @function_tool
    def search_source_text(
        pattern: str,
        glob_pattern: str = "*",
        page_offset: int = 0,
        page_size: int = DEFAULT_SEARCH_RESULTS,
    ) -> str:
        """Search source files for plain text and return paged matching lines."""
        if not pattern:
            raise ValueError("pattern must not be empty")
        if page_offset < 0:
            raise ValueError("page_offset must be >= 0")
        _validate_page_size(page_size, "page_size")

        matches: list[str] = []
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            if _is_ignored_by_source_gitignore(path, source_dir, ignore_spec):
                continue
            relative_path: str = "/" + str(path.relative_to(source_dir))
            if not fnmatch.fnmatch(relative_path, glob_pattern):
                continue

            try:
                lines: list[str] = _read_text_lines(path)
            except ValueError:
                continue

            for line_number, line_text in enumerate(lines, start=1):
                if pattern in line_text:
                    matches.append(f"{relative_path}:{line_number}: {line_text}")
        if not matches:
            return "No matches found."

        if page_offset >= len(matches):
            raise ValueError("page_offset is out of range for search results")
        page_matches: list[str] = matches[page_offset : page_offset + page_size]
        has_more: bool = page_offset + page_size < len(matches)
        next_offset: int | None = None
        if has_more:
            next_offset = page_offset + len(page_matches)
        header: str = (
            f"pattern={pattern}\n"
            f"glob_pattern={glob_pattern}\n"
            f"total_matches={len(matches)}\n"
            f"page_offset={page_offset}\n"
            f"page_size={page_size}\n"
            f"returned_matches={len(page_matches)}\n"
            f"has_more={has_more}\n"
            f"next_offset={next_offset}"
        )
        return header + "\n" + "\n".join(page_matches)

    return search_source_text


def build_search_source_files_tool(source_dir: Path) -> Any:
    ignore_spec: PathSpec | None = _build_source_ignore_spec(source_dir)

    @function_tool
    def search_source_files(
        pattern: str,
        page_offset: int = 0,
        page_size: int = DEFAULT_SEARCH_RESULTS,
    ) -> str:
        """Search source-relative file paths by substring, with paging."""
        if not pattern:
            raise ValueError("pattern must not be empty")
        if page_offset < 0:
            raise ValueError("page_offset must be >= 0")
        _validate_page_size(page_size, "page_size")

        normalized_pattern: str = pattern.lower()
        matches: list[str] = []
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            if _is_ignored_by_source_gitignore(path, source_dir, ignore_spec):
                continue
            relative_path: str = "/" + str(path.relative_to(source_dir))
            if normalized_pattern in relative_path.lower():
                matches.append(relative_path)
        if not matches:
            return "No files found."

        if page_offset >= len(matches):
            raise ValueError("page_offset is out of range for file search results")
        page_matches: list[str] = matches[page_offset : page_offset + page_size]
        has_more: bool = page_offset + page_size < len(matches)
        next_offset: int | None = None
        if has_more:
            next_offset = page_offset + len(page_matches)
        header: str = (
            f"pattern={pattern}\n"
            f"total_matches={len(matches)}\n"
            f"page_offset={page_offset}\n"
            f"page_size={page_size}\n"
            f"returned_matches={len(page_matches)}\n"
            f"has_more={has_more}\n"
            f"next_offset={next_offset}"
        )
        return header + "\n" + "\n".join(page_matches)

    return search_source_files


def build_submit_triage_report_tool(
    row: CodeQLResultRow,
    artifacts: RunArtifacts,
    workspace_dir: Path,
    source_dir: Path,
    typst_command: str | None = None,
) -> Any:
    def submit_triage_report(report: SingleFindingReport) -> str:
        """Submit the final structured triage report for this finding."""
        structured_report: dict[str, Any] = asdict(
            SingleFindingReport(
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
        )
        artifacts.write_run_json({"structured_report": structured_report})
        try:
            _validate_report_source_references(report=report, source_dir=source_dir)
        except Exception as exc:
            artifacts.write_run_json({"report_validation_error": str(exc)})
            raise

        bundle = write_single_finding_report(
            output_dir=artifacts.run_dir,
            row=row,
            report=report,
            workspace_dir=workspace_dir,
            typst_command=typst_command,
        )
        artifacts.write_run_json(
            {
                "structured_report": structured_report,
                "report_files": {
                    "json": str(bundle.json_path),
                    "pdf": str(bundle.pdf_path) if bundle.pdf_generated else None,
                    "pdf_generated": bundle.pdf_generated,
                    "typst_command": bundle.typst_command,
                    "pdf_error": bundle.pdf_error,
                },
            }
        )
        pdf_status: str = (
            str(bundle.pdf_path) if bundle.pdf_generated else "not_generated"
        )
        return (
            "Structured triage report submitted.\n"
            f"report_json={bundle.json_path}\n"
            f"report_pdf={pdf_status}"
        )

    submit_triage_report.__doc__ = SUBMIT_TRIAGE_REPORT_DOC
    return function_tool(submit_triage_report)
