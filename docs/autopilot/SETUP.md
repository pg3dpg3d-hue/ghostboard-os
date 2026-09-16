# Ghostboard Autonomous Factory — Setup

This bundle adds a cloud-first autonomous development loop to `pg3dpg3d-hue/ghostboard-os`.

It deliberately reuses the existing `.github/workflows/pi5-validation.yml` as the canonical software CI gate.

## Architecture

The system has three trust zones:

1. **Ghostboard Autonomous Factory** — a GitHub Agentic Workflow that wakes hourly but has a 5-hour cooldown. It inspects `main`, open AUTOPILOT PRs, CI and persistent state; selects one iteration; edits code; tests; reviews; repairs BLOCKING findings up to 3 times; then creates or updates one `[AUTOPILOT]` PR. It never writes directly to `main`.
2. **Ghostboard Autopilot Merge Gate** — deterministic GitHub Actions logic. No LLM decides whether CI passed. It accepts only an explicitly software-clean AUTOPILOT PR, rejects mandatory physical Pi validation, dispatches the existing `pi5-validation.yml` on the exact PR head SHA, waits for PASS, squash-merges, then runs the same validation again on `main`.
3. **Ghostboard Autopilot Cycle Reporter** — runs after every real agent execution, ignores cooldown-only runs, reads persistent repo-memory and publishes an `[AUTOPILOT REPORT]` issue.

## Files to copy

- `.github/workflows/ghostboard-autopilot.md`
- `.github/workflows/ghostboard-automerge.yml`
- `.github/workflows/ghostboard-cycle-report.yml`
- `docs/autopilot/STATE-SCHEMA.md`

Do not replace `pi5-validation.yml`.

## GitHub Agentic Workflows

Install the extension:

```bash
gh extension install github/gh-aw
```

Initialize the repository if needed:

```bash
gh aw init --engine codex
```

Compile and validate:

```bash
gh aw compile ghostboard-autopilot
gh aw compile --validate
```

Commit both the source and generated lock workflow:

```text
.github/workflows/ghostboard-autopilot.md
.github/workflows/ghostboard-autopilot.lock.yml
```

Do not hand-edit the generated lock file.

## AI engine

The source currently uses:

```yaml
engine: codex
```

For Codex, configure one of these repository Actions secrets:

```text
CODEX_API_KEY
OPENAI_API_KEY
```

A ChatGPT subscription is separate from OpenAI API billing.

GitHub Agentic Workflows also supports other engines such as Claude, Gemini and Copilot. Change the `engine:` setting, configure that engine's credential, and recompile if you prefer another provider.

## Schedule

The agent source uses:

```yaml
on:
  schedule: hourly
  cooldown: 5h
```

This is intentional: gh-aw supports hourly schedules and a 5-hour cooldown even though a direct fuzzy `every 5h` interval is not supported.

The deterministic merge gate checks every 15 minutes but exits without changes when there is no eligible PR.

## Persistent memory

Repo memory is stored on the orphan branch:

```text
memory/ghostboard-autopilot
```

Durable state:

```text
ghostboard/state.json
ghostboard/history.md
ghostboard/last-report.md
```

The model therefore does not need conversational memory between runs.

## Merge eligibility

An open, non-draft PR from `autopilot/*` targeting `main` is considered only when its body contains:

```text
AUTOPILOT_STATUS: SOFTWARE_CLEAN
AUTOPILOT_AUTOMERGE: YES
BLOCKING_FINDINGS: 0
```

and does not contain:

```text
PHYSICAL_PI5_VALIDATION: MANDATORY
```

The gate then executes the real canonical CI before merging.

## First activation

Run one observed cycle first:

```bash
gh aw run ghostboard-autopilot
```

Verify that it:

1. reads `AGENTS.md`;
2. selects one scoped iteration only;
3. does not edit `.github/**`;
4. creates or updates at most one AUTOPILOT PR;
5. records truthful test evidence;
6. writes the machine-readable PR markers;
7. produces a cycle report.

## Repository Actions permissions

The agent workflow itself is read-only and uses safe outputs for writes.

The deterministic merge workflow requests:

- `contents: write`
- `pull-requests: write`
- `actions: write`
- `issues: write`

Branch protection and repository rules still apply. The workflow never attempts to bypass them.

If repository settings prevent GitHub Actions from creating PRs or merging, enable the relevant GitHub Actions repository permission or use a properly scoped credential.

## Physical Pi 5 validation

Cloud CI is not physical Raspberry Pi validation.

Every AUTOPILOT PR must be marked:

- `MANDATORY`
- `RECOMMENDED`
- `NONE`

`MANDATORY` blocks autonomous merge.

A future extension can add a self-hosted Pi 5 runner as another deterministic merge gate.

## Validation performed on this bundle

The generated bundle is locally checked for:

- YAML parsing of normal GitHub Actions workflows;
- YAML parsing of the gh-aw frontmatter;
- `bash -n` syntax for shell blocks extracted from normal workflows;
- required AUTOPILOT marker consistency.

The authoritative final validation for the Agentic Workflow remains:

```bash
gh aw compile --validate
```

because the current gh-aw compiler owns the full schema and generates the `.lock.yml`.
