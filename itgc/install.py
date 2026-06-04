# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import frappe

ACCESS_MANAGER_ROLE = "ITGC Access Manager"
MANAGE_ACCESS_DOCTYPE = "Manage Access"

# Roles created when the ITGC app is installed.
# "ITGC Access Manager" is the access-granting role: its holders can grant/revoke
# access (roles, doctype/module permissions, user permissions) to other users.
ITGC_ROLES = [
	{
		"role_name": ACCESS_MANAGER_ROLE,
		"desk_access": 1,
	},
]

# Operational rights the Access Manager gets on Manage Access (permlevel 0 only;
# the Change Doc Perm tab is permlevel 1 and stays restricted to System Manager).
ACCESS_MANAGER_RIGHTS = ("read", "write", "create", "submit", "cancel", "amend")


def after_install():
	"""Set up ITGC roles and permissions. Idempotent — safe to re-run."""
	create_itgc_roles()
	grant_manage_access_permissions()


def create_itgc_roles():
	for role in ITGC_ROLES:
		if frappe.db.exists("Role", role["role_name"]):
			continue
		doc = frappe.new_doc("Role")
		doc.update(role)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()


def grant_manage_access_permissions():
	"""Let the ITGC Access Manager operate the Manage Access doctype.

	Once the Manage Access feature is in place, holders of the access-granting
	role need to use it. We grant permlevel-0 operational rights only, so the
	System-Manager-only Change Doc Perm tab (permlevel 1) remains hidden.
	"""
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists("DocType", MANAGE_ACCESS_DOCTYPE):
		return
	if not frappe.db.exists("Role", ACCESS_MANAGER_ROLE):
		return

	add_permission(MANAGE_ACCESS_DOCTYPE, ACCESS_MANAGER_ROLE, 0)
	for ptype in ACCESS_MANAGER_RIGHTS:
		update_permission_property(MANAGE_ACCESS_DOCTYPE, ACCESS_MANAGER_ROLE, 0, ptype, 1)
	frappe.db.commit()
