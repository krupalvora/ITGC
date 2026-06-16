# Documentation screenshots

Drop the PNGs listed below into this folder. Each is referenced from the docs with
a `<!-- IMAGE: ... -->` note describing exactly what to capture, so the filenames
here must match.

## Index / overview
| File | What to capture |
| --- | --- |
| `itgc-settings-overview.png` | ITGC Settings form showing both tabs (Manage Access / Manage Change). |

## Manage Access ([MANAGE_ACCESS.md](../MANAGE_ACCESS.md))
| File | What to capture |
| --- | --- |
| `ma-lockdown-blocked.png` | The "Blocked — ITGC Manage Access" error when editing a User's roles directly with the feature on. |
| `ma-department.png` | A Manage Access Department record with a name and 1–2 Access Managers. |
| `ma-settings.png` | ITGC Settings → Manage Access tab (before enabling): Access Manager, Sudo User, both protected-role tables filled. |
| `ma-enable-toggle.png` | Close-up of the "Enable Manage Access" checkbox ticked, with the inline note. |
| `ma-request-types.png` | The Manage Access form's Request Type dropdown expanded. |
| `ma-workflow-actions.png` | A pending request showing the Approve / Reject buttons. |
| `ma-example-request.png` | Priya's "Request Role" record — Pending, Approvers = Rahul. |
| `ma-example-approve.png` | Rahul's view of the same record with Approve highlighted. |
| `ma-example-applied.png` | Role granted after approval (User record or Approved Manage Access record). |

## Manage Change ([MANAGE_CHANGE.md](../MANAGE_CHANGE.md))
| File | What to capture |
| --- | --- |
| `mc-pr-check-failing.png` | GitHub PR with the "Check Manage Change is approved" check RED (merge blocked). |
| `mc-vc-branch.png` | A Manage Change VC Branch record (e.g. named `prod`). |
| `mc-department.png` | A Manage Change Department with Department Name + HOD user(s). |
| `mc-settings.png` | ITGC Settings → Manage Change tab: Enable ticked, token filled, notifications ticked. |
| `mc-workflow-actions.png` | A Pending Manage Change with Approve / Reject buttons. |
| `mc-example-record.png` | Aman's Manage Change — Pending, Approver = Neha. |
| `mc-example-prurl.png` | The Version Control URL field filled with the PR link. |
| `mc-example-approved.png` | The record after approval — state Approved. |
| `mc-pr-check-passing.png` | GitHub PR with the check GREEN (merge allowed). |
| `gh-variables.png` | GitHub Settings → Secrets and variables → Actions → Variables (`ITGC_BASE_URL`). |
| `gh-secrets.png` | GitHub Secrets tab (`ITGC_GATE_TOKEN`). |
| `branch-protection.png` | GitHub branch protection rule with the required status check selected. |

> Note: `gh-variables.png`, `gh-secrets.png`, `branch-protection.png` and
> `itgc-settings.png` are also referenced by the app's top-level `README.md` /
> `.github/MANAGE_CHANGE_GATE.md`, which keep their own copies under
> `.github/images/`. You can reuse the same screenshots.
