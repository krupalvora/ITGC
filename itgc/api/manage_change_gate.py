# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import hmac

import frappe
from frappe.utils import get_fullname
from frappe.utils.password import get_decrypted_password


def _resolve_approver(mc_name):
	"""Who actually approved `mc_name`, from the workflow action history.

	Approval happens via the workflow "Approve" transition; Frappe records the
	acting user on the corresponding Workflow Action (`completed_by`) and marks it
	Completed. The latest completed action is therefore the approval, and its
	`completed_by` is the approver — the same identity the on_submit notification
	addresses. Returns (user_id, acted_on) or (None, None) when no completed action
	is on record (e.g. history pruned, or approved before workflow actions existed).
	"""
	rows = frappe.get_all(
		"Workflow Action",
		filters={
			"reference_doctype": "Manage Change",
			"reference_name": mc_name,
			"status": "Completed",
			"completed_by": ["is", "set"],
		},
		fields=["completed_by", "modified"],
		order_by="modified desc",
		limit=1,
		ignore_permissions=True,
	)
	if rows:
		return rows[0].completed_by, rows[0].modified
	return None, None


def _named(user):
	"""(user_id, full_name) for display, tolerating a missing/empty user."""
	if not user:
		return None, None
	return user, (get_fullname(user) or user)


def _is_authorized():
	"""Token check for the merge gate. Fail-closed — a valid token is mandatory.

	The caller must send the configured token in the `X-ITGC-Token` header, and it
	must match the token stored in ITGC Settings. There is no public/unauthenticated
	mode: if no token is configured, or the header is missing or wrong, the call is
	denied, so a misconfigured site never silently exposes approval state.
	"""
	expected = get_decrypted_password(
		"ITGC Settings",
		"ITGC Settings",
		fieldname="manage_change_status_endpoint_token",
		raise_exception=False,
	)
	provided = frappe.get_request_header("X-ITGC-Token")
	# Constant-time compare; both operands must be non-empty strings.
	if not expected or not provided:
		return False
	return hmac.compare_digest(str(provided), str(expected))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def check_pr_approval(pr_url=None, target_branch=None):
	"""Return approval state for a PR. Consumed by the GitHub Actions merge gate.

	A PR is considered approved when a Manage Change record exists with
	`version_control_url == pr_url`, `branch == target_branch`, and `docstatus == 1`.

	The endpoint is `allow_guest` because CI calls it without a Frappe session, but
	it is token-protected by default and fail-closed (see `_is_authorized`) — only a
	caller holding the gate token can read it. On a *matched* record it therefore
	returns the governance context the gated PR comment needs (who raised it, who
	approved it, change type / department / ticket); the pre-match guard responses
	(unknown branch / no record) stay minimal as they carry no record identity.
	"""

	try:
		if not _is_authorized():
			frappe.local.response["http_status_code"] = 401
			return {"approved": False, "reason": "unauthorized"}

		if not pr_url or not target_branch:
			frappe.local.response["http_status_code"] = 400
			return {"approved": False, "reason": "missing_parameters"}

		# Guard 1 — unknown branch. The gate matches MC.branch (a Link to "Manage
		# Change VC Branch") against the git base ref by an EXACT string compare, so
		# a branch this ERP doesn't know about can never match. Surface that as its
		# own reason instead of a misleading "no record": it almost always means the
		# PR was routed to the wrong environment's ERP, or the branch hasn't been
		# registered here yet (and so no Manage Change could ever be raised for it).
		if not frappe.db.exists("Manage Change VC Branch", target_branch):
			return {
				"approved": False,
				"reason": "unknown_branch",
				"pr_url": pr_url,
				"target_branch": target_branch,
			}

		has_workflow_state = frappe.get_meta("Manage Change").has_field("workflow_state")
		fields = ["name", "docstatus"]
		if has_workflow_state:
			fields.append("workflow_state")

		rows = frappe.get_all(
			"Manage Change",
			filters={"version_control_url": pr_url, "branch": target_branch},
			fields=fields,
			order_by="modified desc",
			limit=1,
			ignore_permissions=True,
		)

		if not rows:
			# Guard 2 — branch mismatch. Is there an MC bound to this exact PR URL
			# but on a DIFFERENT branch? That's the classic naming mismatch: the MC's
			# branch (its VC Branch record name) doesn't equal the PR's git base ref,
			# so the exact match above misses. Point the dev straight at the fix
			# rather than letting them chase a phantom "no record".
			other = frappe.get_all(
				"Manage Change",
				filters={
					"version_control_url": pr_url,
					"branch": ["!=", target_branch],
					"docstatus": ["<", 2],
				},
				fields=["name", "branch"],
				order_by="modified desc",
				limit=1,
				ignore_permissions=True,
			)
			if other:
				return {
					"approved": False,
					"reason": "branch_mismatch",
					"name": other[0].name,
					"mc_branch": other[0].branch,
					"pr_url": pr_url,
					"target_branch": target_branch,
				}
			return {
				"approved": False,
				"reason": "no_manage_change_record",
				"pr_url": pr_url,
				"target_branch": target_branch,
			}

		mc = rows[0]
		approved = mc.docstatus == 1

		# Load the matched record for the governance context shown on the PR.
		mc_doc = frappe.get_doc("Manage Change", mc.name)
		raised_by, raised_by_name = _named(mc_doc.owner)
		approvers = [
			get_fullname(row.user) or row.user
			for row in (mc_doc.get("approver") or [])
			if row.user
		]

		approved_by = approved_by_name = approved_on = None
		if approved:
			# Primary: explicit field set in before_submit (reliable).
			# Fallback: workflow action history (may be absent for older records).
			approver_user = mc_doc.get("approved_by") or None
			if approver_user:
				approved_by, approved_by_name = _named(approver_user)
				approved_on = str(mc_doc.modified) if mc_doc.modified else None
			else:
				approver_user, acted_on = _resolve_approver(mc.name)
				approved_by, approved_by_name = _named(approver_user)
				approved_on = str(acted_on) if acted_on else None

		return {
			"approved": approved,
			"reason": "approved" if approved else "not_approved",
			"name": mc.name,
			"workflow_state": mc.get("workflow_state"),
			"docstatus": mc.docstatus,
			"pr_url": pr_url,
			"target_branch": target_branch,
			# Governance context (matched record only; endpoint is token-protected).
			"change_type": mc_doc.change_type,
			"department": mc_doc.department,
			"ticket": mc_doc.ticket_id or mc_doc.ticket or None,
			"raised_by": raised_by,
			"raised_by_name": raised_by_name,
			"raised_on": str(mc_doc.creation) if mc_doc.creation else None,
			"approvers": approvers,
			"approved_by": approved_by,
			"approved_by_name": approved_by_name,
			"approved_on": approved_on,
		}
	except Exception:
		frappe.log_error(title="Manage Change Gate Error", message=frappe.get_traceback())
		frappe.local.response["http_status_code"] = 500
		# Don't leak internal error details to an unauthenticated caller.
		return {"approved": False, "reason": "endpoint_error"}
