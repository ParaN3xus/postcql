from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

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
        help="0-based result index in the CodeQL SARIF file",
    )
    analyze_row.add_argument(
        "--test-mode",
        action="store_true",
        help="Append a test-only prompt instruction that immediately submits a "
        "fabricated valid report",
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


def _get_row_by_index(rows: list[CodeQLResultRow], row_index: int) -> CodeQLResultRow:
    if row_index < 0 or row_index >= len(rows):
        raise IndexError(f"Row index {row_index} out of range, total rows: {len(rows)}")
    return rows[row_index]


def _run_placeholder(command_name: str) -> int:
    logger.info("command_not_implemented=%s", command_name)
    return 0


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
    batch_artifacts: RunArtifacts = RunArtifacts.create(
        results_dir=config.results_dir,
        command_name="analyze-all",
    )
    successful_report_json_paths: list[Path] = []
    row_results: list[dict[str, object]] = []
    logger.info("batch_run_dir=%s", batch_artifacts.run_dir)

    for row in rows:
        row_dir: Path = batch_artifacts.run_dir / str(row.row_index)
        row_artifacts: RunArtifacts = RunArtifacts.create_in_dir(
            run_dir=row_dir,
            command_name="analyze-row",
        )
        logger.info(
            "analyzing row=%s rule=%s file=%s",
            row.row_index,
            row.rule_name,
            row.relative_file_path,
        )
        try:
            analyze_codeql_row_sync(
                config=config,
                row=row,
                artifacts=row_artifacts,
                test_mode=test_mode,
            )
            report_json_path: Path = row_dir / "report.json"
            successful_report_json_paths.append(report_json_path)
            row_results.append(
                {
                    "row_index": row.row_index,
                    "run_dir": row_dir,
                    "status": "ok",
                    "report_json": report_json_path,
                }
            )
        except Exception as exc:
            logger.exception("row_analysis_failed row=%s", row.row_index)
            row_results.append(
                {
                    "row_index": row.row_index,
                    "run_dir": row_dir,
                    "status": "error",
                    "error": str(exc),
                }
            )

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
        row: CodeQLResultRow = _get_row_by_index(rows=rows, row_index=args.row_index)
        return _run_analyze_row(
            config=config,
            row=row,
            command_name=args.command,
            test_mode=args.test_mode,
        )
    if args.command == "analyze-all":
        rows = read_codeql_sarif(config.codeql_sarif_path)
        return _run_analyze_all(config=config, rows=rows, test_mode=args.test_mode)

    return _run_placeholder(args.command)
