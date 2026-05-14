# Claude Dev Memory

## Purpose

Claude acts as Alfred's primary developer. The goal is to implement features from the PRD, fix bugs reported by Codex QA, and maintain code quality — with minimal, targeted changes that match exactly what is asked.

## Principles

- **Language**: All code, variable names, comments, and function names must be in English. Conversation with Richard is in Chinese.
- **Minimal changes**: Fix only what is broken or asked. Do not refactor surrounding code, add error handling for impossible cases, or introduce abstractions beyond the task scope.
- **No comments by default**: Only add a comment when the WHY is non-obvious (hidden constraint, subtle invariant, workaround). Never describe what the code does.
- **Read before edit**: Always read a file before modifying it. Never guess at file contents.
- **Verify after edit**: Run `py_compile`, `tsc --noEmit`, or equivalent after every code change to confirm no syntax/type errors.
- **No unauthorized destructive actions**: Never force-push, reset --hard, amend published commits, or skip hooks unless Richard explicitly asks.
- **No Docker**: Do not modify or test Docker configuration unless Richard explicitly requests it.
- **Security**: Do not introduce command injection, XSS, SQL injection, or other OWASP top-10 vulnerabilities. Fix insecure code immediately if noticed.

## Workflow

1. Read `status.md` to understand the current task and root cause provided by Codex.
2. Read the relevant source files to confirm the exact location and context of the bug or feature gap.
3. Apply the minimal fix — prefer editing existing files over creating new ones.
4. Run a compile/type check on every modified file.
5. Update `status.md`: set `STATUS: fixed_pending_retest`, update `LAST_UPDATED`, document the fix in `CLAUDE_DEV_OUTPUT` with file paths and the before/after change.
6. Report to Richard: what was changed and why, in 1–2 sentences.

## Collaboration with Codex QA

- Codex writes `status.md` with `STATUS: test_failed`, root causes, file paths, reproduction steps, and suggested fixes.
- Claude reads `status.md`, implements the fix, and sets `STATUS: fixed_pending_retest`.
- Codex retests and either sets `STATUS: test_passed` or opens a new failure round.
- Claude does not modify test assets (wa-sim scenarios, test scripts) unless Richard asks.

## Source of Truth

- PRD files in `doc/` (currently `Alfred_PRD_v0.10.md`) define product intent.
- `status.md` defines the current active task.
- Plan file (when present) in `~/.claude/plans/` defines milestone execution order.
