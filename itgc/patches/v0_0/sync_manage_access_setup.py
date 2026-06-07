# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

"""Backfill the Manage Access / Manage Change setup on EXISTING sites.

`itgc.install.after_install` only runs once, when the app is first installed. A
site that already had ITGC installed picks up new code via `bench migrate`, which
does NOT re-run `after_install`. Without this patch such a site would, after an
upgrade:

  * have the Manage Access / Manage Change doctypes synced but NO docperms or
    approval workflows (the requester role can't raise a request, no workflow
    exists), and
  * if `enable_manage_access` was already on, keep the access-master lockdown
    active while the approval workflow stays inactive — freezing access changes
    until someone manually re-saves ITGC Settings.

This post-model-sync patch closes that gap. Every helper it calls is idempotent
(grants are skipped when present, workflows no-op once they exist, and the
active-state setters no-op when already in sync), so it is safe to re-run and is
a no-op on a fresh install where `after_install` already did the work.
"""

import frappe

from itgc.install import (
	MANAGE_ACCESS_DOCTYPE,
	MANAGE_CHANGE_DOCTYPE,
	ensure_manage_access_workflow,
	ensure_manage_change_workflow,
	grant_manage_access_permissions,
	grant_manage_change_permissions,
	set_manage_access_workflow_active,
	set_manage_change_workflow_active,
)


def execute():
	# 1. Backfill docperms + create the (disabled) workflows on existing sites.
	#    These helpers each guard on their doctype existing, so a partially set up
	#    site is handled safely.
	grant_manage_access_permissions()
	grant_manage_change_permissions()
	ensure_manage_access_workflow()
	ensure_manage_change_workflow()

	# 2. Reconcile each workflow's active state with the flag already stored in
	#    ITGC Settings, so a site that had the feature enabled gets its approval
	#    workflow activated automatically — no manual Settings save required.
	if not frappe.db.exists("DocType", "ITGC Settings"):
		return

	settings = frappe.get_single("ITGC Settings")

	if frappe.db.exists("DocType", MANAGE_ACCESS_DOCTYPE):
		set_manage_access_workflow_active(bool(settings.enable_manage_access))

	if frappe.db.exists("DocType", MANAGE_CHANGE_DOCTYPE):
		set_manage_change_workflow_active(bool(settings.enable_change_management))
