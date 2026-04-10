from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from .agent import analyze_codeql_row_sync
from .codeql_csv import CodeQLResultRow, read_codeql_csv
from .config import AppConfig, load_config
from .logging import logger, set_logger_level
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
        help="Run the triage agent for a single CodeQL CSV row index",
    )
    analyze_row.add_argument(
        "row_index",
        type=int,
        help="0-based row index in the CodeQL CSV",
    )
    analyze_row.add_argument(
        "--test-mode",
        action="store_true",
        help="Append a test-only prompt instruction that immediately submits a fabricated valid report",
    )

    subparsers.add_parser(
        "setup",
        help="Placeholder for future environment setup command",
    )
    subparsers.add_parser(
        "build-database",
        help="Placeholder for future CodeQL database creation command",
    )
    subparsers.add_parser(
        "run-scan",
        help="Placeholder for future CodeQL scan command",
    )

    return parser


def _get_row_by_index(rows: list[CodeQLResultRow], row_index: int) -> CodeQLResultRow:
    if row_index < 0 or row_index >= len(rows):
        raise IndexError(f"Row index {row_index} out of range, total rows: {len(rows)}")
    return rows[row_index]


def _run_placeholder(command_name: str) -> int:
    logger.info("command_not_implemented=%s", command_name)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    set_logger_level(args.log_level)

    config: AppConfig = load_config(args.config)

    if args.command == "analyze-row":
        rows: list[CodeQLResultRow] = read_codeql_csv(config.codeql_csv_path)
        row: CodeQLResultRow = _get_row_by_index(rows=rows, row_index=args.row_index)
        artifacts: RunArtifacts = RunArtifacts.create(
            results_dir=config.results_dir,
            command_name=args.command,
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
            test_mode=args.test_mode,
        )
        return 0

    return _run_placeholder(args.command)
