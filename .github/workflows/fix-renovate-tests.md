---
on:
  pull_request:
    types: [labeled]
    names: [renovate-fix-needed]

permissions:
  actions: read

tools:
  edit:
  agentic-workflows:
  bash:
    - "git"
    - "cat"
    - "grep"
    - "find"
    - "head"
    - "tail"
    - "wc"

safe-outputs:
  push-to-pull-request-branch:
    target: "*"
    title-prefix: "[renovate-agent]"
    labels: [renovate-fix-needed]
    protected-files: blocked
  remove-labels:
    allowed: [renovate-fix-needed]
  noop:

checkout:
  fetch: ["*"]
  fetch-depth: 0
---

# Fix Renovate Agent Test Failures

You are an expert Python software engineer.

A pull request has been labeled `renovate-fix-needed` on this repository.
This means the `renovate-agent` workflow updated a Python or npm dependency,
ran the test suite, and the tests **failed**.

Your job is to **read the CI failure logs, understand what broke, and fix it**
by making the minimum targeted code changes necessary to make the tests pass —
then push those fixes back to the PR branch.

## Context

- The PR was created automatically by `scripts/renovate_agent.py`.
- Its branch name follows the pattern `renovate-agent/<package>-<version>-<date>`.
- The dependency change is already committed in `pyproject.toml` and `poetry.lock`
  (or `tests_cypress/package.json` for npm packages). **Do NOT modify those files.**
- The failing tests live under `tests/`.

## Step-by-step instructions

### 0. Circuit breaker — check attempt count

Before doing anything else, count how many `[copilot-fix]` commits are already
on this branch:

```bash
git log --oneline | grep -c '\[copilot-fix\]' || true
```

If the count is **3 or more**, the maximum number of automated fix attempts has
been reached. Call `noop` immediately with the message:
"Max fix attempts (3) reached. Human review required."

Do NOT attempt any further fixes.

### 1. Identify the failing CI run

Use the `agentic-workflows` tools to find the most recent failed workflow run
for this PR's branch. Look for:
- Workflow name: "Continuous Integration Testing" or "Continuous Integration Testing (prod feature flags)"
- The run should be on the PR's head branch.

Read the failed job logs to identify:
- Which test(s) failed
- The exact error message and traceback
- Which Python module or import caused the failure

### 2. Analyse the root cause

Possible causes:
- A function, class, or constant was **renamed or removed** in the new dependency version.
  Fix: update references in app code or test code to use the new name.
- A function **signature changed** (new required parameter, removed parameter, etc.).
  Fix: update call sites.
- A new **exception type** is raised. Fix: update `except` clauses.
- A **return type changed** (e.g., dict → object). Fix: update assertions or usage.
- Test fixtures or mocks reference removed symbols. Fix: update the mock targets.

### 3. Decide what to fix

- If app code is calling a removed/renamed API → fix the app code.
- If tests are asserting on behaviour that changed in the new version → fix the tests.
- If both need updating → update both. Use the minimum change required.

### 4. Make the fixes

Edit only the files that need changing. Do NOT touch:
- `pyproject.toml` or `poetry.lock`
- `tests_cypress/package.json` or `tests_cypress/package-lock.json`
- Any file under `.github/`

Use `cat`, `grep`, and `find` to explore the repository before editing.

### 5. Push your fixes

After making all edits, push them to the PR branch using
`push-to-pull-request-branch`. Use a commit message that includes `[copilot-fix]`
so the circuit breaker in step 0 can count previous attempts, e.g.:
`fix: update call sites for marshmallow 3.26.2 API change [copilot-fix]`

Then remove the `renovate-fix-needed` label from the PR using `remove-labels`
to signal that the fix has been applied. A separate workflow will detect the
label removal and push an empty commit to re-trigger CI.

### 6. If no action is needed

Call `noop` with a clear explanation if:
- The CI run is already green (label applied redundantly)
- You cannot determine a safe fix
- The max attempt count was reached (step 0)

**Never** guess at a fix or make changes you are not confident about.
If you are unsure, call `noop` and describe exactly what you found in the logs.

