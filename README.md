# ITGC

Information Technology General Controls — a Frappe app for access governance
(Manage Access) and change management (the Manage Change merge gate).

---test

## Manage Change merge gate — setup

These workflows block merges into the gated branches (`staging`, `prod`) until a
matching **Manage Change** record is submitted (approved) in Frappe:

| Workflow | Purpose |
| --- | --- |
| [`manage-change-check.yml`](.github/workflows/manage-change-check.yml) | On every PR to a gated branch, polls the ITGC endpoint and fails until the change is approved. |
| [`manage-change-recheck.yml`](.github/workflows/manage-change-recheck.yml) | Lets a maintainer comment `/recheck` to re-poll without pushing a new commit. |

The check calls a Frappe endpoint that is **token-protected by default**
(`itgc.api.manage_change_gate.check_pr_approval`). You configure the **same
gate token** in two places — Frappe and GitHub — so only your CI can read
approval state.

> **There is no token to fetch from a third party.** The gate token is a random
> secret *you* generate; the two sides just have to match. `GITHUB_TOKEN` (used
> by `/recheck`) is injected by Actions automatically, so no PAT is needed.

### Tokens & secrets at a glance

| Name | Type | Where | How you get it |
| --- | --- | --- | --- |
| **Gate token** | shared secret | ITGC Settings **and** GitHub secret `ITGC_GATE_TOKEN` | You generate it (Step 1). |
| `ITGC_BASE_URL` | repo **variable** | GitHub → Settings → Variables | Your Frappe site URL, e.g. `https://stagingerp.solarsquare.in` |
| `GITHUB_TOKEN` | auto | provided by Actions | Nothing to do — built in. |

### Step 1 — Generate the gate token

Create a strong random secret (either works):

```bash
openssl rand -hex 32
# or
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output — you'll paste the **exact same value** into Steps 2 and 3.

### Step 2 — Set the token in Frappe

1. Open **ITGC Settings** (Awesomebar → "ITGC Settings").
2. Leave **"Allow Public Manage Change Status API (no token)"** *unticked*
   (keeps the endpoint token-protected — the secure default).
3. Paste the value into **"Manage Change Status API Token"** and **Save**.

![ITGC Settings — Manage Change Approval API](.github/images/itgc-settings.png)

> Ticking *Allow Public…* removes the token requirement, but then anyone who can
> reach the URL can read approval state. Only do that for a fully private
> endpoint.

### Step 3 — Add the secret + variable in GitHub

Repo → **Settings → Secrets and variables → Actions**.

**Variables** tab → *New repository variable*
- Name: `ITGC_BASE_URL`
- Value: your Frappe site URL (no trailing path), e.g. `https://stagingerp.solarsquare.in`

![Repository variable ITGC_BASE_URL](.github/images/gh-variables.png)

**Secrets** tab → *New repository secret*
- Name: `ITGC_GATE_TOKEN`
- Value: the same string from Step 1

![Repository secret ITGC_GATE_TOKEN](.github/images/gh-secrets.png)

The check workflow sends `ITGC_GATE_TOKEN` as the `X-ITGC-Token` header and the
endpoint accepts it.

### Step 4 — Make the check required (branch protection)

So PRs can't merge while the check is red:

**Settings → Branches → Add rule** for `staging` and `prod` → *Require status
checks to pass before merging* → select **"Check Manage Change is approved"**.

![Branch protection — required status check](.github/images/branch-protection.png)

### Rotating the token

1. Generate a new value (Step 1).
2. Update **both** the GitHub secret `ITGC_GATE_TOKEN` and the ITGC Settings
   token field. They must change together or the gate returns `401`.

### Troubleshooting

| PR comment reason | Meaning | Fix |
| --- | --- | --- |
| `unauthorized` | Token missing/mismatched, or none configured. | Re-check Steps 2 & 3 match exactly. |
| `no_manage_change_record` | No submitted Manage Change for this PR URL + branch. | Set `version_control_url` on the approved Manage Change to the PR URL. |
| `not_submitted` | Record exists but isn't submitted (`docstatus != 1`). | Get it approved/submitted. |
| `missing_parameters` | Workflow didn't send `pr_url`/`target_branch`. | Check the workflow config / `ITGC_BASE_URL`. |

A condensed copy of this guide also lives at
[.github/MANAGE_CHANGE_GATE.md](.github/MANAGE_CHANGE_GATE.md).

---

#### License

mit
