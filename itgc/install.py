# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import frappe

ACCESS_MANAGER_ROLE = "ITGC Access Manager"
MANAGE_ACCESS_DOCTYPE = "Manage Access"

# --- Manage Change governance ---------------------------------------------
MANAGE_CHANGE_DOCTYPE = "Manage Change"
# Holders may raise (create) a Manage Change, but never approve one.
MC_REQUESTER_ROLE = "Manage Change Requester"
# Carries the *capability* to act on the approval workflow. The per-document
# authority is still narrowed by the workflow condition to the users listed in
# that document's `approver` table (the department's HODs).
MC_APPROVER_ROLE = "Manage Change Approver"

# Frappe Workflow that drives the Manage Change approval. Created (disabled) on
# install and only activated when ITGC Settings -> "Enable Change Management" is on.
MC_WORKFLOW_NAME = "ITGC Manage Change Approval"

# Only the users present in the document's approver list may approve/reject. The
# workflow `allowed` role gates the capability; this condition gates the identity.
MC_APPROVER_CONDITION = "frappe.session.user in [d.user for d in doc.approver]"

# (state, doc_status, allow_edit_role)
MC_WORKFLOW_STATES = (
	("Pending", "0", MC_REQUESTER_ROLE),
	("Approved", "1", None),
	("Rejected", "0", MC_REQUESTER_ROLE),
)

# (from_state, action, to_state, allowed_role, allow_self_approval, condition)
MC_WORKFLOW_TRANSITIONS = (
	("Pending", "Approve", "Approved", MC_APPROVER_ROLE, 0, MC_APPROVER_CONDITION),
	("Pending", "Reject", "Rejected", MC_APPROVER_ROLE, 0, MC_APPROVER_CONDITION),
	# Let the requester re-open a rejected change and send it back for approval.
	("Rejected", "Resubmit", "Pending", MC_REQUESTER_ROLE, 1, None),
)

# Roles created when the ITGC app is installed.
# "ITGC Access Manager" is the access-granting role: its holders can grant/revoke
# access (roles, doctype/module permissions, user permissions) to other users.
ITGC_ROLES = [
	{
		"role_name": ACCESS_MANAGER_ROLE,
		"desk_access": 1,
	},
	{
		"role_name": MC_REQUESTER_ROLE,
		"desk_access": 1,
	},
	{
		"role_name": MC_APPROVER_ROLE,
		"desk_access": 1,
	},
]

# Operational rights the Access Manager gets on Manage Access (permlevel 0 only;
# the Change Doc Perm tab is permlevel 1 and stays restricted to System Manager).
ACCESS_MANAGER_RIGHTS = ("read", "write", "create", "submit", "cancel", "amend")

# Requesters raise changes; approvers act on the workflow (submit = approve,
# cancel = reject path). Neither gets the other's defining right.
MC_REQUESTER_RIGHTS = ("read", "write", "create", "amend")
MC_APPROVER_RIGHTS = ("read", "write", "submit", "cancel")


def after_install():
	"""Set up ITGC roles, permissions and workflows. Idempotent — safe to re-run."""
	create_itgc_roles()
	grant_manage_access_permissions()
	grant_manage_change_permissions()
	ensure_manage_change_workflow()


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


def grant_manage_change_permissions():
	"""Give the requester/approver roles their docperms on Manage Change.

	Done programmatically (not in the doctype JSON) so the roles — created by
	`create_itgc_roles` — are guaranteed to exist first, mirroring how Manage
	Access permissions are granted.
	"""
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists("DocType", MANAGE_CHANGE_DOCTYPE):
		return

	grants = (
		(MC_REQUESTER_ROLE, MC_REQUESTER_RIGHTS),
		(MC_APPROVER_ROLE, MC_APPROVER_RIGHTS),
	)
	for role, rights in grants:
		if not frappe.db.exists("Role", role):
			continue
		add_permission(MANAGE_CHANGE_DOCTYPE, role, 0)
		for ptype in rights:
			update_permission_property(MANAGE_CHANGE_DOCTYPE, role, 0, ptype, 1)
	frappe.db.commit()


def ensure_manage_change_workflow():
	"""Create the Manage Change approval workflow, disabled by default.

	The workflow ships with the app but stays inactive until an admin turns on
	ITGC Settings -> "Enable Change Management" (which flips `is_active`). Safe to
	re-run: it no-ops once the workflow exists.
	"""
	if not frappe.db.exists("DocType", MANAGE_CHANGE_DOCTYPE):
		return

	# The workflow's states/transitions link to these roles, so they must exist
	# first. Idempotent — covers running this function standalone (e.g. on a site
	# where the app was already installed) without first calling create_itgc_roles.
	create_itgc_roles()
	_ensure_workflow_masters()

	if frappe.db.exists("Workflow", MC_WORKFLOW_NAME):
		return

	wf = frappe.new_doc("Workflow")
	wf.workflow_name = MC_WORKFLOW_NAME
	wf.document_type = MANAGE_CHANGE_DOCTYPE
	wf.workflow_state_field = "workflow_state"
	wf.override_status = 1
	# Disabled on install — only ITGC Settings activates it.
	wf.is_active = 0

	for state, doc_status, allow_edit in MC_WORKFLOW_STATES:
		wf.append(
			"states",
			{
				"state": state,
				"doc_status": doc_status,
				# A pending change is editable by its requester; approved/rejected
				# changes lock down to System Manager.
				"allow_edit": allow_edit or "System Manager",
			},
		)

	for from_state, action, to_state, allowed, self_approval, condition in MC_WORKFLOW_TRANSITIONS:
		row = {
			"state": from_state,
			"action": action,
			"next_state": to_state,
			"allowed": allowed,
			"allow_self_approval": self_approval,
		}
		if condition:
			row["condition"] = condition
		wf.append("transitions", row)

	wf.insert(ignore_permissions=True)
	frappe.db.commit()


def _ensure_workflow_masters():
	"""Create the Workflow State / Action Master records the workflow links to."""
	states = {s[0] for s in MC_WORKFLOW_STATES}
	actions = {t[1] for t in MC_WORKFLOW_TRANSITIONS}

	for state in states:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert(
				ignore_permissions=True
			)
	for action in actions:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc(
				{"doctype": "Workflow Action Master", "workflow_action_name": action}
			).insert(ignore_permissions=True)
	frappe.db.commit()


def set_manage_change_workflow_active(is_active):
	"""Activate/deactivate the Manage Change workflow. Returns True if state changed.

	Called from ITGC Settings when "Enable Change Management" is toggled. Ensures
	the workflow exists first (covers sites installed before the workflow shipped).
	"""
	ensure_manage_change_workflow()
	if not frappe.db.exists("Workflow", MC_WORKFLOW_NAME):
		return False

	wf = frappe.get_doc("Workflow", MC_WORKFLOW_NAME)
	target = 1 if is_active else 0
	if wf.is_active == target:
		return False

	wf.is_active = target
	wf.save(ignore_permissions=True)
	return True
