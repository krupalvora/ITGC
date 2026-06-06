# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import hmac

import frappe
from frappe.utils.password import get_decrypted_password


def _is_authorized():
	"""Token check for the merge gate. Fail-closed by default.

	The endpoint is token-protected unless an admin explicitly opts into a
	public endpoint via ITGC Settings -> "Allow Public Manage Change Status API".
	When protected (the default), the caller must send the configured token in
	the `X-ITGC-Token` header. If no token is configured we still deny, so a
	misconfigured site never silently exposes approval state.
	"""
	allow_public = frappe.db.get_single_value(
		"ITGC Settings", "allow_public_manage_change_status_endpoint"
	)
	if allow_public:
		return True

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

	The endpoint is `allow_guest` because CI calls it without a Frappe session,
	but it is token-protected by default (see `_is_authorized`). The response is
	intentionally minimal — only what the merge gate needs — to avoid leaking
	requester/approver identities to anyone who can reach the URL.
	"""

	try:
		if not _is_authorized():
			frappe.local.response["http_status_code"] = 401
			return {"approved": False, "reason": "unauthorized"}

		if not pr_url or not target_branch:
			frappe.local.response["http_status_code"] = 400
			return {"approved": False, "reason": "missing_parameters"}

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
			return {
				"approved": False,
				"reason": "no_manage_change_record",
				"pr_url": pr_url,
				"target_branch": target_branch,
			}

		mc = rows[0]
		approved = mc.docstatus == 1
		return {
			"approved": approved,
			"reason": "submitted" if approved else "not_submitted",
			"name": mc.name,
			"workflow_state": mc.get("workflow_state"),
			"docstatus": mc.docstatus,
			"pr_url": pr_url,
			"target_branch": target_branch,
		}
	except Exception:
		frappe.log_error(title="Manage Change Gate Error", message=frappe.get_traceback())
		frappe.local.response["http_status_code"] = 500
		# Don't leak internal error details to an unauthenticated caller.
		return {"approved": False, "reason": "endpoint_error"}
