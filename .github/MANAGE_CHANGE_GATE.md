# Manage Change Merge Gate — Setup

These two workflows block merges into the gated branches
until a matching **Manage Change** record is submitted (approved) in Frappe:

| Workflow | Purpose |
| --- | --- |
| [`manage-change-check.yml`](workflows/manage-change-check.yml) | On every PR to a gated branch, polls the ITGC endpoint and fails until the change is approved. |
| [`manage-change-recheck.yml`](workflows/manage-change-recheck.yml) | Lets a maintainer comment `/recheck` to re-poll without pushing a new commit. |

## Multiple environments (manage N)

Each environment runs its own ERP, and the gate is **fully config-driven**: which
branch is gated and which ERP it's checked against is set with repo settings, not
code. For a PR into branch `<b>`, the workflow derives an env key (uppercase the
branch, replace non-alphanumerics with `_`) and looks up:

| Setting | Type | Example (branch `prod`) |
| --- | --- | --- |
| `ITGC_BASE_URL_<ENV>` | repo **Variable** | `ITGC_BASE_URL_PROD` = `https://erp.example.com` |
| `ITGC_GATE_TOKEN_<ENV>` | repo **Secret** | `ITGC_GATE_TOKEN_PROD` = that ERP's gate token |

So a `staging` PR hits the staging ERP (`ITGC_BASE_URL_STAGING` / `ITGC_GATE_TOKEN_STAGING`),
a `prod` PR hits the prod ERP, and so on. (A generic `ITGC_BASE_URL` / `ITGC_GATE_TOKEN`
is used as a fallback if no env-specific setting exists — handy for a single-ERP setup.)

**To add the Nth environment** — the only YAML edit you ever make:
1. Add its branch under `on.pull_request.branches` in `manage-change-check.yml`
   (GitHub can't trigger on a dynamic branch list, so this list must stay in YAML).
2. Create repo Variable `ITGC_BASE_URL_<ENV>` and Secret `ITGC_GATE_TOKEN_<ENV>` for it.

No `case`/script changes, and `manage-change-recheck.yml` needs no edits at all
(it keys off whether a check run exists, not a branch list).

The check calls a Frappe endpoint that is **token-protected by default**
(`itgc.api.manage_change_gate.check_pr_approval`). You configure the **same
token** in two places — Frappe and GitHub — so only your CI can read approval
state.

---

## Tokens & secrets at a glance

| Name | Type | Where | How you get it |
| --- | --- | --- | --- |
| **Gate token** (per env) | shared secret | each env's ITGC Settings **and** GitHub secret `ITGC_GATE_TOKEN_<ENV>` (or generic `ITGC_GATE_TOKEN`) | You generate it (Step 1). |
| `ITGC_BASE_URL_<ENV>` (per env) | repo **variable** | GitHub → Settings → Variables | That environment's Frappe site URL, e.g. `https://erp.example.com` (generic `ITGC_BASE_URL` is a fallback) |
| `GITHUB_TOKEN` | auto | provided by Actions | Nothing to do — built in (used by `/recheck`). |

> There is **no token to "fetch" from a third party**. The gate token is a
> random secret *you* create; the two sides just have to match. `GITHUB_TOKEN`
> is injected by GitHub automatically, so the recheck workflow needs no PAT.

---

## Step 1 — Generate the gate token

Create a strong random secret (any of these works):

```bash
openssl rand -hex 32
# or
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output — you'll paste the **exact same value** into Steps 2 and 3.

## Step 2 — Set the token in Frappe

1. Open **ITGC Settings** (Awesomebar → "ITGC Settings").
2. Paste the value into **"Manage Change Status API Token"** and **Save**.

> The token is **mandatory** whenever Change Management is enabled — the status
> API is always token-protected and has no public mode. A call without a valid
> `X-ITGC-Token` header (or when no token is configured) is rejected with 401,
> which blocks the gated merge.

## Step 3 — Add the secret + variable in GitHub

In the repo: **Settings → Secrets and variables → Actions**

- **Secrets** tab → *New repository secret*
  - Name: `ITGC_GATE_TOKEN`
  - Value: the same string from Step 1
- **Variables** tab → *New repository variable*
  - Name: `ITGC_BASE_URL`
  - Value: your Frappe site URL (no trailing path), e.g. `https://erp.example.com`

That's it — `manage-change-check.yml` sends `ITGC_GATE_TOKEN` as the
`X-ITGC-Token` header and the endpoint accepts it.

## Step 4 — Make the check required (branch protection)

So PRs can't merge while the check is red:

**Settings → Branches → Add rule** for `staging` and `prod` →
*Require status checks to pass before merging* → select
**"Check Manage Change is approved"**.

---

## Rotating the token

1. Generate a new value (Step 1).
2. Update **both** the GitHub secret `ITGC_GATE_TOKEN` and the ITGC Settings
   token field (Steps 2–3). They must change together or the gate returns 401.

## Troubleshooting

| PR comment reason | Meaning | Fix |
| --- | --- | --- |
| `unauthorized` | Token missing/mismatched, or none configured. | Re-check Steps 2 & 3 match exactly. |
| `no_manage_change_record` | No submitted Manage Change for this PR URL + branch. | Set `version_control_url` on the approved Manage Change to the PR URL. |
| `not_submitted` | Record exists but isn't submitted (`docstatus != 1`). | Get it approved/submitted. |
| `missing_parameters` | Workflow didn't send `pr_url`/`target_branch`. | Check the workflow config / `ITGC_BASE_URL`. |
