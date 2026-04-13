---
name: report-to-poc
description: Turn CodeQL triage reports into minimal proof-of-concept inputs and runner scripts. Use when Codex needs to read a finding from work/results/.../report.json or report.pdf, identify the true trigger condition in the local source tree, decide whether nearby rows are the same root cause, and place a reproducible PoC under a work/poc row directory or a merged directory such as work/poc/90,91,92.
---

# Report To PoC

Convert a validated finding into a small, reproducible PoC that matches the local build and repository layout.

## Workflow

1. Start from structured artifacts.
Read `report.json` first when it exists. Use `report.pdf` only as fallback or for details not present in JSON.

2. Confirm the exact code path locally.
Open the referenced source lines and verify the parser branch, sink, and user-controlled input format. Do not rely on the report wording alone.

3. Decide whether rows should share one PoC.
Merge rows only when they come from the same call site or same root cause and differ only by which output variable CodeQL tracked. If merged, name the folder with comma-separated row numbers such as `work/poc/90,91,92`.

4. Prefer the smallest triggerable input.
Construct the minimum malformed file or argument sequence that reaches the vulnerable code. Favor deterministic parse failures or visible state corruption over large samples.

5. Match the local runtime layout.
If the target binary is under `work/source/utilities`, set the local ImageMagick environment before running:
`MAGICK_CONFIGURE_PATH=.../work/source/config`
`MAGICK_CODER_MODULE_PATH=.../work/source/coders`
`MAGICK_FILTER_MODULE_PATH=.../work/source/filters`

6. Ship both artifact and runner.
Create the malicious input file and a small shell runner script in the PoC directory. The runner should print the input, execute the target, show stderr or decoded output, and explain why the behavior demonstrates the bug.

7. Validate on the current build.
Actually run the PoC. Record the observed symptom that is visible on this build, even if it is only an error path. Do not claim stronger impact than what the local run shows.

8. Add one attack-chain example after the PoC is done.
Write one concrete but non-operational example of how this bug could participate in a larger attack plan. Keep it at the system-design level: describe the surrounding service, what this bug contributes to the chain, what stronger downstream bug would have to exist, and whether the same route would still work if this bug were absent.

## PoC Design Rules

- Prefer `report.json`, source, and local execution over guessing from the PDF.
- Keep PoCs minimal and ASCII unless the format requires otherwise.
- Reuse the repo's established pattern: one input file plus one `run-*.sh` script.
- For unchecked `sscanf` bugs, design inputs that cause partial or zero conversions and then surface the first downstream use of the unwritten variable.
- If the visible outcome is an error like `ImproperImageHeader`, say clearly that the demonstrable symptom is the later rejection while the actual bug is the earlier undefined read.
- If one malformed record after a valid record causes stale-state reuse, include that as a secondary manifestation when it makes the bug easier to see.
- After building the PoC, also produce one threat-model example that explains the bug's possible role in a multi-stage attack without giving step-by-step exploitation instructions.
- In that example, be explicit about whether this bug is a primary primitive, a state-pollution step, a precondition enabler, or merely a weak supporting signal.
- State clearly whether the imagined chain would still work without this bug; if the answer depends on another stronger bug, say so.

## Repo Conventions

- Default output location: `work/poc/<row>` or merged directory.
- Target programs in this repo are often the wrappers under `work/source/utilities/`; run those from `work/source`.
- Preserve existing PoCs and neighboring user files.
- Use concise filenames that describe the bug, for example `txt-uninit-coords-poc.txt` and `run-txt-uninit-coords-poc.sh`.

## Close-Out

When finished, report:

- where the PoC was written
- whether it covers one row or multiple rows
- the exact command used to run it
- the observed runtime behavior on the current build
- one concrete attack-chain example describing this bug's possible role in a larger compromise
