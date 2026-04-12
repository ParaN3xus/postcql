from __future__ import annotations

import argparse
import logging
import shutil
import sys
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Sequence

from .agent import analyze_codeql_row_sync
from .codeql_sarif import CodeQLResultRow, read_codeql_sarif
from .config import AppConfig, load_config
from .logging import logger, set_logger_level
from .report import write_full_report
from .run_artifacts import RunArtifacts


def _parse_log_level(value: str) -> int:
    normalized: str = value.upper()
    if normalized not in logging.getLevelNamesMapping():
        raise argparse.ArgumentTypeError(f"Unsupported log level: {value}")
    return logging.getLevelNamesMapping()[normalized]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="postql")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to config.toml",
    )
    parser.add_argument(
        "--log-level",
        type=_parse_log_level,
        default=logging.INFO,
        help="Python logging level, for example DEBUG or INFO",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_row = subparsers.add_parser(
        "analyze-row",
        help="Run the triage agent for a single CodeQL SARIF result index",
    )
    analyze_row.add_argument(
        "row_index",
        type=int,
        nargs="+",
        help="0-based result index in the CodeQL SARIF file",
    )
    analyze_row.add_argument(
        "--test-mode",
        action="store_true",
        help="Append a test-only prompt instruction that immediately submits a "
        "fabricated valid report",
    )
    analyze_row.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt",
    )
    analyze_all = subparsers.add_parser(
        "analyze-all",
        help="Run the triage agent for every result in the CodeQL SARIF file",
    )
    analyze_all.add_argument(
        "--test-mode",
        action="store_true",
        help="Append a test-only prompt instruction that immediately "
        "submits a fabricated valid report",
    )

    subparsers.add_parser(
        "setup",
        help="Placeholder for future environment setup command",
    )
    subparsers.add_parser(
        "build-database",
        help="Placeholder for future CodeQL database creation command",
    )

    return parser


def _get_row_by_index(rows: List[CodeQLResultRow], row_index: int) -> CodeQLResultRow:
    if row_index < 0 or row_index >= len(rows):
        raise IndexError(f"Row index {row_index} out of range, total rows: {len(rows)}")
    return rows[row_index]


def _run_placeholder(command_name: str) -> int:
    logger.info("command_not_implemented=%s", command_name)
    return 0


def _row_index_from_result(item: dict[str, object]) -> int:
    row_index: object = item.get("row_index")
    if not isinstance(row_index, int):
        raise ValueError(f"Invalid row_index in row result: {row_index!r}")
    return row_index


def _format_optional_text(value: str | None) -> str:
    return value if value else "none"


def _confirm_analyze_row(row: CodeQLResultRow, test_mode: bool) -> bool:
    lines: list[str] = [
        "About to analyze this SARIF result:",
        f"  row_index: {row.row_index}",
        f"  rule_name: {row.rule_name}",
        f"  severity: {row.severity}",
        f"  file: {row.relative_file_path}",
        f"  start: {row.start.line}:{row.start.column}",
        f"  end: {row.end.line}:{row.end.column}",
        f"  test_mode: {test_mode}",
        "",
        "Press Enter to continue, or type 'n' to cancel: ",
    ]
    print("\n".join(lines), end="", flush=True)
    response: str = input().strip().lower()
    return response not in {"n", "no"}


def _confirm_analyze_rows(rows: list[CodeQLResultRow], test_mode: bool) -> bool:
    preview_rows: list[CodeQLResultRow] = rows[:5]
    lines: list[str] = [
        "About to analyze these SARIF results:",
        f"  total_rows: {len(rows)}",
        f"  row_indexes: {', '.join(str(row.row_index) for row in rows)}",
        f"  test_mode: {test_mode}",
    ]
    for row in preview_rows:
        lines.append(
            "  - "
            f"{row.row_index} {row.rule_name} {row.relative_file_path} "
            f"{row.start.line}:{row.start.column}"
        )
    if len(rows) > len(preview_rows):
        lines.append(f"  - ... {len(rows) - len(preview_rows)} more rows")
    lines.extend(
        [
            "",
            "Press Enter to continue, or type 'n' to cancel: ",
        ]
    )
    print("\n".join(lines), end="", flush=True)
    response: str = input().strip().lower()
    return response not in {"n", "no"}


def _run_analyze_row(
    config: AppConfig,
    row: CodeQLResultRow,
    command_name: str,
    test_mode: bool,
) -> int:
    artifacts: RunArtifacts = RunArtifacts.create(
        results_dir=config.results_dir,
        command_name=command_name,
        name_suffix=str(row.row_index),
    )
    logger.info(
        "analyzing row=%s rule=%s file=%s",
        row.row_index,
        row.rule_name,
        row.relative_file_path,
    )
    logger.info("run_artifacts_dir=%s", artifacts.run_dir)
    analyze_codeql_row_sync(
        config=config,
        row=row,
        artifacts=artifacts,
        test_mode=test_mode,
    )
    return 0


def _run_analyze_all(
    config: AppConfig,
    rows: list[CodeQLResultRow],
    test_mode: bool,
) -> int:
    return _run_batch_analysis(
        config=config,
        rows=rows,
        test_mode=test_mode,
        command_name="analyze-all",
    )


def _run_batch_analysis(
    config: AppConfig,
    rows: list[CodeQLResultRow],
    test_mode: bool,
    command_name: str,
) -> int:
    batch_artifacts: RunArtifacts = RunArtifacts.create(
        results_dir=config.results_dir,
        command_name=command_name,
    )
    successful_report_json_paths: list[Path] = []
    row_results: list[dict[str, object]] = []
    logger.info("batch_run_dir=%s", batch_artifacts.run_dir)
    logger.info("max_concurrency=%s", config.agent.max_concurrency)

    def run_single_row(row: CodeQLResultRow) -> dict[str, object]:
        row_dir: Path = batch_artifacts.run_dir / str(row.row_index)
        max_attempts: int = 2
        last_error: str | None = None

        for attempt in range(1, max_attempts + 1):
            shutil.rmtree(row_dir, ignore_errors=True)
            row_artifacts: RunArtifacts = RunArtifacts.create_in_dir(
                run_dir=row_dir,
                command_name="analyze-row",
            )
            logger.info(
                "analyzing row=%s rule=%s file=%s attempt=%s/%s",
                row.row_index,
                row.rule_name,
                row.relative_file_path,
                attempt,
                max_attempts,
            )
            try:
                analyze_codeql_row_sync(
                    config=config,
                    row=row,
                    artifacts=row_artifacts,
                    test_mode=test_mode,
                )
                report_json_path: Path = row_dir / "report.json"
                report_pdf_path: Path = row_dir / "report.pdf"
                if report_json_path.is_file() and report_pdf_path.is_file():
                    return {
                        "row_index": row.row_index,
                        "run_dir": row_dir,
                        "status": "ok",
                        "report_json": report_json_path,
                        "attempts": attempt,
                    }
                last_error = "missing report.pdf"
                logger.warning(
                    "row_analysis_missing_pdf row=%s attempt=%s/%s",
                    row.row_index,
                    attempt,
                    max_attempts,
                )
            except Exception as exc:
                last_error = str(exc)
                logger.exception(
                    "row_analysis_failed row=%s attempt=%s/%s",
                    row.row_index,
                    attempt,
                    max_attempts,
                )

        return {
            "row_index": row.row_index,
            "run_dir": row_dir,
            "status": "error",
            "error": last_error or "unknown error",
            "attempts": max_attempts,
        }

    with ThreadPoolExecutor(max_workers=config.agent.max_concurrency) as executor:
        future_by_row_index: dict[Future[dict[str, object]], int] = {
            executor.submit(run_single_row, row): row.row_index for row in rows
        }
        for future in as_completed(future_by_row_index):
            row_result: dict[str, object] = future.result()
            row_results.append(row_result)
            report_json: object = row_result.get("report_json")
            if isinstance(report_json, Path):
                successful_report_json_paths.append(report_json)

    row_results.sort(key=_row_index_from_result)

    full_report_bundle = None
    if successful_report_json_paths:
        full_report_bundle = write_full_report(
            output_dir=batch_artifacts.run_dir,
            report_json_paths=successful_report_json_paths,
            workspace_dir=config.work_dir,
        )

    batch_artifacts.write_run_json(
        {
            "test_mode": test_mode,
            "command_name": command_name,
            "total_rows": len(rows),
            "successful_rows": len(successful_report_json_paths),
            "failed_rows": len(rows) - len(successful_report_json_paths),
            "rows": row_results,
            "full_report_files": (
                {
                    "json": str(full_report_bundle.json_path),
                    "pdf": str(full_report_bundle.pdf_path)
                    if full_report_bundle.pdf_generated
                    else None,
                    "pdf_generated": full_report_bundle.pdf_generated,
                    "typst_command": full_report_bundle.typst_command,
                    "pdf_error": full_report_bundle.pdf_error,
                }
                if full_report_bundle is not None
                else None
            ),
        }
    )
    return 0 if len(successful_report_json_paths) == len(rows) else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    set_logger_level(args.log_level)

    config: AppConfig = load_config(args.config)

    if args.command == "analyze-row":
        rows = read_codeql_sarif(config.codeql_sarif_path)
        selected_rows: list[CodeQLResultRow] = [
            _get_row_by_index(rows=rows, row_index=row_index)
            for row_index in args.row_index
        ]
        unique_rows: list[CodeQLResultRow] = []
        seen_row_indexes: set[int] = set()
        for row in selected_rows:
            if row.row_index in seen_row_indexes:
                continue
            seen_row_indexes.add(row.row_index)
            unique_rows.append(row)
        selected_rows = unique_rows
        if not args.yes:
            if not sys.stdin.isatty():
                raise RuntimeError("Interactive confirmation requires a TTY; use --yes")
            confirmed: bool
            if len(selected_rows) == 1:
                confirmed = _confirm_analyze_row(
                    row=selected_rows[0],
                    test_mode=args.test_mode,
                )
            else:
                confirmed = _confirm_analyze_rows(
                    rows=selected_rows,
                    test_mode=args.test_mode,
                )
            if not confirmed:
                print("Cancelled.")
                return 1
        if len(selected_rows) == 1:
            return _run_analyze_row(
                config=config,
                row=selected_rows[0],
                command_name=args.command,
                test_mode=args.test_mode,
            )
        return _run_batch_analysis(
            config=config,
            rows=selected_rows,
            test_mode=args.test_mode,
            command_name="analyze-row-batch",
        )
    if args.command == "analyze-all":
        rows = read_codeql_sarif(config.codeql_sarif_path)
        return _run_analyze_all(config=config, rows=rows, test_mode=args.test_mode)

    return _run_placeholder(args.command)
