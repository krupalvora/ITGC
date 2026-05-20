"""Apply an approved Access Request.

The orchestrator dispatches each populated change-type to a separate processor and
records the outcome on the request. Idempotent: callers must guard against re-entry
(see AccessRequest.on_update which checks `applied_at`).
"""

import frappe
from frappe.utils import now

from itgc.api.permission_manager import (
	add_permission_with_logging,
	update_permission_with_logging,
)
from itgc.itgc.doctype.access_audit_log.access_audit_log import (
	create_access_audit_log,
	create_access_audit_log_user_permission,
	create_role_profile_audit_log,
)


_DOCPERM_FIELDS = (
	"select", "create", "chk_cancel", "email", "export", "read",
	"chk_delete", "chk_amend", "share", "report", "write",
	"chk_submit", "print", "import",
)


def apply_request(request):
	"""Execute every populated change-section on the request.

	Sets `status` to `Applied` if all sections succeed, `Failed` (with details in
	`decision_remarks`) otherwise. Caller decides when to call this — usually
	`AccessRequest.on_update` when status hits Approved.
	"""
	is_removal = request.request_type == "Remove Access"
	errors: list[tuple[str, str]] = []

	steps = [
		("role_profile", _apply_role_profile, [request]),
		("roles", _apply_roles, [request, is_removal]),
		("modules", _apply_modules, [request, is_removal]),
		("docperm_changes", _apply_docperm_changes, [request, is_removal]),
		("user_permissions", _apply_user_permissions, [request, is_removal]),
	]

	for step_name, fn, args in steps:
		if not _is_populated(request, step_name):
			continue
		try:
			fn(*args)
		except Exception as e:
			errors.append((step_name, f"{type(e).__name__}: {e}"))
			frappe.log_error(
				title=f"Access Request apply failed ({step_name})",
				message=frappe.get_traceback(),
			)

	if errors:
		summary = "; ".join(f"{step}: {err}" for step, err in errors)
		existing = request.decision_remarks or ""
		request.db_set(
			{
				"status": "Failed",
				"decision_remarks": (existing + f"\nApply errors: {summary}").strip(),
			},
			update_modified=False,
		)
	else:
		request.db_set(
			{"status": "Applied", "applied_at": now()},
			update_modified=False,
		)


def _is_populated(request, step_name) -> bool:
	return bool(
		{
			"role_profile": request.role_profile,
			"roles": request.requested_roles,
			"modules": request.requested_modules,
			"docperm_changes": request.docperm_changes,
			"user_permissions": request.user_permissions,
		}[step_name]
	)


def _apply_role_profile(request):
	user_doc = frappe.get_doc("User", request.target_user)
	user_doc.role_profile_name = request.role_profile
	if request.request_type == "New User":
		user_doc.custom_reporting_manager = frappe.session.user
	user_doc.flags.from_access_request = True
	user_doc.save(ignore_permissions=True)
	create_role_profile_audit_log(request)


def _apply_roles(request, is_removal):
	requested = {row.reference_doctype for row in request.requested_roles if row.reference_doctype}
	if not requested:
		return

	user_doc = frappe.get_doc("User", request.target_user)
	if not user_doc.enabled or user_doc.user_type == "Website User":
		raise frappe.ValidationError(
			f"Role changes are not allowed for {user_doc.name} (disabled or Website User)."
		)

	current = {row.role for row in user_doc.roles}
	added_or_removed: list[str] = []

	if is_removal:
		to_remove = requested & current
		user_doc.roles = [r for r in user_doc.roles if r.role not in to_remove]
		added_or_removed = sorted(to_remove)
	else:
		to_add = requested - current
		for role in to_add:
			user_doc.append("roles", {"role": role})
		added_or_removed = sorted(to_add)

	user_doc.flags.from_access_request = True
	user_doc.save(ignore_permissions=True)

	create_access_audit_log(
		old_roles=list(current),
		cur_roles=added_or_removed,
		req_id=request.name,
		user_id=request.target_user,
	)


def _apply_modules(request, is_removal):
	"""Modify target_user's block_modules table.

	Semantics: 'Additional Access' BLOCKS the listed modules; 'Remove Access'
	UNBLOCKS them. Mirrors how block_modules represents *restrictions*.
	"""
	requested = {row.reference_module for row in request.requested_modules if row.reference_module}
	if not requested:
		return

	user_doc = frappe.get_doc("User", request.target_user)
	current_blocked = {b.module for b in (user_doc.block_modules or [])}

	if is_removal:
		user_doc.block_modules = [
			b for b in (user_doc.block_modules or []) if b.module not in requested
		]
	else:
		for module in requested - current_blocked:
			user_doc.append("block_modules", {"module": module})

	user_doc.flags.from_access_request = True
	user_doc.save(ignore_permissions=True)


def _apply_docperm_changes(request, is_removal):
	for row in request.docperm_changes:
		reference_doctype = row.reference_doctype
		role = row.role

		exists = frappe.db.get_value(
			"Custom DocPerm",
			{
				"parent": reference_doctype,
				"role": role,
				"permlevel": 0,
				"if_owner": 0,
			},
		)

		for field in _DOCPERM_FIELDS:
			if not row.get(field):
				continue
			if not exists and not is_removal:
				add_permission_with_logging(reference_doctype, role, 0)
				exists = True
			value = 0 if is_removal else 1
			update_permission_with_logging(
				reference_doctype, role, 0, field, value, request_id=request.name,
			)


def _apply_user_permissions(request, is_removal):
	for row in request.user_permissions:
		spec = {
			"allow": row.allow,
			"for_value": row.for_value,
			"user": row.user,
			"is_default": row.is_default,
			"apply_to_all_doctypes": row.apply_to_all_doctypes,
			"applicable_for": row.applicable_for,
			"hide_descendants": row.hide_descendants,
		}

		if is_removal:
			match = frappe.db.get_value("User Permission", spec, "name")
			if not match:
				continue
			doc = frappe.get_doc("User Permission", match)
			doc.flags.from_access_request = True
			doc.delete(ignore_permissions=True)
			activity_type = "Deleted User Permission"
		else:
			if frappe.db.exists("User Permission", spec):
				raise frappe.ValidationError(f"User Permission already exists: {spec}")
			doc = frappe.new_doc("User Permission")
			doc.update(spec)
			doc.flags.from_access_request = True
			doc.save(ignore_permissions=True)
			activity_type = "Created User Permission"

		create_access_audit_log_user_permission(doc, request.name, activity_type)
