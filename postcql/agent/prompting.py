from __future__ import annotations

from pathlib import Path

from ..codeql_sarif import CodeQLResultRow, SupportingLocation

TOOL_USAGE_GUIDANCE: str = """
- Use MCP language-server tools aggressively, and prefer position-based queries first.
- Use the local read_source_context tool whenever you need exact source text.
- Use read_source_span when you already know the exact range to inspect.
- Use search_source_text for grep-like repository text search.
- Use search_source_files to locate candidate files by filename/path.
- Some local source tools support pagination. Prefer small pages first and only
  request additional pages when the prior result indicates more content is needed.
- Start from the alert location using hover, diagnostics, references,
  and any other relevant tools.
""".strip()

CLASSIFICATION_GUIDANCE: str = """
- Determine whether the CodeQL alert is REAL, FALSE_POSITIVE, or UNCERTAIN.
- Classification rule: REAL does not require a high-severity security impact.
  If the condition or bug CodeQL identified actually occurs in the real code
  path and is realistically triggerable, classify it as REAL even when the
  impact is only low severity, reliability-only, or otherwise not a strong
  security vulnerability.
- Classification rule: do not treat unavoidable program semantics as a real
  vulnerability when the reported flow is simply the intended feature needed
  for the program to operate. For example, if a command-line tool must open a
  user-specified input file to do its job, a user-controlled path reaching
  `open` is not by itself a real vulnerability unless additional code evidence
  shows unsafe behavior beyond that expected feature boundary.
- Classification rule: some non-best-practice patterns are still REAL when
  they create a meaningful security risk even if the bug looks subtle or
  low-level. For example, creating a temporary file with `mkstemp` but then
  failing to manage the returned file descriptor safely, or reopening the path
  later instead of consistently using the original descriptor, should be
  treated as REAL when the surrounding code makes the resulting race or file
  safety issue realistic.
- Classification rule: treat temporary-file lifecycle regressions as REAL by
  default when code first establishes a temporary file or temporary pathname in
  a safer way, but later falls back to pathname-based handling of that same
  artifact. Typical signals include losing the original descriptor or handle,
  passing the temp pathname through additional subsystems, or reusing the temp
  pathname for later reads, writes, delegate execution, or cleanup. Do not
  dismiss these cases merely because the pathname is library-generated rather
  than copied directly from user input.
- Classification rule: when an alert lands on a cleanup or follow-up operation
  involving a temporary artifact, analyze the whole temporary-file lifecycle
  rather than only the sink line. If nearby code shows that the same temp
  artifact was later reused through pathname semantics, related cleanup
  findings should normally follow the same verdict as that underlying
  temporary-file handling issue.
- Classification rule: avoid line-local reasoning for temporary resources. A
  cleanup sink is not automatically safe just because it deletes a
  library-generated temp path; if the surrounding lifecycle for that same temp
  artifact already regressed to less-safe pathname-based handling, classify the
  cleanup finding consistently with that broader issue unless the code shows it
  is a different artifact or a different control-flow path.
- Classification rule: do not break the temporary-file lifecycle just because
  the temp path is wrapped inside another object or string representation
  before later use. If code writes or creates a temp artifact and then passes
  that artifact into another API by embedding the pathname into a cloned info
  struct, a format-prefixed filename string, a delegate command, or another
  derived wrapper, that still counts as later pathname-based reuse of the same
  temp artifact.
- Classification rule: do not over-index on style-only or hygiene-only issues.
  If a pattern is merely non-ideal but the code evidence does not show a
  realistic security consequence, classify it as FALSE_POSITIVE rather than
  treating every non-best-practice as a real vulnerability.
- Classification rule: use FALSE_POSITIVE when the CodeQL-implied condition
  does not actually hold on the real path, or is blocked by guards,
  sanitization, type/range constraints, or missing reachability.
- Classification rule: use UNCERTAIN when the available code evidence is not
  strong enough to decide between REAL and FALSE_POSITIVE.
- Classification rule: when macro-controlled code makes the real behavior
  ambiguous, treat the effective build configuration in `compile_commands.json`
  as the source of truth for which macros and paths actually apply.
- Be explicit about uncertainty.
  Do not claim exploitability unless the code evidence supports it.
""".strip()

STRUCTURED_OUTPUT_GUIDANCE: str = """
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
- Any `file_path` attached in `hypothesis_validation.evidence` or `trigger_path`
  must be a source-relative repository path such as `magick/utility.c`, never
  an absolute filesystem path.
- Any attached source range must refer to a real file and valid 1-based line
  numbers within that file. Do not invent ranges that extend past the file's
  actual line count.
- Keep verdict and triggerability logically consistent. Do not mark a finding
  FALSE_POSITIVE if your analysis says the CodeQL-identified condition really
  happens and is triggerable; in that case classify it as REAL and describe the
  actual impact level separately.
- trigger_path must be a structured sequence of path steps, not one free-form paragraph.
- These fields are rendered directly as section content under Markdown headings in
  the final report. Write them as clean prose paragraphs or structured steps,
  not as `Field Name: value` labels.
- Use normal sentence casing and paragraph formatting. Start sentences with a
  capital letter, and do not prefix the body text with redundant item names such
  as `Explanation:` or `Impact:`.
""".strip()

SUBMIT_TRIAGE_REPORT_DOC: str = """
Submit the final structured triage report for this finding.

`triggerability` is mandatory and must never be `none`.
If the CodeQL-identified condition actually holds on a real,
triggerable path, classify the finding as `real` even when the impact
is low severity or not a strong security vulnerability.
Use `false_positive` when the condition does not hold in the real code
path or is blocked in practice. Use `uncertain` when the evidence is
insufficient to decide.
Use the literal string `none` only for fields that are genuinely not
applicable to the final verdict or unsupported by code evidence.
In practice this usually applies to `trigger_path`, `impact`, and
`remediation`; use it for `hypothesis_validation` only when code
validation could not be completed.
""".strip()

TEST_MODE_GUIDANCE: str = """
Test mode is enabled.
- Do not perform real investigation.
- Do not call MCP tools or local source-reading/search tools.
- Immediately call `submit_triage_report` exactly once.
- Generate synthetic but schema-valid content for every required field.
- The output must look like a plausible triage report, but it is
  intentionally fabricated for testing.
- Do not default to `uncertain`.
- Vary the result distribution across rows by deriving fields from `row_index`:
  verdict = [`real`, `false_positive`, `uncertain`][row_index mod 3]
  severity = [`low`, `medium`, `high`, `critical`][row_index mod 4]
- Keep `triggerability` non-`none`.
- Any `file_path` used in `hypothesis_validation.evidence` or `trigger_path`
  must be a repository-relative source path such as `magick/utility.c`, never
  an absolute filesystem path.
- Keep the other fields logically consistent with the chosen verdict and severity.
""".strip()


def _optional_text(value: str | None) -> str:
    return value if value else "none"


def _format_supporting_location(location: SupportingLocation) -> str:
    location_label: str = (
        f"{location.file_path}:{location.start.line}:{location.start.column}"
    )
    message: str = location.message or "no message"
    if location.location_id is None:
        return f"- {location_label} - {message}"
    return f"- [id={location.location_id}] {location_label} - {message}"


def _render_related_locations(row: CodeQLResultRow, limit: int = 8) -> str:
    if not row.related_locations:
        return "- none"
    rendered: list[str] = [
        _format_supporting_location(location)
        for location in row.related_locations[:limit]
    ]
    if len(row.related_locations) > limit:
        rendered.append(
            f"- ... {len(row.related_locations) - limit} more related locations omitted"
        )
    return "\n".join(rendered)


def _render_code_flows(
    row: CodeQLResultRow,
    max_flows: int = 2,
    max_steps_per_flow: int = 6,
) -> str:
    if not row.code_flows:
        return "- none"
    rendered_flows: list[str] = []
    for code_flow in row.code_flows[:max_flows]:
        flow_lines: list[str] = [f"- thread_flow_index={code_flow.thread_flow_index}"]
        for step in code_flow.steps[:max_steps_per_flow]:
            step_label: str = f"{step.file_path}:{step.start.line}:{step.start.column}"
            step_message: str = step.message or "no message"
            flow_lines.append(f"  - {step_label} - {step_message}")
        if len(code_flow.steps) > max_steps_per_flow:
            flow_lines.append(
                "  - ... "
                f"{len(code_flow.steps) - max_steps_per_flow} more steps omitted"
            )
        rendered_flows.append("\n".join(flow_lines))
    if len(row.code_flows) > max_flows:
        rendered_flows.append(
            f"- ... {len(row.code_flows) - max_flows} more code flows omitted"
        )
    return "\n".join(rendered_flows)


def build_agent_instructions(test_mode: bool = False) -> str:
    if test_mode:
        return " ".join(
            [
                "You analyze one CodeQL finding at a time.",
                "The available tools include MCP code inspection tools, "
                "local source tools, and submit_triage_report.",
                "In test mode, do not inspect code and do not use any tool "
                "except submit_triage_report.",
                "Produce one synthetic structured result and call "
                "submit_triage_report exactly once.",
                "Do not end with a normal free-form answer.",
            ]
        )
    return " ".join(
        [
            "You analyze one CodeQL finding at a time.",
            "Use MCP tools to inspect the code.",
            "Use read_source_context when you need exact local source text.",
            "Use read_source_span for exact line ranges.",
            "Use search_source_text for repository text search.",
            "Use search_source_files to locate files by path or filename.",
            "Those local tools support pagination; prefer small pages first "
            "and only fetch more when needed.",
            "Prefer position-based queries around the alert location.",
            "Think step by step: form an initial hypothesis for why the "
            "alert looks suspicious, validate that hypothesis against the "
            "real code path, and if it does not hold, still evaluate whether "
            "the code is unsafe in some other realistic context.",
            "Write hypothesis_validation as structured validation steps: "
            "each step needs a message, and evidence locations are optional "
            "but encouraged when they materially support the claim.",
            "Decide whether the finding is real, false positive, or uncertain.",
            "A real finding does not require a strong security impact; if "
            "the CodeQL-identified condition actually occurs on a real, "
            "triggerable path, classify it as real even if the result is "
            "only low severity or reliability-oriented.",
            "Do not treat an intended, unavoidable program behavior as a "
            "real vulnerability when that behavior is simply required for "
            "the program to function, such as a CLI opening a user-selected "
            "input file, unless there is additional unsafe behavior beyond "
            "that feature boundary.",
            "Do treat non-best-practice code as real when it creates a "
            "meaningful security risk in context, such as unsafe `mkstemp` "
            "descriptor handling or reopening a temporary-file path instead "
            "of consistently using the original file descriptor.",
            "Treat temporary-file lifecycle regressions as real by default "
            "when code first creates or acquires a temporary artifact in a "
            "safer way but later falls back to pathname-based handling of "
            "that same artifact.",
            "When the alert lands on a cleanup or follow-up line involving "
            "a temporary artifact, reason about the entire temporary-file "
            "lifecycle rather than the sink in isolation; related cleanup "
            "findings should normally inherit the same verdict as the "
            "underlying temp-file handling issue.",
            "Do not assume a cleanup sink is safe merely because it targets "
            "a library-generated temp path; if the same temp artifact was "
            "already handled unsafely through pathname-based reuse, keep the "
            "cleanup finding aligned with that broader lifecycle issue unless "
            "the code clearly shows a different artifact or path.",
            "Do not lose the temp-file lifecycle merely because the temp "
            "pathname is wrapped into another object or derived string "
            "before later use; cloned info structs, prefixed filenames, and "
            "similar wrappers still count as pathname-based reuse of the "
            "same temp artifact.",
            "Do not treat every non-best-practice as real; if the code "
            "evidence does not show a realistic security consequence, "
            "classify it as false positive.",
            "Use false positive when the condition does not actually hold "
            "on the real path or is blocked in practice.",
            "Use uncertain when the code evidence is insufficient to decide.",
            "Triggerability is always required and must never be `none`.",
            "Only use the literal string `none` for fields that are truly "
            "not applicable to the final verdict or unsupported by the code "
            "evidence, especially trigger_path, impact, and remediation.",
            "When the investigation is complete, call submit_triage_report "
            "exactly once with the final structured result.",
            "Do not end with a normal free-form answer.",
        ]
    )


def build_triage_prompt_text(
    row: CodeQLResultRow,
    project_root: Path,
    test_mode: bool = False,
) -> str:
    source_path: Path = row.resolved_path(project_root)
    if test_mode:
        return f"""
You are triaging one CodeQL finding against a real C/C++ codebase.

Available tools:
- MCP language-server tools for code inspection
- read_source_context
- read_source_span
- search_source_text
- search_source_files
- submit_triage_report

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
- rule_full_description: {row.rule_full_description}
- rule_precision: {_optional_text(row.rule_precision)}
- rule_problem_severity: {_optional_text(row.rule_problem_severity)}
- rule_security_severity: {_optional_text(row.rule_security_severity)}
- alert_message: {row.message}

CodeQL related locations:
{_render_related_locations(row)}

CodeQL code flows:
{_render_code_flows(row)}

Required submit_triage_report fields:
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

Final submission requirement:
- Do not return a free-form final answer.
- Call submit_triage_report exactly once.
{STRUCTURED_OUTPUT_GUIDANCE}

{TEST_MODE_GUIDANCE}
""".strip()
    prompt: str = f"""
You are triaging one CodeQL finding against a real C/C++ codebase.

Primary requirements:
{TOOL_USAGE_GUIDANCE}
- Think through the problem step by step before concluding.
{CLASSIFICATION_GUIDANCE}
- If you need to reason about control flow or data flow, use the available
  code navigation tools to gather evidence before concluding.

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
- rule_full_description: {row.rule_full_description}
- rule_precision: {_optional_text(row.rule_precision)}
- rule_problem_severity: {_optional_text(row.rule_problem_severity)}
- rule_security_severity: {_optional_text(row.rule_security_severity)}
- alert_message: {row.message}

CodeQL related locations:
{_render_related_locations(row)}

CodeQL code flows:
{_render_code_flows(row)}

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
{STRUCTURED_OUTPUT_GUIDANCE}
""".strip()
    return prompt
