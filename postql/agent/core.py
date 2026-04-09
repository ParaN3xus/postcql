from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents import (
    Agent,
    ItemHelpers,
    MessageOutputItem,
    RawResponsesStreamEvent,
    ReasoningItem,
    RunItemStreamEvent,
    Runner,
    ToolCallItem,
    ToolCallOutputItem,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)
from agents.mcp import MCPServerStdio
from openai import AsyncOpenAI

from ..codeql_csv import CodeQLResultRow
from ..config import AppConfig, DEFAULT_CLANGD_PATH, DEFAULT_MCP_SERVER_COMMAND
from ..logging import logger
from .tools import (
    build_read_source_context_tool,
    build_read_source_span_tool,
    build_search_source_files_tool,
    build_search_source_text_tool,
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


def build_triage_prompt(row: CodeQLResultRow, project_root: Path) -> str:
    source_path: Path = row.resolved_path(project_root)
    return f"""
You are triaging one CodeQL finding against a real C/C++ codebase.

Primary requirements:
- Use MCP language-server tools aggressively, and prefer position-based queries first.
- Use the local read_source_context tool whenever you need exact source text.
- Use read_source_span when you already know the exact range to inspect.
- Use search_source_text for grep-like repository text search.
- Use search_source_files to locate candidate files by filename/path.
- Start from the alert location using hover, diagnostics, references,
  and any other relevant tools.
- Determine whether the CodeQL alert is a real vulnerability in practice,
  or a false positive / low-signal concern.
- If you need to reason about control flow or data flow, use the available
  code navigation tools to gather evidence before concluding.
- Be explicit about uncertainty.
  Do not claim exploitability unless the code evidence supports it.

CodeQL finding:
- row_index: {row.row_index}
- rule_name: {row.rule_name}
- severity: {row.severity}
- file: {source_path}
- start_line: {row.start.line}
- start_column: {row.start.column}
- end_line: {row.end.line}
- end_column: {row.end.column}
- rule_description: {row.rule_description}
- alert_message: {row.message}

You must produce:
1. verdict: REAL, FALSE_POSITIVE, or UNCERTAIN
2. why CodeQL was concerned
3. whether the concern is actually reachable/triggerable in this code, with evidence
4. if REAL: a concrete possible trigger path, severity,
   and a high-level remediation idea
5. list of key code locations you relied on

Keep the answer technical and specific to the codebase.
""".strip()


def _stringify_tool_call(raw_item: Any) -> str:
    name: str = str(
        getattr(raw_item, "name", None) or getattr(raw_item, "type", "unknown_tool")
    )
    arguments: Any = getattr(raw_item, "arguments", None)
    if arguments is None and isinstance(raw_item, dict):
        arguments = raw_item.get("arguments")
    return f"{name} args={arguments}"


def _stringify_reasoning(item: ReasoningItem) -> str:
    raw_item: Any = item.raw_item
    summary: Any = getattr(raw_item, "summary", None)
    if summary:
        return str(summary)
    content: Any = getattr(raw_item, "content", None)
    if content:
        return str(content)
    return str(raw_item)


async def _log_streaming_events(result: Any) -> None:
    async for event in result.stream_events():
        if isinstance(event, RawResponsesStreamEvent):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("raw_llm_event=%s", event.data)
            continue

        if isinstance(event, RunItemStreamEvent):
            if event.name == "reasoning_item_created" and isinstance(
                event.item,
                ReasoningItem,
            ):
                logger.debug("llm_reasoning=%s", _stringify_reasoning(event.item))
            elif event.name == "tool_called" and isinstance(event.item, ToolCallItem):
                logger.debug(
                    "tool_called=%s",
                    _stringify_tool_call(event.item.raw_item),
                )
            elif event.name == "tool_output" and isinstance(
                event.item,
                ToolCallOutputItem,
            ):
                logger.debug("tool_output=%s", event.item.output)
            elif event.name == "message_output_created" and isinstance(
                event.item,
                MessageOutputItem,
            ):
                logger.debug(
                    "message_output_delta=%s",
                    ItemHelpers.text_message_output(event.item),
                )
            else:
                logger.debug("agent_event=%s item=%s", event.name, event.item)


async def analyze_codeql_row(config: AppConfig, row: CodeQLResultRow) -> str:
    configure_openai_client(config)
    mcp_server: MCPServerStdio = build_mcp_server(config)
    read_source_context_tool: Any = build_read_source_context_tool(config.source_dir)
    read_source_span_tool: Any = build_read_source_span_tool(config.source_dir)
    search_source_text_tool: Any = build_search_source_text_tool(config.source_dir)
    search_source_files_tool: Any = build_search_source_files_tool(config.source_dir)
    await mcp_server.connect()

    try:
        agent = Agent[AnalysisContext](
            name="PostQL CodeQL Triage Agent",
            instructions=(
                "You analyze one CodeQL finding at a time. "
                "Use MCP tools to inspect the code. "
                "Use read_source_context when you need exact local source text. "
                "Use read_source_span for exact line ranges. "
                "Use search_source_text for repository text search. "
                "Use search_source_files to locate files by path or filename. "
                "Prefer position-based queries around the alert location. "
                "Decide whether the finding is real, false positive, or uncertain. "
                "If real, explain trigger path, severity, "
                "and high-level remediation without code."
            ),
            tools=[
                read_source_context_tool,
                read_source_span_tool,
                search_source_text_tool,
                search_source_files_tool,
            ],
            mcp_servers=[mcp_server],
            model=config.openai.model,
        )

        prompt: str = build_triage_prompt(row=row, project_root=config.source_dir)
        run_result = Runner.run_streamed(
            agent,
            prompt,
            context=AnalysisContext(row=row, project_root=config.source_dir),
        )
        await _log_streaming_events(run_result)
        final_output: str = str(run_result.final_output)
        logger.info("analysis_result_row=%s\n%s", row.row_index, final_output)
        return final_output
    finally:
        await mcp_server.cleanup()


def analyze_codeql_row_sync(config: AppConfig, row: CodeQLResultRow) -> str:
    return asyncio.run(analyze_codeql_row(config=config, row=row))
