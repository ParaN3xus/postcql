from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
import tomllib

DEFAULT_MCP_SERVER_COMMAND: str = "/home/admin/go/bin/mcp-language-server"
DEFAULT_CLANGD_PATH: str = "/usr/bin/clangd"


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
class AppConfig:
    openai: OpenAIConfig
    agent: AgentConfig
    work_dir: Path

    @property
    def source_dir(self) -> Path:
        return self.work_dir / "source"

    @property
    def compile_commands_dir(self) -> Path:
        return self.source_dir

    @property
    def codeql_sarif_path(self) -> Path:
        return self.work_dir / "codeql-results" / "all.sarif"

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


def load_config(config_path: Path) -> AppConfig:
    data: dict[str, object] = tomllib.loads(config_path.read_text())

    openai_data: dict[str, Any] = _get_table(data, "openai")
    app_data: dict[str, Any] = _get_table(data, "app")
    agent_data_raw: object = data.get("agent", {})
    if not isinstance(agent_data_raw, dict):
        raise ValueError("Invalid [agent] table in config")
    agent_data: dict[str, Any] = dict(agent_data_raw)
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
        work_dir=work_dir,
    )
