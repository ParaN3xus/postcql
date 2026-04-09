from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from agents import function_tool


def _resolve_source_path(source_dir: Path, file_path: str) -> Path:
    normalized_relative_path: str = file_path.lstrip("/")
    resolved_path: Path = (source_dir / normalized_relative_path).resolve()
    source_root: Path = source_dir.resolve()
    try:
        resolved_path.relative_to(source_root)
    except ValueError as exc:
        raise ValueError(f"File path escapes source dir: {file_path}") from exc
    return resolved_path


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

        lines: list[str] = resolved_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        start_line: int = max(1, center_line - context_lines)
        end_line: int = min(len(lines), center_line + context_lines)

        rendered_lines: list[str] = [
            f"{line_number:6d}: {lines[line_number - 1]}"
            for line_number in range(start_line, end_line + 1)
        ]
        header: str = (
            f"file={resolved_path}\n"
            f"requested_line={center_line}\n"
            f"shown_range={start_line}-{end_line}"
        )
        return header + "\n" + "\n".join(rendered_lines)

    return read_source_context


def build_read_source_span_tool(source_dir: Path) -> Any:
    @function_tool
    def read_source_span(file_path: str, start_line: int, end_line: int) -> str:
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

        lines: list[str] = resolved_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        bounded_end_line: int = min(len(lines), end_line)
        rendered_lines: list[str] = [
            f"{line_number:6d}: {lines[line_number - 1]}"
            for line_number in range(start_line, bounded_end_line + 1)
        ]
        header: str = (
            f"file={resolved_path}\n"
            f"requested_range={start_line}-{end_line}\n"
            f"shown_range={start_line}-{bounded_end_line}"
        )
        return header + "\n" + "\n".join(rendered_lines)

    return read_source_span


def build_search_source_text_tool(source_dir: Path) -> Any:
    @function_tool
    def search_source_text(
        pattern: str,
        glob_pattern: str = "*",
        max_results: int = 50,
    ) -> str:
        """Search source files for plain text and return matching lines."""
        if not pattern:
            raise ValueError("pattern must not be empty")
        if max_results < 1:
            raise ValueError("max_results must be >= 1")

        matches: list[str] = []
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            relative_path: str = "/" + str(path.relative_to(source_dir))
            if not fnmatch.fnmatch(relative_path, glob_pattern):
                continue

            for line_number, line_text in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(),
                start=1,
            ):
                if pattern in line_text:
                    matches.append(f"{relative_path}:{line_number}: {line_text}")
                    if len(matches) >= max_results:
                        return "\n".join(matches)

        if matches:
            return "\n".join(matches)
        return "No matches found."

    return search_source_text


def build_search_source_files_tool(source_dir: Path) -> Any:
    @function_tool
    def search_source_files(pattern: str, max_results: int = 50) -> str:
        """Search source-relative file paths by substring."""
        if not pattern:
            raise ValueError("pattern must not be empty")
        if max_results < 1:
            raise ValueError("max_results must be >= 1")

        normalized_pattern: str = pattern.lower()
        matches: list[str] = []
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            relative_path: str = "/" + str(path.relative_to(source_dir))
            if normalized_pattern in relative_path.lower():
                matches.append(relative_path)
                if len(matches) >= max_results:
                    break

        if matches:
            return "\n".join(matches)
        return "No files found."

    return search_source_files
