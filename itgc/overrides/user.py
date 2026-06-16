# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import frappe

ACCESS_MANAGER_ROLE = "ITGC Access Manager"


def ensure_access_manager_role(doc, method=None):
	"""Re-assert the ITGC Access Manager role for the privileged users.

	The "privileged" users are the configured Access Manager and the Sudo User:
	both must hold the ITGC Access Manager role so they can act on the Manage
	Access approval workflow (the Access Manager approves normal requests; the
	Sudo User approves protected-role grants).

	Runs as a `User` validate doc-event, i.e. AFTER Frappe core's
	`populate_role_profile_roles()` has reset the roles table to match the user's
	Role Profile. For role-profile users that sync wipes any ad-hoc role, so
	without this they would silently lose the role on every save. Here we append it
	back, making the assignment self-healing.
	"""
	# During an ITGC Settings save the new value may not yet be readable here
	# (single-value cache), so the settings controller passes the user explicitly
	# via this flag. For every other User save we read the committed values.
	privileged = frappe.flags.get("itgc_access_manager", False)
	if privileged is False:
		if not frappe.db.get_single_value("ITGC Settings", "enable_manage_access"):
			return
		privileged = {
			frappe.db.get_single_value("ITGC Settings", "access_manager"),
			frappe.db.get_single_value("ITGC Settings", "sudo_user"),
		}
	else:
		privileged = {privileged}

	if not doc.name or doc.name not in privileged:
		return

	if ACCESS_MANAGER_ROLE not in {r.role for r in doc.get("roles")}:
		doc.append("roles", {"role": ACCESS_MANAGER_ROLE})


def ensure_granted_roles(doc, method=None):
	"""Authoritatively apply role grants/revokes from submitted Manage Access records.

	Runs after core's role-profile sync (which strips ad-hoc roles for
	role-profile users), so it both:
	  - re-asserts roles granted via Manage Access ("Request Role" / "New User"),
	    making them persist and self-heal across any future User save, and
	  - removes roles whose latest Manage Access action is a "Revoke Role".

	Roles supplied by the user's Role Profile are left untouched — to remove
	those, revoke the Role Profile itself.
	"""
	granted, revoked = get_active_role_changes(doc.name)
	if not granted and not revoked:
		return

	current = {r.role for r in doc.get("roles")}
	for role in granted - current:
		doc.append("roles", {"role": role})

	to_remove = revoked - get_profile_roles(doc.role_profile_name)
	if to_remove:
		doc.set("roles", [r for r in doc.get("roles") if r.role not in to_remove])


def get_active_role_changes(user):
	"""Resolve net role grants/revokes for `user` from Manage Access records.

	Latest submitted action per role wins, so grant -> revoke -> grant resolves
	correctly. Returns (granted_roles, revoked_roles) as disjoint sets.
	"""
	if not user:
		return set(), set()

	# All Manage Access actions are admin-on-behalf: the subject is request_for.
	rows = frappe.get_all(
		"Manage Access",
		filters={
			"docstatus": 1,
			"request_for": user,
			"request_type": ["in", ["Request Role", "New User", "Revoke Role"]],
			"role": ["is", "set"],
		},
		fields=["role", "request_type"],
		order_by="creation asc",
	)
	state = {}  # role -> is_granted (later rows overwrite earlier ones)
	for r in rows:
		state[r.role] = r.request_type != "Revoke Role"

	granted = {role for role, is_granted in state.items() if is_granted}
	revoked = {role for role, is_granted in state.items() if not is_granted}
	return granted, revoked


def get_profile_roles(role_profile_name):
	"""Roles supplied by a Role Profile (these are owned by core, not Manage Access)."""
	if not role_profile_name or not frappe.db.exists("Role Profile", role_profile_name):
		return set()
	return {r.role for r in frappe.get_doc("Role Profile", role_profile_name).get("roles")}
