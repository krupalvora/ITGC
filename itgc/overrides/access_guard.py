# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

"""Lockdown guards for the ITGC Manage Access governance.

When ITGC Settings -> `enable_manage_access` is ON, the Manage Access submit flow
is the ONLY sanctioned way to change access. These guards block every *human
frontend* write to the underlying masters (User roles / role profile, Role, Role
Profile, Custom DocPerm) and to the Doctype Permissions page.

The guards intentionally do NOT fire for:
  - the Manage Access apply path (`frappe.flags.in_manage_access`),
  - ERPNext portal auto-role assignment (`frappe.flags.setting_role`),
  - install / migrate / patch / setup-wizard,
  - background jobs, schedulers and the server shell (`bench console`) -- no HTTP
    request -- which is the intended break-glass.
Data Import IS guarded (it is a frontend-initiated bulk write).
"""

import frappe
from frappe import _


def _managed():
	"""True when a human frontend write must be blocked under Manage Access governance."""
	# Our own sanctioned writer.
	if frappe.flags.get("in_manage_access"):
		return False
	# ERPNext portal Customer/Supplier role assignment on login.
	if frappe.flags.get("setting_role"):
		return False
	# System lifecycle flows write access masters legitimately.
	if (
		frappe.flags.in_install
		or frappe.flags.in_migrate
		or frappe.flags.get("in_patch")
		or frappe.flags.get("in_setup_wizard")
	):
		return False
	# Only guard real user-initiated frontend writes: HTTP requests + Data Import.
	# Background jobs (Role Profile -> user sync), schedulers and `bench console`
	# have no request and are the intentional break-glass path.
	if not (getattr(frappe, "request", None) or frappe.flags.in_import):
		return False
	return bool(frappe.db.get_single_value("ITGC Settings", "enable_manage_access"))


def _throw(label):
	frappe.throw(
		_(
			"Access is governed by Manage Access. Direct changes to {0} are disabled while "
			"ITGC Manage Access is enabled. Please raise a Manage Access request."
		).format(frappe.bold(label)),
		title=_("Blocked — ITGC Manage Access"),
	)


def block_doc(doc, method=None):
	"""Full block for Role / Role Profile / Custom DocPerm (validate + on_trash)."""
	if _managed():
		_throw(doc.doctype)


def block_user_role_change(doc, method=None):
	"""Block direct changes to a User's roles / role profile.

	Registered as the FIRST `User` validate hook so it sees the user-submitted state
	before this app's re-assert hooks (`ensure_*_role`) mutate the roles table. We
	compare against the committed DB state, so non-role User edits (language, theme,
	password, bare user creation) are unaffected.
	"""
	if not _managed():
		return
	# Public sign-up assigns the Portal Settings default role as Guest -- exempt.
	if frappe.session.user == "Guest":
		return

	is_new = doc.is_new()
	old_profile = None if is_new else frappe.db.get_value("User", doc.name, "role_profile_name")
	old_roles = (
		set()
		if is_new
		else {
			r.role
			for r in frappe.get_all(
				"Has Role",
				filters={"parent": doc.name, "parenttype": "User"},
				fields=["role"],
			)
		}
	)
	new_roles = {r.role for r in doc.get("roles")}

	if (doc.role_profile_name or None) != (old_profile or None) or new_roles != old_roles:
		_throw(_("User roles / role profile"))


def block_user_trash(doc, method=None):
	"""Block deleting a User from the frontend (use Manage Access 'Disable User')."""
	if _managed():
		_throw(_("User"))
