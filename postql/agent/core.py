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

from ..codeql_csv import CodeQLResultRow
from ..config import DEFAULT_CLANGD_PATH, DEFAULT_MCP_SERVER_COMMAND, AppConfig
from ..logging import logger
from ..run_artifacts import RunArtifacts
from .events import consume_streaming_events
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
) -> str:
    source_path: Path = row.resolved_path(project_root)
    return f"""
You are triaging one CodeQL finding against a real C/C++ codebase.

Primary requirements:
- Use MCP language-server tools aggressively, and prefer position-based queries first.
- Use the local read_source_context tool whenever you need exact source text.
- Use read_source_span when you already know the exact range to inspect.
- Use search_source_text for grep-like repository text search.
- Use search_source_files to locate candidate files by filename/path.
- Some local source tools support pagination. Prefer small pages first and only
  request additional pages when the prior result indicates more content is needed.
- Start from the alert location using hover, diagnostics, references,
  and any other relevant tools.
- Think through the problem step by step before concluding.
- Determine whether the CodeQL alert is a real vulnerability in practice,
  or a false positive / low-signal concern.
- If you need to reason about control flow or data flow, use the available
  code navigation tools to gather evidence before concluding.
- Be explicit about uncertainty.
  Do not claim exploitability unless the code evidence supports it.

Required analysis process:
1. After reading the alert location and nearby code, form an initial hypothesis
   for why CodeQL treated this location as suspicious, using the alert metadata
   and local code context.
2. Validate that hypothesis against the actual program behavior by checking
   surrounding logic, callers, callees, guards, sanitization, data flow,
   control flow, and reachability.
3. Decide whether the condition CodeQL appears to rely on actually holds in the
   real code path.
4. If that CodeQL-based hypothesis does not hold, do not stop there. Evaluate
   whether the code is still unsafe in some other realistic context, and whether
   the behavior can still be triggered.
5. If the behavior is triggerable, explain why with concrete code evidence,
   including the relevant execution path, attacker or input influence, limiting
   conditions, likely impact, severity, and the deeper semantic reason the code
   is unsafe.
6. If the behavior is not realistically triggerable, explain exactly what
   blocks it.

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

The final tool submission must include:
- verdict: REAL, FALSE_POSITIVE, or UNCERTAIN
- severity: low, medium, high, or critical
- explanation
- initial_hypothesis
- hypothesis_validation: a list of validation steps; each step must have a
  message and may optionally include evidence locations
- triggerability
- trigger_path: a list of concrete path steps with file/line info and message
- impact
- remediation

Keep the answer technical and specific to the codebase.

Final submission requirement:
- Do not return a free-form final answer.
- When your investigation is complete, call submit_triage_report exactly once.
- `explanation`, `initial_hypothesis`, and `triggerability` are always required.
- `hypothesis_validation` is always required and should normally be a structured
  sequence of validation steps. Each step must contain a clear conclusion in
  prose, and may optionally attach one or more code evidence locations. Use
  `none` only if you genuinely could not obtain enough code evidence to validate
  the hypothesis.
- `trigger_path` may be `none` when the behavior is not realistically
  triggerable, when the verdict is FALSE_POSITIVE, or when the evidence is too
  incomplete to claim a concrete execution path.
- `impact` may be `none` when there is no realistic attacker-reachable unsafe
  behavior to describe.
- `remediation` may be `none` when there is no concrete vulnerability to fix,
  such as a clear FALSE_POSITIVE with no underlying bug.
- Do not use `none` for convenience. Only use it when the field is genuinely
  not applicable to the final verdict or unsupported by the code evidence.
- hypothesis_validation must be a structured sequence of validation steps, not
  one free-form paragraph.
- Use hypothesis_validation to prove or disprove the initial hypothesis directly
  from the code. For false positives, show the exact guards, missing reachability,
  or contradictory call-flow evidence that blocks the issue. Not every step
  needs an attached code location, but attach evidence where it materially
  strengthens the claim.
- trigger_path must be a structured sequence of path steps, not one free-form paragraph.
""".strip()


async def analyze_codeql_row(
    config: AppConfig,
    row: CodeQLResultRow,
    artifacts: RunArtifacts | None = None,
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
        row=row, artifacts=artifacts
    )
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
                "Those local tools support pagination; prefer small pages first "
                "and only fetch more when needed. "
                "Prefer position-based queries around the alert location. "
                "Think step by step: form an initial hypothesis for why the "
                "alert looks suspicious, validate that hypothesis against the "
                "real code path, and if it does not hold, still evaluate "
                "whether the code is unsafe in some other realistic context. "
                "Write hypothesis_validation as structured validation steps: "
                "each step needs a message, and evidence locations are optional "
                "but encouraged when they materially support the claim. "
                "Decide whether the finding is real, false positive, or uncertain. "
                "Triggerability is always required and must never be `none`. "
                "Only use the literal string `none` for fields that are truly "
                "not applicable to the final verdict or unsupported by the code "
                "evidence, especially trigger_path, impact, and remediation. "
                "When the investigation is complete, call submit_triage_report "
                "exactly once with the final structured result. "
                "Do not end with a normal free-form answer."
            ),
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
        )
        artifacts.add_section(
            "Run Metadata",
            {
                "row_index": row.row_index,
                "rule_name": row.rule_name,
                "severity": row.severity,
                "file": row.relative_file_path,
                "work_dir": config.work_dir,
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
                "Agent finished without any final output; submit_triage_report was likely not called."
            )
        if "structured_report" not in artifacts._payload:
            raise RuntimeError(
                "Agent finished without structured_report; submit_triage_report was not completed."
            )
        if "report_files" not in artifacts._payload:
            raise RuntimeError(
                "Agent finished without report_files; report artifacts were not generated."
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
) -> str:
    return asyncio.run(analyze_codeql_row(config=config, row=row, artifacts=artifacts))
