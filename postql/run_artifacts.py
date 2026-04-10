from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _to_json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_compatible(item) for item in value]
    if is_dataclass(value):
        return {
            field.name: _to_json_compatible(getattr(value, field.name))
            for field in fields(value)
        }

    model_dump: Any = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _to_json_compatible(model_dump(mode="json"))
        except TypeError:
            return _to_json_compatible(model_dump())

    return repr(value)


@dataclass(slots=True)
class RunArtifacts:
    command_name: str
    run_dir: Path
    result_markdown_path: Path
    run_json_path: Path
    _sections: list[dict[str, Any]]
    _events: list[dict[str, Any]]
    _payload: dict[str, Any]

    @classmethod
    def create(
        cls,
        results_dir: Path,
        command_name: str,
        name_suffix: str | None = None,
    ) -> "RunArtifacts":
        timestamp: str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        run_name: str = command_name
        if name_suffix:
            run_name = f"{run_name}-{name_suffix}"
        run_dir: Path = results_dir / f"{run_name}-{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=False)
        artifacts = cls(
            command_name=command_name,
            run_dir=run_dir,
            result_markdown_path=run_dir / "result.md",
            run_json_path=run_dir / "run.json",
            _sections=[],
            _events=[],
            _payload={},
        )
        artifacts.initialize()
        return artifacts

    def initialize(self) -> None:
        self._flush_run_json()

    def _flush_run_json(self) -> None:
        serialized_payload: dict[str, Any] = {
            "command_name": self.command_name,
            "run_dir": str(self.run_dir),
            "sections": _to_json_compatible(self._sections),
            "events": _to_json_compatible(self._events),
            **_to_json_compatible(self._payload),
        }
        self.run_json_path.write_text(
            json.dumps(serialized_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def add_section(self, title: str, data: Any) -> None:
        self._sections.append(
            {
                "type": "section",
                "title": title,
                "data": _to_json_compatible(data),
            }
        )
        self._flush_run_json()

    def add_event(
        self,
        event_type: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        event_payload: dict[str, Any] = {"event_type": event_type}
        if details is not None:
            event_payload["details"] = _to_json_compatible(details)
        self._events.append(event_payload)
        self._flush_run_json()

    def write_result(self, final_output: str) -> None:
        self.result_markdown_path.write_text(
            final_output.rstrip() + "\n",
            encoding="utf-8",
        )
        self.write_run_json({"final_output": final_output})

    def write_run_json(self, payload: dict[str, Any]) -> None:
        self._payload.update(_to_json_compatible(payload))
        self._flush_run_json()
