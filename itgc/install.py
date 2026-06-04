# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import frappe

# Roles created when the ITGC app is installed.
# "ITGC Access Manager" is the access-granting role: its holders can grant/revoke
# access (roles, doctype/module permissions, user permissions) to other users.
ITGC_ROLES = [
	{
		"role_name": "ITGC Access Manager",
		"desk_access": 1,
	},
]


def after_install():
	"""Create ITGC roles. Idempotent — safe to re-run."""
	create_itgc_roles()


def create_itgc_roles():
	for role in ITGC_ROLES:
		if frappe.db.exists("Role", role["role_name"]):
			continue
		doc = frappe.new_doc("Role")
		doc.update(role)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
