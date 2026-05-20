# Originally authored by Krupal Vora (2025).
# Migrated to the ITGC app.
#
# Audit log entries record what changed and who triggered it. They do NOT modify the
# source Access Request — status transitions are owned by the apply orchestrator
# (itgc.itgc.doctype.access_request.apply).

import frappe
from frappe.model.document import Document


class AccessAuditLog(Document):
	pass


def _audit_doc(request_doc, activity_type, *, reference_doctype=None):
	"""Build a base Access Audit Log doc populated from the parent request."""
	log = frappe.new_doc("Access Audit Log")
	if request_doc:
		log.target_user = getattr(request_doc, "target_user", None)
		log.approver = getattr(request_doc, "approver", None)
		log.request_id = request_doc.name
	if reference_doctype:
		log.reference_doctype = reference_doctype
	log.activity_type = activity_type
	log.updated_by = frappe.session.user
	return log


@frappe.whitelist()
def create_access_audit_log(old_roles, cur_roles, req_id, user_id):
	"""Record a role-assignment change for `req_id`."""
	old_roles = ",".join(frappe.parse_json(old_roles) or [])
	cur_roles = ",".join(frappe.parse_json(cur_roles) or [])

	request_doc = frappe.get_doc("Access Request", req_id)
	log = _audit_doc(request_doc, activity_type="User Role is updated")
	log.previous_roles = old_roles
	log.new_roles = cur_roles
	log.save(ignore_permissions=True)


def _log_role_permission_changes(activity_type, old_permission=None, new_updated_permission=None, request_id=None):
	"""Record a Custom DocPerm change (called from the permission_manager wrapper)."""
	request_doc = frappe.get_doc("Access Request", request_id) if request_id else None
	log = _audit_doc(request_doc, activity_type, reference_doctype="Role Permission Manager")

	if old_permission:
		for row in old_permission:
			if "parent" in row:
				row.update({"reference_doctype": row.parent})
			log.append("old_role_permission", row)

	if new_updated_permission:
		for row in new_updated_permission:
			if "parent" in row:
				row.update({"reference_doctype": row.parent})
			log.append("new_role_permission", row)

	log.save(ignore_permissions=True)


@frappe.whitelist()
def create_access_audit_log_user_permission(doc, req_id, activity_type):
	"""Record a User Permission create/update/delete for `req_id`."""
	if isinstance(doc, str):
		doc = frappe._dict(frappe.parse_json(doc))

	previous_doc_value = None
	if doc.get("name") and frappe.db.exists(doc.doctype, doc.name):
		previous_doc_value = frappe.get_doc(doc.doctype, doc.name)
		if activity_type == "Created User Permission":
			activity_type = "User Permission value updated"

	request_doc = frappe.get_doc("Access Request", req_id)
	log = _audit_doc(request_doc, activity_type, reference_doctype="User Permission")

	if previous_doc_value:
		log.previous_roles = _format_user_permission(previous_doc_value)
	log.new_roles = _format_user_permission(doc)
	log.save(ignore_permissions=True)


def create_role_profile_audit_log(request_doc):
	"""Record that a Role Profile was assigned via `request_doc`."""
	log = _audit_doc(request_doc, activity_type="User Role-Profile is set")
	log.save(ignore_permissions=True)


def _format_user_permission(obj) -> str:
	return (
		f"User: {obj.get('user') or ''}\n"
		f"Allow: {obj.get('allow') or ''}\n"
		f"For Value: {obj.get('for_value') or ''}\n"
		f"Is Default: {obj.get('is_default') or ''}\n"
		f"Apply to all Doctypes: {obj.get('apply_to_all_doctypes') or ''}\n"
		f"Hide Descendants: {obj.get('hide_descendants') or ''}"
	)
