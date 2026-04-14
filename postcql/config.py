from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
import tomllib

@dataclass(slots=True)
class OpenAIConfig:
    api_key: str
    base_url: str
    model: str
    api_mode: Literal["chat_completions", "responses"] = "chat_completions"


@dataclass(slots=True)
class AgentConfig:
    max_turns: int = 64
    max_concurrency: int = 4


@dataclass(slots=True)
class BinaryConfig:
    mcp_server: str | None = None
    clangd: str | None = None
    typst: str | None = None
    mcp_server_path_entries: tuple[str, ...] = ()


@dataclass(slots=True)
class AppConfig:
    openai: OpenAIConfig
    agent: AgentConfig
    binaries: BinaryConfig
    work_dir: Path
    codeql_sarif_filename: str = "all.sarif"

    @property
    def source_dir(self) -> Path:
        return self.work_dir / "source"

    @property
    def compile_commands_dir(self) -> Path:
        return self.source_dir

    @property
    def codeql_sarif_path(self) -> Path:
        return self.work_dir / "codeql-results" / self.codeql_sarif_filename

    @property
    def codeql_db_dir(self) -> Path:
        return self.work_dir / "codeql-db"

    @property
    def results_dir(self) -> Path:
        return self.work_dir / "results"


def _expand_path(value: str | None) -> Path | None:
    if value is None:
        return None
    return Path(value).expanduser().resolve()


def _parse_optional_path_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    expanded: Path = Path(value).expanduser()
    if expanded.is_absolute():
        return str(expanded.resolve())
    return value


def _parse_string_list(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array of strings")
    parsed: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must contain only strings")
        expanded: Path = Path(item).expanduser()
        parsed.append(str(expanded.resolve()) if expanded.is_absolute() else item)
    return tuple(parsed)


def _get_table(data: dict[str, object], key: str) -> dict[str, Any]:
    value: object = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Missing or invalid [{key}] table in config")
    return dict(value)


def _parse_api_mode(value: object) -> Literal["chat_completions", "responses"]:
    if value == "chat_completions":
        return "chat_completions"
    if value == "responses":
        return "responses"
    raise ValueError(f"Unsupported openai.api_mode: {value!r}")


def _parse_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{field_name} must be an integer")
    parsed: int = int(value)
    if parsed < 1:
        raise ValueError(f"{field_name} must be >= 1")
    return parsed


def _parse_filename(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    parsed = Path(value)
    if parsed.name != value or parsed.name in {".", ".."}:
        raise ValueError(f"{field_name} must be a filename, not a path")
    return value


def load_config(config_path: Path) -> AppConfig:
    data: dict[str, object] = tomllib.loads(config_path.read_text())

    openai_data: dict[str, Any] = _get_table(data, "openai")
    app_data: dict[str, Any] = _get_table(data, "app")
    agent_data_raw: object = data.get("agent", {})
    if not isinstance(agent_data_raw, dict):
        raise ValueError("Invalid [agent] table in config")
    agent_data: dict[str, Any] = dict(agent_data_raw)
    binaries_data_raw: object = data.get("binaries", {})
    if not isinstance(binaries_data_raw, dict):
        raise ValueError("Invalid [binaries] table in config")
    binaries_data: dict[str, Any] = dict(binaries_data_raw)
    work_dir: Path = _expand_path(str(app_data["work_dir"])) or Path.cwd()

    return AppConfig(
        openai=OpenAIConfig(
            api_key=str(openai_data["api_key"]),
            base_url=str(openai_data["base_url"]),
            model=str(openai_data["model"]),
            api_mode=_parse_api_mode(openai_data.get("api_mode", "chat_completions")),
        ),
        agent=AgentConfig(
            max_turns=_parse_positive_int(
                agent_data.get("max_turns", 64),
                "agent.max_turns",
            ),
            max_concurrency=_parse_positive_int(
                agent_data.get("max_concurrency", 4),
                "agent.max_concurrency",
            ),
        ),
        binaries=BinaryConfig(
            mcp_server=_parse_optional_path_string(
                binaries_data.get("mcp_server"),
                "binaries.mcp_server",
            ),
            clangd=_parse_optional_path_string(
                binaries_data.get("clangd"),
                "binaries.clangd",
            ),
            typst=_parse_optional_path_string(
                binaries_data.get("typst"),
                "binaries.typst",
            ),
            mcp_server_path_entries=_parse_string_list(
                binaries_data.get("mcp_server_path_entries"),
                "binaries.mcp_server_path_entries",
            ),
        ),
        work_dir=work_dir,
        codeql_sarif_filename=_parse_filename(
            app_data.get("codeql_sarif_filename", "all.sarif"),
            "app.codeql_sarif_filename",
        ),
    )
