# Renovate Agent – Setup Guide

The **renovate-agent** is a GitHub Actions workflow that automatically creates pull requests for
dependency upgrades identified in open Renovate PRs.  It selects only packages where the
[Mend merge-confidence](https://docs.renovatebot.com/merge-confidence/) data shows **age > 30 days**
and **confidence = high or very high**, ensuring only battle-tested upgrades are promoted.

## How It Works

1. **Schedule / trigger** – the workflow runs every Monday at 08:00 UTC, or can be triggered
   manually via `workflow_dispatch`.
2. **Guard** – if a PR with the `renovate-agent` label is already open, the workflow exits
   immediately (one PR at a time).
3. **Discovery** – scans all open PRs labelled `Renovate`, parses their update tables, and
   fetches the Mend age/confidence badges for each package row.
4. **Selection** – picks the single most eligible package (highest age first, alphabetical
   on ties).
5. **Apply** – updates `pyproject.toml` (Python/pypi) or `tests_cypress/package.json` (npm),
   regenerates the lockfile, and pushes a new branch.
6. **Test** – runs the full Python test suite on the new branch.
7. **PR** – only if tests pass, opens a PR against `main` and adds the `renovate-agent` label.
8. **Cleanup** – if tests fail the remote branch is deleted; no PR is opened.

---

## Prerequisites

| Requirement | Details |
|---|---|
| GitHub repository | `cds-snc/notification-api` (or your fork) |
| GitHub App | Used to create branches, commits, and PRs with a dedicated identity |
| Repository label | `renovate-agent` must exist (see below) |

---

## Step 1 – Create the GitHub App

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
   (or your organisation's equivalent URL: `https://github.com/organizations/<org>/settings/apps/new`).

2. Fill in the form:

   | Field | Value |
   |---|---|
   | **App name** | `notification-api-renovate-agent` (must be globally unique) |
   | **Homepage URL** | `https://github.com/cds-snc/notification-api` |
   | **Webhook** | Uncheck "Active" – webhooks are not needed |

3. Set the following **Repository permissions** (everything else can remain *No access*):

   | Permission | Level |
   |---|---|
   | Contents | **Read & write** |
   | Metadata | **Read-only** (required) |
   | Pull requests | **Read & write** |

4. Under **Where can this GitHub App be installed?**, choose **Only on this account**.

5. Click **Create GitHub App**.

6. On the resulting page note the **App ID** (a number, e.g. `123456`).

7. Scroll to **Private keys** → **Generate a private key**.  A `.pem` file is downloaded
   automatically – keep it secure.

---

## Step 2 – Install the App on the Repository

1. In the App settings page, click **Install App** in the left sidebar.
2. Click **Install** next to your organisation / account.
3. Choose **Only select repositories** → select `cds-snc/notification-api` (or your target repo).
4. Click **Install**.

---

## Step 3 – Add Repository Secrets and Variables

In the target repository go to **Settings → Secrets and variables → Actions**.

### Secrets (`Settings → Secrets → Actions → New repository secret`)

| Name | Value |
|---|---|
| `RENOVATE_AGENT_PRIVATE_KEY` | Paste the **full contents** of the `.pem` file downloaded in Step 1, including the `-----BEGIN RSA PRIVATE KEY-----` header and footer lines. |

### Variables (`Settings → Variables → Actions → New repository variable`)

| Name | Value |
|---|---|
| `RENOVATE_AGENT_APP_ID` | The **App ID** from Step 1 (numeric, e.g. `123456`). |

> **Why a variable for the App ID?**  App IDs are not sensitive – they appear in GitHub's public
> API responses.  Storing them as variables (not secrets) keeps them visible in the Actions UI,
> making troubleshooting easier.

---

## Step 4 – Create the `renovate-agent` Label

The workflow applies the label `renovate-agent` to PRs it creates, and also checks for this label
to enforce the "one PR at a time" rule.  The label must exist in the repository before the first
run.

1. In the repository go to **Issues → Labels → New label**.
2. Set:
   - **Name**: `renovate-agent`
   - **Color**: `#0075ca` (blue – or any colour you prefer)
   - **Description**: `Automated dependency upgrade opened by the renovate-agent workflow`
3. Click **Create label**.

---

## Step 5 – Verify the Workflow

1. Go to **Actions → Renovate Agent** in the repository.
2. Click **Run workflow** → **Run workflow** (leave *Dry run* as `false`).
3. Watch the run:
   - If an existing `renovate-agent` PR is open the run will exit in step 3.
   - Otherwise it will scan Renovate PRs, apply any eligible upgrade, run tests, and open a PR.
4. For a safe first test, use **Dry run = true** – this runs the discovery phase only and
   does NOT commit or open a PR.

---

## Eligibility Rules (reference)

| Criterion | Rule |
|---|---|
| Age | The new package version must have been published **more than 30 days** ago (Mend merge-confidence badge). |
| Confidence | Mend merge-confidence must report **"high"** or **"very high"** for the `from → to` version pair. |
| Ecosystem | Only `pypi` (Poetry) and `npm` (`tests_cypress/package.json`) packages are supported. |
| One PR | If a PR with label `renovate-agent` is already **open**, no new PR is created. |

When multiple packages are eligible the one with the **highest age** is chosen first; ties are
broken alphabetically by package name.

---

## Troubleshooting

### The workflow exits immediately with "An open renovate-agent PR already exists"

A previous agent PR is still open.  Merge or close it, then re-trigger the workflow.

### Badge values could not be determined

The Mend merge-confidence API (`developer.mend.io`) was unreachable or returned unexpected content.
The package is skipped.  Check the workflow logs for the badge URL and try it manually in a browser.

### Tests fail after the dependency update

The branch is automatically deleted.  The failing test output is available in the workflow logs
as annotations.  To investigate:

1. Temporarily run the workflow with **Dry run = true** to identify which package would be selected.
2. Manually apply the same `pyproject.toml` change on a local branch and run `poetry run make test`.

### "poetry check --lock" fails

The `poetry.lock` file in `main` is out of sync with `pyproject.toml`.  Run
`poetry lock --no-update` locally and push the updated lock file.
