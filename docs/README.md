# ITGC — User & Setup Documentation

**ITGC (Information Technology General Controls)** is a Frappe app that adds two
independent governance features on top of an ERPNext/Frappe site:

| Feature | What it governs | One-line summary |
| --- | --- | --- |
| **[Manage Access](MANAGE_ACCESS.md)** | *Who* can do *what* inside the ERP | A maker-checker approval flow for every access change (roles, role profiles, doctype permissions, user permissions) — plus a lockdown that disables direct edits to the underlying access masters. |
| **[Manage Change](MANAGE_CHANGE.md)** | *Code* going into the ERP | An approval record for every code change + a GitHub Actions **merge gate** that blocks a PR from merging into a protected branch (`staging`, `prod`, …) until its Manage Change is approved. |

Both features are **off by default** and are switched on independently from a
single control panel: **ITGC Settings**.

---

## The control panel — ITGC Settings

Everything is configured from one Single doctype. Open it from the Awesomebar:

> Awesomebar → type **"ITGC Settings"** → Enter

It has two tabs, one per feature:

- **Manage Access** tab → `Enable Manage Access` + access-governance config
- **Manage Change** tab → `Enable Change Management` + the merge-gate API token

<!-- IMAGE: itgc-settings-overview.png
     Screenshot of the ITGC Settings form showing both tabs (Manage Access / Manage Change). -->
![ITGC Settings — both tabs](images/itgc-settings-overview.png)

---

## Quick start

1. Install the app on your site (see below).
2. Decide which feature you want and read its dedicated guide:
   - **[Manage Access setup →](MANAGE_ACCESS.md)**
   - **[Manage Change setup →](MANAGE_CHANGE.md)**
3. Each guide walks you through the ITGC Settings switches, the supporting master
   data (departments, approvers, branches), and a fully worked example.

---

## Installation

```bash
# From the bench directory
bench get-app itgc <repo-url>
bench --site <your-site> install-app itgc
bench --site <your-site> migrate
```

On install the app automatically (idempotent — safe to re-run):

- creates the governance **roles** — `ITGC Access Manager`, `Manage Change
  Requester`, `Manage Change Approver`;
- grants those roles the right permissions on the Manage Access / Manage Change
  doctypes;
- creates both approval **workflows** in a **disabled** state (they only turn on
  when you flip the matching switch in ITGC Settings);
- **seeds the protected-role lists** — `System Manager` as *Fully Restricted* and
  `ITGC Access Manager` as *Approval-Gated* (you can customise these later).

> Nothing changes the behaviour of your site until you tick a switch in ITGC
> Settings. Installing the app is safe and inert on its own.

---

## How the pieces fit together

```
                         ┌─────────────────────┐
                         │    ITGC Settings     │   (single control panel)
                         ├──────────┬──────────┤
              ┌──────────┤ Manage   │ Manage   ├──────────┐
              │          │ Access   │ Change   │          │
              ▼          └──────────┴──────────┘          ▼
   ┌──────────────────────┐               ┌──────────────────────────┐
   │  Manage Access flow   │               │   Manage Change flow      │
   │  • approval workflow  │               │  • approval workflow      │
   │  • access lockdown    │               │  • GitHub merge gate API  │
   └──────────────────────┘               └──────────────────────────┘
```

The two features share nothing except the settings page — you can run either one
on its own, or both together.

---

## Images

All screenshots referenced by these docs live in [`images/`](images/). Each
image is referenced with a `<!-- IMAGE: ... -->` note describing exactly what the
screenshot should show, so you can drop the files in without guessing. See
[`images/README.md`](images/README.md) for the full list.
