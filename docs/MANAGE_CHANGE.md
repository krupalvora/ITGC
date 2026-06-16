# Manage Change — Change Management & Merge Gate

> An approval record for every code change, plus a GitHub Actions **merge gate**
> that blocks a pull request from merging into a protected branch (`staging`,
> `prod`, …) until a matching **Manage Change** record has been approved in Frappe.

- [What it does](#what-it-does)
- [Core concepts](#core-concepts)
- [Setup — Part A: Frappe side](#setup--part-a-frappe-side)
- [Setup — Part B: GitHub side](#setup--part-b-github-side)
- [The approval workflow](#the-approval-workflow)
- [The merge gate explained](#the-merge-gate-explained)
- [Worked example](#worked-example)
- [Troubleshooting](#troubleshooting)

---

## What it does

Manage Change has two halves that work together:

1. **In Frappe** — a **Manage Change** record captures a proposed code change
   (which app, which branch, the PR URL, the ticket, the change type) and runs it
   through a `Pending → Approved` approval workflow. The department's HODs are the
   approvers.
2. **In GitHub** — two GitHub Actions workflows poll a token-protected Frappe
   endpoint on every PR to a gated branch. The PR's status check stays **red**
   (merge blocked) until an **approved** Manage Change record exists for that exact
   PR URL + branch.

The result: nothing reaches `staging`/`prod` without a recorded, approved change.

<!-- IMAGE: mc-pr-check-failing.png
     Screenshot of a GitHub PR with the "Check Manage Change is approved" status check
     RED / failing, blocking the merge button. -->
![PR blocked until the Manage Change is approved](images/mc-pr-check-failing.png)

---

## Core concepts

### Roles

| Role | Meaning |
| --- | --- |
| **Manage Change Requester** | May **raise** (create) a Manage Change. Cannot approve. |
| **Manage Change Approver** | May **act on the workflow** (approve / reject). The *capability* to approve; the *identity* is narrowed per-record to the department's HODs. |

### Departments & HODs

- A **Manage Change Department** holds a list of **Approvers** (HODs).
- When a Manage Change is saved, its read-only **Approver** table is populated from
  the chosen department's HODs — they are the people who can approve that record.

### Masters

| Master | Purpose |
| --- | --- |
| **Manage Change VC Branch** | The set of branches the gate protects (e.g. `staging`, `prod`). The record **name must equal the git base branch name exactly** — the gate compares them with an exact string match. |
| **Manage Change Type** | A categorisation of the change (e.g. `Feature`, `Bugfix`, `Hotfix`). |
| **Manage Change Department** | Approval routing (above). |

### Key record fields

| Field | Notes |
| --- | --- |
| **ERP App** | Dropdown of apps actually installed on this site. |
| **Branch** | Link to a Manage Change VC Branch (the gated branch). |
| **Version Control URL** | The PR URL. Defaults to `Not Set`; **fillable after submit** (so you can attach the PR once it's raised). Once a real URL is saved it is **locked** (immutable) and **unique** — one PR maps to exactly one Manage Change. To gate a different PR, raise a new record. |
| **Change Type / Department / Ticket / Ticket ID / Description** | Metadata. If **Ticket ID** is set it becomes the record name; otherwise it's `MC-YYYY-MM-DD-##`. |
| **Approver** | Read-only, synced from the department's HODs. |

---

## Setup — Part A: Frappe side

### Step 1 — Create the masters

**1a. Branches to protect.** Create one **Manage Change VC Branch** per gated
branch. **Name it exactly like the git branch** (`staging`, `prod`, …).

<!-- IMAGE: mc-vc-branch.png
     Screenshot of a new Manage Change VC Branch record named e.g. "prod". -->
![Manage Change VC Branch](images/mc-vc-branch.png)

**1b. Change types.** Create a few **Manage Change Type** records
(`Feature`, `Bugfix`, `Hotfix`, …).

**1c. Department(s).** Create a **Manage Change Department** with its HODs.

> New → **Manage Change Department**
> - **Department Name** — e.g. `Engineering`
> - **Approver** — the HOD user(s) who approve changes for this department

<!-- IMAGE: mc-department.png
     Screenshot of a Manage Change Department with Department Name and one/two HOD users. -->
![Manage Change Department with HODs](images/mc-department.png)

### Step 2 — Configure ITGC Settings (Manage Change tab)

> Awesomebar → **ITGC Settings** → **Manage Change** tab

1. **Manage Change Status API Token** *(mandatory when enabling)* — generate a
   strong random secret and paste it here. You'll store the **same** value as a
   GitHub secret in Part B.

   ```bash
   openssl rand -hex 32
   # or
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   > The status endpoint is **always token-protected (fail-closed)**: there is no
   > public mode. Callers must send this token in the `X-ITGC-Token` header, and if
   > no token is configured every call is rejected.

2. **Send Approval Notifications** *(optional)* — email + in-app notify the
   department approvers when a change is raised, and notify the requester when it's
   approved/rejected.

3. Tick **Enable Change Management** and **Save** — this activates the
   `ITGC Manage Change Approval` workflow.

<!-- IMAGE: mc-settings.png
     Screenshot of ITGC Settings -> Manage Change tab: Enable Change Management ticked,
     API token field filled (masked), Send Approval Notifications ticked. -->
![ITGC Settings — Manage Change tab](images/mc-settings.png)

### Step 3 — Add the workflow files to each gated repo (one-time per app)

The gate is enforced by two GitHub Actions files that must live in **the target
app's own repo**:

| File | Purpose |
| --- | --- |
| `.github/workflows/manage-change-check.yml` | On every PR to a gated branch, polls the ITGC endpoint and fails the check until the change is approved. |
| `.github/workflows/manage-change-recheck.yml` | Lets a maintainer comment `/recheck` to re-poll without pushing a new commit. |

Copy them from the canonical source in the **itgc** app and commit them via a
normal PR in the target app's repo:

```bash
mkdir -p apps/<your_app>/.github/workflows
cp apps/itgc/.github/workflows/manage-change-*.yml apps/<your_app>/.github/workflows/
```

> **Why manual?** The app refuses to **submit** a Manage Change for an app whose
> repo is missing these files (it would create a record that can never gate a PR).
> It deliberately does *not* auto-copy them — that would write into another app's
> source tree without going through that app's PR review, weakening the separation
> of duties the gate exists to enforce. After the files are merged, re-submit.

---

## Setup — Part B: GitHub side

In each gated repo: **Settings → Secrets and variables → Actions**.

> **Tip — multiple environments.** The workflow is config-driven. For a PR into
> branch `<b>` it derives an env key (uppercase the branch, non-alphanumerics →
> `_`) and looks up `ITGC_BASE_URL_<ENV>` / `ITGC_GATE_TOKEN_<ENV>`, falling back
> to the generic `ITGC_BASE_URL` / `ITGC_GATE_TOKEN`. So a `staging` PR can hit the
> staging ERP and a `prod` PR the prod ERP. See
> [`.github/MANAGE_CHANGE_GATE.md`](../.github/MANAGE_CHANGE_GATE.md) for the full
> multi-environment guide.

### B1 — Variable: the Frappe site URL

**Variables** tab → *New repository variable*
- **Name:** `ITGC_BASE_URL` (or `ITGC_BASE_URL_PROD`, `ITGC_BASE_URL_STAGING`, …)
- **Value:** your Frappe site URL, no trailing path — e.g.
  `https://stagingerp.example.com`

<!-- IMAGE: gh-variables.png
     GitHub Settings -> Secrets and variables -> Actions -> Variables tab, showing
     ITGC_BASE_URL. -->
![Repository variable ITGC_BASE_URL](images/gh-variables.png)

### B2 — Secret: the gate token

**Secrets** tab → *New repository secret*
- **Name:** `ITGC_GATE_TOKEN` (or `ITGC_GATE_TOKEN_PROD`, …)
- **Value:** the **exact same string** you put in ITGC Settings in Step 2.

<!-- IMAGE: gh-secrets.png
     GitHub Secrets tab showing ITGC_GATE_TOKEN. -->
![Repository secret ITGC_GATE_TOKEN](images/gh-secrets.png)

> `GITHUB_TOKEN` (used by the `/recheck` workflow) is injected by Actions
> automatically — there is **no PAT to create**.

### B3 — Make the check required (branch protection)

So PRs cannot merge while the check is red:

**Settings → Branches → Add rule** for each gated branch → *Require status checks
to pass before merging* → select **"Check Manage Change is approved"**.

<!-- IMAGE: branch-protection.png
     GitHub branch protection rule with the required status check selected. -->
![Branch protection — required status check](images/branch-protection.png)

### Tokens & secrets at a glance

| Name | Type | Where | How you get it |
| --- | --- | --- | --- |
| **Gate token** | shared secret | ITGC Settings **and** GitHub secret `ITGC_GATE_TOKEN` | You generate it (Step 2). |
| `ITGC_BASE_URL` | repo **variable** | GitHub → Variables | Your Frappe site URL. |
| `GITHUB_TOKEN` | auto | provided by Actions | Nothing to do — built in. |

---

## The approval workflow

`ITGC Manage Change Approval` drives the record through three states:

```
            ┌──────────┐  Approve (HOD)        ┌──────────┐
            │ Pending  │ ────────────────────▶ │ Approved │  (docstatus 1 → gates the PR)
   raise ──▶│          │                        └──────────┘
            │          │  Reject (HOD)          ┌──────────┐
            │          │ ────────────────────▶ │ Rejected │
            └──────────┘                        └────┬─────┘
                  ▲          Resubmit (requester)    │
                  └──────────────────────────────────┘
```

- **Approve** / **Reject** can only be done by a user in the record's **Approver**
  table (capability = `Manage Change Approver` role; identity = the department's
  HODs). **Self-approval is off.**
- **Approve** submits the record (`docstatus 1`) — that's what the merge gate reads
  as "approved".
- **Reject** keeps it editable; only the **requester** may fix and **Resubmit**.
- If **Send Approval Notifications** is on, approvers are emailed/notified when a
  change is raised, and the requester when it's approved or rejected.

<!-- IMAGE: mc-workflow-actions.png
     Screenshot of a Pending Manage Change record showing the Approve / Reject workflow
     buttons. -->
![Workflow actions on a pending change](images/mc-workflow-actions.png)

---

## The merge gate explained

The check workflow calls `itgc.api.manage_change_gate.check_pr_approval` with the
PR URL and target branch, sending the token in the `X-ITGC-Token` header. A PR is
**approved** only when a Manage Change exists with that exact **Version Control
URL** + **Branch** and is **submitted** (`docstatus 1`).

The endpoint returns one of these reasons — surfaced back on the PR:

| Reason | Meaning | Fix |
| --- | --- | --- |
| `submitted` | ✅ Approved — merge allowed. | — |
| `unauthorized` | Token missing / mismatched, or none configured. | Re-check the token matches in ITGC Settings **and** the GitHub secret. |
| `missing_parameters` | Workflow didn't send `pr_url` / `target_branch`. | Check the workflow config / `ITGC_BASE_URL`. |
| `unknown_branch` | No **Manage Change VC Branch** matches the PR's base branch. | Register the branch (Step 1a), or the PR is pointed at the wrong environment's ERP. |
| `branch_mismatch` | A Manage Change is bound to this PR URL but on a **different** branch. | Fix the record's Branch (or the VC Branch name) to match the git base ref exactly. |
| `no_manage_change_record` | No submitted Manage Change for this PR URL + branch. | Set **Version Control URL** on the approved record to the PR URL. |
| `not_submitted` | Record exists but isn't approved yet (`docstatus != 1`). | Get it approved. |

> Need to re-run the check without a new commit? A maintainer comments
> **`/recheck`** on the PR (handled by `manage-change-recheck.yml`).

### Rotating the token

Generate a new value, then update **both** the GitHub secret and the ITGC Settings
token field. They must change together or the gate returns `401 unauthorized`.

---

## Worked example

**Scenario:** *Aman* (Engineering) opens PR **#142** into the **`prod`** branch of
the `my_app` app. *Neha* is the Engineering HOD.

### 1. Prerequisites (one-time)

- A `prod` **Manage Change VC Branch** exists.
- An `Engineering` **Manage Change Department** lists **Neha** as approver.
- The two workflow files are committed in `my_app`'s repo, and
  `ITGC_BASE_URL` / `ITGC_GATE_TOKEN` are set in GitHub. Branch protection requires
  the check on `prod`.

### 2. Aman raises the Manage Change

> New → **Manage Change**
> - **ERP App:** `my_app`
> - **Branch:** `prod`
> - **Change Type:** `Feature`
> - **Department:** `Engineering`
> - **Ticket ID:** `TICK-1234`, **Description:** what's changing
> - **Save** → then **Submit** (workflow state **Pending**)

On save, the **Approver** table auto-fills with **Neha**.

<!-- IMAGE: mc-example-record.png
     Screenshot of Aman's Manage Change: ERP App = my_app, Branch = prod,
     Change Type = Feature, Department = Engineering, Approver = Neha, state = Pending. -->
![Aman's Manage Change — Pending](images/mc-example-record.png)

### 3. Aman opens PR #142 and attaches it

Once the PR exists, Aman edits **Version Control URL** on the record (allowed even
after submit) and pastes the PR URL, e.g.
`https://github.com/org/my_app/pull/142`. It's now **locked** to that PR.

<!-- IMAGE: mc-example-prurl.png
     Screenshot of the Version Control URL field on the record filled with the PR link. -->
![Version Control URL bound to the PR](images/mc-example-prurl.png)

At this point the PR's check is still **red** — reason `not_submitted` if not yet
approved (or `no_manage_change_record` until the URL is attached).

### 4. Neha approves

Neha opens the record and clicks **Approve**. State → **Approved**
(`docstatus 1`).

<!-- IMAGE: mc-example-approved.png
     Screenshot of the record after Neha approves: workflow state Approved. -->
![Change approved by HOD](images/mc-example-approved.png)

### 5. The PR check goes green

On the next check (push, or a `/recheck` comment) the gate finds the approved
record for PR #142 on `prod` and returns `submitted`. The status check turns
**green** and the PR can be merged.

<!-- IMAGE: mc-pr-check-passing.png
     Screenshot of the GitHub PR with the "Check Manage Change is approved" status check
     GREEN, merge button enabled. -->
![PR check passing — merge allowed](images/mc-pr-check-passing.png)

---

## Troubleshooting

| Symptom | Cause / Fix |
| --- | --- |
| Check is red with `unauthorized` | Token mismatch — make the ITGC Settings token and the GitHub `ITGC_GATE_TOKEN` secret identical. |
| Check is red with `unknown_branch` | No VC Branch named exactly like the PR's base branch — create one. |
| Check is red with `branch_mismatch` | The record's Branch ≠ the PR's base branch — fix the Branch / VC Branch name. |
| Check is red with `no_manage_change_record` | Attach the PR URL to the approved record's **Version Control URL**. |
| Check is red with `not_submitted` | Get the record approved (workflow → Approve). |
| Can't **submit** a Manage Change | The target app repo is missing the workflow files — copy them in and merge (Step 3), then re-submit. |
| Can't change Version Control URL | It's locked once a real URL is saved — raise a **new** Manage Change to gate a different PR. |
| Approver can't approve | Confirm they're an HOD of the chosen Department (so they're in the record's **Approver** table). |
| Need to re-run the check | Comment **`/recheck`** on the PR. |

---

See also: **[Manage Access →](MANAGE_ACCESS.md)** · **[Docs index →](README.md)** ·
condensed gate guide at [`.github/MANAGE_CHANGE_GATE.md`](../.github/MANAGE_CHANGE_GATE.md)
