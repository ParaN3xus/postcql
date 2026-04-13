from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents import (
    Agent,
    ModelSettings,
    Runner,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)
from agents.mcp import MCPServerStdio
from openai import AsyncOpenAI
from openai.types.shared import Reasoning

from ..codeql_sarif import CodeQLResultRow
from ..config import DEFAULT_CLANGD_PATH, DEFAULT_MCP_SERVER_COMMAND, AppConfig
from ..logging import logger
from ..run_artifacts import RunArtifacts
from .events import consume_streaming_events
from .prompting import build_agent_instructions, build_triage_prompt_text
from .tools import (
    build_read_source_context_tool,
    build_read_source_span_tool,
    build_search_source_files_tool,
    build_search_source_text_tool,
    build_submit_triage_report_tool,
)


@dataclass(slots=True)
class AnalysisContext:
    row: CodeQLResultRow
    project_root: Path


def configure_openai_client(config: AppConfig) -> AsyncOpenAI:
    client = AsyncOpenAI(
        api_key=config.openai.api_key,
        base_url=config.openai.base_url,
    )
    set_default_openai_client(client, use_for_tracing=False)
    set_default_openai_api(config.openai.api_mode)
    set_tracing_disabled(True)
    return client


def build_mcp_server(config: AppConfig) -> MCPServerStdio:
    server_args: list[str] = [
        "--workspace",
        str(config.source_dir),
        "--lsp",
        DEFAULT_CLANGD_PATH,
        "--",
        f"--compile-commands-dir={config.compile_commands_dir}",
    ]
    env: dict[str, str] = {
        "PATH": str(Path("/usr/bin")) + ":" + str(Path("/bin")),
    }

    return MCPServerStdio(
        params={
            "command": DEFAULT_MCP_SERVER_COMMAND,
            "args": server_args,
            "cwd": config.source_dir,
            "env": env,
        },
        cache_tools_list=True,
        name="language-server",
    )


def build_triage_prompt(
    row: CodeQLResultRow,
    project_root: Path,
    test_mode: bool = False,
) -> str:
    return build_triage_prompt_text(
        row=row,
        project_root=project_root,
        test_mode=test_mode,
    )


async def analyze_codeql_row(
    config: AppConfig,
    row: CodeQLResultRow,
    artifacts: RunArtifacts | None = None,
    test_mode: bool = False,
) -> str:
    if artifacts is None:
        raise ValueError(
            "artifacts is required; analysis must end via submit_triage_report"
        )

    configure_openai_client(config)
    mcp_server: MCPServerStdio = build_mcp_server(config)
    read_source_context_tool: Any = build_read_source_context_tool(config.source_dir)
    read_source_span_tool: Any = build_read_source_span_tool(config.source_dir)
    search_source_text_tool: Any = build_search_source_text_tool(config.source_dir)
    search_source_files_tool: Any = build_search_source_files_tool(config.source_dir)
    submit_triage_report_tool: Any = build_submit_triage_report_tool(
        row=row,
        artifacts=artifacts,
        workspace_dir=config.work_dir,
        source_dir=config.source_dir,
    )
    await mcp_server.connect()

    try:
        agent = Agent[AnalysisContext](
            name="PostCQL Triage Agent",
            instructions=build_agent_instructions(test_mode=test_mode),
            tools=[
                read_source_context_tool,
                read_source_span_tool,
                search_source_text_tool,
                search_source_files_tool,
                submit_triage_report_tool,
            ],
            mcp_servers=[mcp_server],
            model=config.openai.model,
            model_settings=ModelSettings(
                tool_choice="required",
                reasoning=Reasoning(effort="medium"),
            ),
            tool_use_behavior={"stop_at_tool_names": ["submit_triage_report"]},
        )

        prompt: str = build_triage_prompt(
            row=row,
            project_root=config.source_dir,
            test_mode=test_mode,
        )
        artifacts.add_section(
            "Run Metadata",
            {
                "row_index": row.row_index,
                "rule_name": row.rule_name,
                "severity": row.severity,
                "file": row.relative_file_path,
                "work_dir": config.work_dir,
                "test_mode": test_mode,
            },
        )
        artifacts.add_section("Prompt", {"text": prompt})

        run_result = Runner.run_streamed(
            agent,
            prompt,
            context=AnalysisContext(row=row, project_root=config.source_dir),
            max_turns=config.agent.max_turns,
        )
        await consume_streaming_events(run_result, artifacts=artifacts)
        final_output: str = str(run_result.final_output)
        artifacts.write_run_json({"final_output": final_output})
        if not final_output.strip():
            raise RuntimeError(
                "Agent finished without any final output; "
                "submit_triage_report was likely not called."
            )
        if "structured_report" not in artifacts._payload:
            raise RuntimeError(
                "Agent finished without structured_report; "
                "submit_triage_report was not completed."
            )
        if "report_files" not in artifacts._payload:
            raise RuntimeError(
                "Agent finished without report_files; "
                "report artifacts were not generated."
            )
        logger.info("analysis_result_row=%s\n%s", row.row_index, final_output)
        return final_output
    except Exception as exc:
        artifacts.add_section("Error", {"message": str(exc)})
        artifacts.write_run_json(
            {
                "row": row,
                "error": str(exc),
            }
        )
        raise
    finally:
        await mcp_server.cleanup()


def analyze_codeql_row_sync(
    config: AppConfig,
    row: CodeQLResultRow,
    artifacts: RunArtifacts | None = None,
    test_mode: bool = False,
) -> str:
    return asyncio.run(
        analyze_codeql_row(
            config=config,
            row=row,
            artifacts=artifacts,
            test_mode=test_mode,
        )
    )
