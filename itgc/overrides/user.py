# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import frappe

ACCESS_MANAGER_ROLE = "ITGC Access Manager"


def ensure_access_manager_role(doc, method=None):
	"""Re-assert the ITGC Access Manager role for the configured access manager.

	Runs as a `User` validate doc-event, i.e. AFTER Frappe core's
	`populate_role_profile_roles()` has reset the roles table to match the
	user's Role Profile. For role-profile users that sync wipes any ad-hoc
	role, so without this the access manager would silently lose the role on
	every save. Here we append it back when this user is the one selected in
	ITGC Settings, making the assignment self-healing.
	"""
	# During an ITGC Settings save the new value may not yet be readable here
	# (single-value cache), so the settings controller passes it explicitly via
	# this flag. For every other User save we read the committed value.
	access_manager = frappe.flags.get("itgc_access_manager", False)
	if access_manager is False:
		if not frappe.db.get_single_value("ITGC Settings", "enable_manage_access"):
			return
		access_manager = frappe.db.get_single_value("ITGC Settings", "access_manager")

	if not access_manager or doc.name != access_manager:
		return

	if ACCESS_MANAGER_ROLE not in {r.role for r in doc.get("roles")}:
		doc.append("roles", {"role": ACCESS_MANAGER_ROLE})
