from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path


@dataclass(slots=True)
class SourceLocation:
    line: int
    column: int


@dataclass(slots=True)
class CodeQLResultRow:
    row_index: int
    rule_name: str
    rule_description: str
    severity: str
    message: str
    relative_file_path: str
    start: SourceLocation
    end: SourceLocation

    def resolved_path(self, project_root: Path) -> Path:
        return project_root / self.relative_file_path.lstrip("/")


def parse_codeql_csv_row(row_index: int, raw_row: list[str]) -> CodeQLResultRow:
    if len(raw_row) != 9:
        raise ValueError(
            f"Expected 9 columns for CodeQL CSV row {row_index}, got {len(raw_row)}"
        )

    return CodeQLResultRow(
        row_index=row_index,
        rule_name=raw_row[0],
        rule_description=raw_row[1],
        severity=raw_row[2],
        message=raw_row[3],
        relative_file_path=raw_row[4],
        start=SourceLocation(line=int(raw_row[5]), column=int(raw_row[6])),
        end=SourceLocation(line=int(raw_row[7]), column=int(raw_row[8])),
    )


def read_codeql_csv(csv_path: Path) -> list[CodeQLResultRow]:
    rows: list[CodeQLResultRow] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for row_index, raw_row in enumerate(reader):
            rows.append(parse_codeql_csv_row(row_index=row_index, raw_row=raw_row))
    return rows
