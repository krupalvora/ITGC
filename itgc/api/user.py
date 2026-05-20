# Originally authored by Krupal Vora (2025).
# Migrated to the ITGC app.

import frappe

from itgc.itgc.doctype.itgc_settings.itgc_settings import is_enforcement_enabled


GUARDED_USER_FIELDS = ("role_profile_name", "module_profile")

# Roles allowed without a role_profile (e.g., default roles that Frappe assigns to
# every user regardless of profile). Anything else requires a profile when the
# role-profile-only rule is active.
_BASELINE_ROLES = {"All", "Guest", "Desk User"}


def validate(doc, method):
	"""Guard role/permission-impacting fields on User."""
	if not is_enforcement_enabled():
		return

	# Rule 1: roles can only come from a Role Profile. This rule applies even to
	# Access Request-driven changes — role assignment goes through `role_profile`,
	# never `roles` directly.
	_enforce_role_profile_only(doc)

	# Rule 2: direct edits to role/permission fields require an Access Request.
	# Bypassed when the change originates from an approved AR or the doc is brand-new.
	if doc.flags.get("from_access_request"):
		return
	if doc.is_new():
		return

	changes = []

	db_state = frappe.db.get_value(
		"User", doc.name, list(GUARDED_USER_FIELDS), as_dict=True
	) or {}
	for field in GUARDED_USER_FIELDS:
		old_val = db_state.get(field) or None
		new_val = doc.get(field) or None
		if old_val != new_val:
			changes.append(f"{field} ({old_val!r} -> {new_val!r})")

	# Frappe core User.validate runs before doc_events and re-populates roles from
	# role_profile_name. A diff here reflects a real user-driven mutation, not
	# profile restoration.
	db_roles = set(
		frappe.db.get_all(
			"Has Role",
			filters={"parent": doc.name, "parenttype": "User"},
			pluck="role",
		)
	)
	doc_roles = {r.role for r in (doc.roles or [])}
	if db_roles != doc_roles:
		added = sorted(doc_roles - db_roles)
		removed = sorted(db_roles - doc_roles)
		bits = []
		if added:
			bits.append(f"add {added}")
		if removed:
			bits.append(f"remove {removed}")
		changes.append("roles (" + ", ".join(bits) + ")")

	db_blocked = set(
		frappe.db.get_all(
			"Block Module",
			filters={"parent": doc.name, "parenttype": "User"},
			pluck="module",
		)
	)
	doc_blocked = {b.module for b in (doc.block_modules or [])}
	if db_blocked != doc_blocked:
		changes.append("block_modules")

	if changes:
		frappe.throw(
			"Direct edits to role/permission fields are blocked by ITGC enforcement. "
			"Raise an Access Request for: " + ", ".join(changes),
			title="Access Request Required",
		)


def _enforce_role_profile_only(doc):
	"""Roles must be sourced from a Role Profile, not assigned directly."""
	doc_roles = {r.role for r in (doc.roles or [])}
	non_baseline_roles = doc_roles - _BASELINE_ROLES
	if not non_baseline_roles:
		return  # No managed roles assigned — nothing to enforce.

	if not doc.get("role_profile_name"):
		frappe.throw(
			(
				"Direct role assignment is not allowed under ITGC enforcement. "
				f"User {doc.name or '(new)'} has roles {sorted(non_baseline_roles)!r} "
				"but no Role Profile set. Assign a Role Profile that contains the "
				"required roles, or clear the roles entirely."
			),
			title="Role Profile Required",
		)


@frappe.whitelist()
def get_guest_user_list(doctype, txt, searchfield, start, page_len, filters):
	"""Search query for Access Request: list of Website Users (excluding Guest)."""
	filters = {"user_type": "Website User", "name": ["!=", "Guest"]}
	if txt:
		filters["name"] = ["like", f"%{txt}%"]

	users = frappe.db.get_all(
		"User",
		filters=filters,
		fields=["name", "full_name"],
		limit_start=start,
		limit_page_length=page_len,
	)
	return [(u.name, u.full_name) for u in users]
