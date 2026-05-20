# Originally authored by Krupal Vora (2025).
# Migrated to the ITGC app.

import frappe
from frappe.core.page.permission_manager.permission_manager import (
	update as core_update,
	add as core_add,
	remove as core_remove,
	reset as core_reset,
	get_permissions as core_get_permissions,
)

from itgc.itgc.doctype.access_audit_log.access_audit_log import _log_role_permission_changes


@frappe.whitelist()
def update_permission_with_logging(doctype, role, permlevel, ptype, value=None, if_owner=0, request_id=None):
	"""Wrapper over Frappe's core permission update — diffs and logs the change."""

	old_perm = _get_permission_state(doctype, role, permlevel, if_owner)
	response = core_update(doctype, role, permlevel, ptype, value, if_owner)

	name = None
	val = 0 if value == "1" else 1
	if not old_perm:
		old_perm = core_get_permissions(doctype, role)[0]
		old_perm.update({ptype: val, "reference_doctype": old_perm.parent})

	name = old_perm.get("name")
	new_perm = _get_permission_state(doctype, role, permlevel, if_owner, name)

	if old_perm != new_perm:
		activity_type = f"Updated : For Role-{role} => permission-{ptype} is updated from {val} to {value}"
		_log_role_permission_changes(activity_type, [old_perm], [new_perm], request_id)

	return response


@frappe.whitelist()
def add_permission_with_logging(parent, role, permlevel):
	"""Add a new DocType permission and record the resulting values in the audit log."""

	response = core_add(parent, role, permlevel)
	new_perm = _get_permission_state(parent, role, permlevel)
	activity_type = f"Add : New Role- {role} is added"
	_log_role_permission_changes(new_updated_permission=[new_perm], activity_type=activity_type)
	return response


@frappe.whitelist()
def remove_permission_with_logging(doctype, role, permlevel, if_owner=0):
	"""Remove a permission rule and record the pre-deletion state to the audit log."""

	old_perm = _get_permission_state(doctype, role, permlevel, if_owner)
	response = core_remove(doctype, role, permlevel, if_owner)
	activity_type = f"Delete : Role- {role} is deleted"
	_log_role_permission_changes(old_permission=[old_perm], activity_type=activity_type)
	return response


@frappe.whitelist()
def reset_permission_with_logging(doctype):
	"""Reset all permissions for a DocType, logging both pre and post snapshots."""

	old_perm = core_get_permissions(doctype)
	response = core_reset(doctype)
	activity_type = "Reset : All role permission is reset and default permission is set"
	new_perm = core_get_permissions(doctype)
	_log_role_permission_changes(activity_type, old_perm, new_perm)
	return response


def _get_permission_state(doctype, role=None, permlevel=None, if_owner=0, name=None):
	"""Fetch current permission state for logging. Returns a dict or None."""
	fields = [
		"name",
		"parent as reference_doctype",
		"role",
		"if_owner",
		"permlevel",
		"select",
		"read",
		"write",
		"create",
		"delete as chk_delete",
		"submit",
		"cancel",
		"amend",
		"report",
		"export",
		"import",
		"set_user_permissions",
		"share",
		"print",
		"email",
	]

	if name:
		doc_perm_name = frappe.db.exists("Custom DocPerm", name)
		if not doc_perm_name:
			return {}
		filters = {"name": doc_perm_name}
	elif not role and not permlevel and not if_owner:
		filters = {"parent": doctype}
	else:
		filters = {
			"parent": doctype,
			"role": role,
			"permlevel": permlevel,
			"if_owner": if_owner,
		}

	perm = frappe.db.get_value(
		"Custom DocPerm",
		filters=filters,
		fieldname=fields,
		as_dict=True,
	)

	return perm if perm else None
