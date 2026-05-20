"""Install-time bootstrap for the ITGC app.

Creates the `Access Request Approver` role, grants it to Administrator, and points the
Access Request Workflow's approval transitions at that role. Safe to re-run.
"""

import frappe


APPROVER_ROLE = "Access Request Approver"
WORKFLOW_NAME = "Access Request Workflow"
APPROVAL_ACTIONS = ("Approve", "Reject")


def after_install():
	_ensure_role()
	_grant_to_administrator()
	_attach_role_to_workflow()


def _ensure_role():
	if frappe.db.exists("Role", APPROVER_ROLE):
		return
	doc = frappe.new_doc("Role")
	doc.role_name = APPROVER_ROLE
	doc.desk_access = 1
	doc.disabled = 0
	doc.insert(ignore_permissions=True)


def _grant_to_administrator():
	admin = frappe.get_doc("User", "Administrator")
	if APPROVER_ROLE in {r.role for r in admin.roles}:
		return
	admin.append("roles", {"role": APPROVER_ROLE})
	admin.flags.from_access_request = True
	admin.save(ignore_permissions=True)


def _attach_role_to_workflow():
	"""Point the Approve/Reject transitions at our role.

	The Workflow record may have been created with a different `allowed` role
	(e.g. System Manager) on first install; this re-syncs it idempotently.
	"""
	if not frappe.db.exists("Workflow", WORKFLOW_NAME):
		return
	wf = frappe.get_doc("Workflow", WORKFLOW_NAME)
	changed = False
	for transition in wf.transitions:
		if transition.action in APPROVAL_ACTIONS and transition.allowed != APPROVER_ROLE:
			transition.allowed = APPROVER_ROLE
			changed = True
	if changed:
		wf.save(ignore_permissions=True)
