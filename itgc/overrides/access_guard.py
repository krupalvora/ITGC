# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

"""Lockdown guards for the ITGC Manage Access governance.

When ITGC Settings -> `enable_manage_access` is ON, the Manage Access submit flow
is the ONLY sanctioned way to change access. These guards block every *human
frontend* write to the underlying masters (User roles / role profile, Role, Role
Profile, Custom DocPerm, User Permission) and to the Doctype Permissions page.

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
	"""Block edits/deletes for Role / Role Profile / Custom DocPerm.

	New Role creation is intentionally allowed — admins still create roles directly
	from the Role form; governance only covers modifications and deletions.
	"""
	if not _managed():
		return
	if doc.doctype == "Role" and doc.is_new():
		return
	_throw(doc.doctype)


def capture_user_access_state(doc, method=None):
	"""Stash the user-SUBMITTED roles / role profile before core rewrites them.

	Runs as the `User` `before_validate` hook -- i.e. BEFORE the controller's
	`validate()` calls `populate_role_profile_roles()` (which empties the roles table
	and refills it from the Role Profile) and before this app's re-assert hooks
	(`ensure_*_role`) add the Access Manager / Manage-Access-granted roles back.

	`block_user_role_change` compares *this* captured state -- exactly what the human
	sent -- against the DB. By the time that validate hook runs the live roles table
	no longer reflects the submission, so without this stash a role-profile user's
	granted/asserted roles (which the form resubmits unchanged) would read as a
	deletion and falsely block a plain password / API-key / profile-field edit.
	"""
	doc.flags._itgc_submitted_roles = {r.role for r in doc.get("roles")}
	doc.flags._itgc_submitted_profile = doc.role_profile_name


def block_user_role_change(doc, method=None):
	"""Block direct changes to a User's roles / role profile.

	Compares the user-SUBMITTED roles/profile (captured in `capture_user_access_state`
	on `before_validate`, before core's role-profile sync and this app's re-assert
	hooks mutate the live roles table) against the committed DB state. So non-role
	User edits (language, theme, password, API key, bare user creation) are
	unaffected -- the resubmitted-but-unchanged roles match the DB and pass through.
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
	# Prefer the submitted snapshot; fall back to the live table only if the
	# before_validate hook did not run (e.g. a direct unit-test call).
	submitted_roles = doc.flags.get("_itgc_submitted_roles")
	if submitted_roles is None:
		submitted_roles = {r.role for r in doc.get("roles")}
	if "_itgc_submitted_profile" in doc.flags:
		submitted_profile = doc.flags.get("_itgc_submitted_profile")
	else:
		submitted_profile = doc.role_profile_name

	if (submitted_profile or None) != (old_profile or None) or submitted_roles != old_roles:
		_throw(_("User roles / role profile"))


def block_user_trash(doc, method=None):
	"""Block deleting a User from the frontend (use Manage Access 'Disable User')."""
	if _managed():
		_throw(_("User"))


# Permission flags compared to detect a doctype-permission change. Mirrors the
# rights tracked by Frappe's Role Permission Manager plus the row's role/level.
_PERM_FIELDS = (
	"role", "permlevel", "if_owner",
	"select", "read", "write", "create", "delete", "submit", "cancel", "amend",
	"print", "email", "report", "import", "export", "share", "set_user_permissions",
)


def _perm_signature(rows):
	"""Order-independent signature of a permissions table for equality testing."""
	signature = []
	for row in rows:
		signature.append(
			tuple(
				(field, (row.get(field) or "") if field == "role" else int(row.get(field) or 0))
				for field in _PERM_FIELDS
			)
		)
	return sorted(signature)


def block_doctype_perm_change(doc, method=None):
	"""Block editing a doctype's permissions (DocPerm) via the DocType form.

	`block_doc` guards *Custom* DocPerm, but a custom doctype's standard DocPerm
	rows are editable straight from the DocType form (custom doctypes skip the
	developer-mode gate). That is a back door around Manage Access governance, so
	here we block any save that changes the permissions table while governed.

	Only the permissions table is compared, so legitimate structural edits to a
	custom doctype (fields, naming, etc.) are unaffected; doctype permissions may
	only change through the Manage Access 'Change Doctype Permission' flow (which
	writes Custom DocPerm with `in_manage_access` set and never touches DocPerm).
	"""
	if not _managed():
		return
	# Creating a doctype sets its initial permissions; that is doctype creation,
	# not a modification of existing permissions. Only guard edits to existing ones.
	if doc.is_new():
		return

	old_rows = frappe.get_all(
		"DocPerm",
		filters={"parent": doc.name, "parenttype": "DocType"},
		fields=list(_PERM_FIELDS),
	)
	new_rows = doc.get("permissions") or []
	if _perm_signature(old_rows) != _perm_signature(new_rows):
		_throw(_("Doctype permissions"))
