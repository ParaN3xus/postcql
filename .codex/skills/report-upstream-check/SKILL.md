---
name: report-upstream-check
description: Validate local CodeQL triage reports against an upstream Git checkout. Use when the input is either a single report directory such as `work/results/.../0` or a full run directory such as `work/results/...` that contains many numeric report subdirectories, and Codex must decide whether each report's conclusion is correct and whether the reported issue was already fixed upstream, then write `eval.json` artifacts while skipping reports that already have eval output.
---

# Report Upstream Check

Use this skill to evaluate CodeQL report artifacts against the upstream repository at `local/ImageMagick6`.

Treat two input forms differently:
- single report directory: a path like `work/results/analyze-all-20260410-161338Z/0`
- full run directory: a path like `work/results/analyze-all-20260410-161338Z`

For a full run directory:
- enumerate only immediate child directories whose names are pure digits
- skip any directory that already contains `<report_dir>/eval.json`
- prefer launching one subagent per remaining report directory so each evaluation has a fresh, short context window
- cap active subagents at `6`
- keep the parent agent responsible only for enumeration, skip logic, subagent orchestration, and final artifact verification

For every evaluated report directory, write exactly one artifact:

```json
{"upstream_fixed": false, "is_valid": true, "notes": "reasoning summary"}
```

Interpret the fields as:
- `upstream_fixed`: whether the reported issue was fixed upstream after the scanned snapshot
- `is_valid`: whether the report's conclusion is correct
- `notes`: short free-form reasoning, such as the evidence for the decision, important caveats, or the upstream commit that matters most

`is_valid` refers to the report, not directly to the raw CodeQL result. The report is itself a judgment about the CodeQL finding. Example:
- if the report says the CodeQL result is a false positive, and that conclusion is correct, then `is_valid` must be `true`
- if the report says the CodeQL result is a true bug, and that conclusion is correct, then `is_valid` must be `true`
- if the report's conclusion is wrong, then `is_valid` must be `false`

`upstream_fixed` is separate. A report can be valid even when upstream never fixed the issue, so `is_valid` may be `true` while `upstream_fixed` is `false`.

## Inputs to read

Within each report directory:
- read `result.md` first when present
- read `run.json` only when `result.md` is missing details needed to identify the finding, file, snippet, or claim

Extract:
- the reported file and line range
- the suspicious snippet or a stable subexpression
- the report's reasoning about why the code is wrong
- whether the claim is about one exact code segment or a broader invariant

## Core evaluation rule

These reports come from CodeQL output on an older snapshot. The task is to use later upstream history to judge two things separately:

1. Was the report's conclusion about the scanned snapshot correct?
2. Did upstream later fix that reported issue?

Do not collapse these into one conclusion. A valid report may remain unfixed, and an invalid report obviously cannot become "validated" by later upstream changes.

## Batch mode with subagents

When the input is a full run directory, prefer subagents by default.

Parent agent responsibilities:
- list immediate numeric child directories
- skip directories that already have `eval.json`
- launch one independent subagent for each remaining report directory, with at most `6` active at once
- give each subagent only the task-local path and the fixed upstream path `local/ImageMagick6`
- wait for results, confirm that `eval.json` exists, and report any failures

Subagent responsibilities:
- evaluate exactly one report directory
- read only that report's local artifacts plus the upstream repository history needed for the judgment
- decide `upstream_fixed` and `is_valid`
- write exactly one `eval.json` file into its assigned report directory

Prompt shape for a subagent should be direct and narrow, for example:

```text
Use $report-upstream-check at /home/admin/projects/python/codeql-on-clice/.codex/skills/report-upstream-check to evaluate report directory work/results/<run>/<n> against upstream local/ImageMagick6 and write work/results/<run>/<n>/eval.json.
```

Do not ask one subagent to evaluate multiple report directories. The purpose of subagents here is context isolation, not just parallelism.

## Workflow for one report directory

1. Read the local report artifact and identify the exact code claim.
2. Open the corresponding file in `local/ImageMagick6` and inspect the current code.
3. Classify the current upstream state of the exact reported segment:
- `still present`
- `changed`
- `fixed`
- `not comparable`
4. Use Git history to determine whether a later upstream change confirms or refutes the report:
- `git -C local/ImageMagick6 blame -L <start>,<end> -- <file>`
- `git -C local/ImageMagick6 log -S "<stable snippet>" --oneline -- <file>`
- `git -C local/ImageMagick6 show --format=medium --unified=8 <commit> -- <file>`
- `git -C local/ImageMagick6 log --oneline --follow -- <file>` only when rename or rewrite is likely
5. Decide `upstream_fixed`.
6. Decide whether the report's conclusion is correct and set `is_valid`.
7. Summarize the evidence in `notes`.
8. Write `<report_dir>/eval.json`.

When running under batch mode, this entire workflow belongs inside the per-report subagent.

## How to decide `upstream_fixed`

Set `upstream_fixed` to `true` only when the upstream evidence shows that the reported issue was later corrected. Typical evidence:
- a guard, range check, null check, cast, or bounds condition was added that directly blocks the reported failure mode
- a dangerous call or data flow was removed
- a patch message or diff clearly addresses the same defect
- the exact risky code disappeared because the invariant was enforced earlier in the path

Set `upstream_fixed` to `false` when:
- the same risky behavior is still present
- the code changed but the safety effect is unclear
- the location was rewritten and there is no evidence of a real fix for the claimed issue
- the report itself appears invalid

Be strict. "Line changed" is not enough.

## How to decide `is_valid`

Judge validity against the report's conclusion about the scanned snapshot, not only against current upstream.

Remember the object being judged is the report itself. The report may conclude either "true positive" or "false positive". `is_valid` answers whether that conclusion is correct.

Set `is_valid` to `true` when the report's conclusion is supported by code and later upstream history does not undermine the premise. Strong signals:
- a later upstream patch fixes the same issue
- the reported code path clearly violates the claimed invariant
- type definitions, control flow, or data constraints in the scanned code support the report's premise
- the report correctly explains why the CodeQL result is a false positive

Set `is_valid` to `false` when the report's conclusion is wrong. Common cases:
- the supposedly dangerous state cannot occur
- the type/range assumptions in the report are wrong
- the flagged code is safe once surrounding conditions are checked carefully
- later upstream changes do not fix the claim and inspection shows the original reasoning was mistaken
- the report labels the CodeQL result as a false positive but the underlying bug is real
- the report labels the CodeQL result as a real bug but the reasoning does not hold

If evidence is mixed, prefer a conservative explicit judgment based on the code, not on wording in the report.

## Command patterns

Prefer short read-only commands while analyzing:

```bash
sed -n '1,220p' work/results/<run>/<n>/result.md
sed -n '1,260p' work/results/<run>/<n>/run.json
sed -n '<start>,<end>p' local/ImageMagick6/<path/to/file>
rg -n -F "<literal snippet>" local/ImageMagick6
git -C local/ImageMagick6 blame -L <start>,<end> -- <path/to/file>
git -C local/ImageMagick6 log -S "<stable snippet>" --oneline -- <path/to/file>
git -C local/ImageMagick6 show --format=medium --unified=8 <commit> -- <path/to/file>
```

When choosing a snippet for `git log -S`, prefer a short unique subexpression over a large multi-line block.

## Writing `eval.json`

Use `jq` to generate the JSON so the formatting stays fixed. The file must contain exactly these keys:

```json
{"upstream_fixed": true, "is_valid": true, "notes": "reasoning summary"}
```

Preferred pattern:

```bash
jq -n \
  --argjson upstream_fixed true \
  --argjson is_valid true \
  --arg notes "Fixed by <commit>; report conclusion is correct because ..." \
  '{upstream_fixed: $upstream_fixed, is_valid: $is_valid, notes: $notes}' \
  > work/results/<run>/<n>/eval.json
```

Keep `notes` concise but useful. Include the main reason for the judgment, and mention the most relevant commit, invariant, or contradiction when available.

If `jq` is unavailable in the environment, state that explicitly as the blocker instead of silently writing ad hoc JSON by hand.

## Practical cautions

- Distinguish the scanned snapshot from the current `local/ImageMagick6` checkout.
- Use later upstream actions as evidence about truth, but keep the final validity judgment anchored to the original reported code.
- Do not interpret `is_valid` as "the CodeQL result is a true bug". Interpret it as "the report's conclusion is correct", including correct false-positive conclusions.
- If the exact line changed, verify by snippet search and patch inspection instead of trusting stale line numbers.
- If a full run directory is provided, do not touch non-numeric child directories.
- If `eval.json` already exists for a numeric child directory, skip it without recomputing.
- In full-run mode, do not accumulate detailed reasoning for many reports in the parent thread; keep per-report reasoning inside the corresponding subagent.
- Prefer absolute dates when stating when an upstream fix landed.
