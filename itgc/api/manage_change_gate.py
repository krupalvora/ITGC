# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import frappe


@frappe.whitelist(allow_guest=True, methods=["GET"])
def check_pr_approval(pr_url=None, target_branch=None):
	"""Return approval state for a PR. Consumed by the GitHub Actions merge gate.

	A PR is considered approved when a Manage Change record exists with
	`version_control_url == pr_url`, `branch == target_branch`, and `docstatus == 1`.
	"""

	try:
		protect_flag = frappe.db.get_single_value(
			"ITGC Settings", "protect_manage_change_status_endpoint"
		)
		if protect_flag:
			expected = frappe.utils.password.get_decrypted_password(
				"ITGC Settings",
				"ITGC Settings",
				fieldname="manage_change_status_endpoint_token",
				raise_exception=False,
			)
			provided = frappe.get_request_header("X-ITGC-Token")
			if not expected or provided != expected:
				frappe.local.response["http_status_code"] = 401
				return {"approved": False, "reason": "unauthorized"}

		if not pr_url or not target_branch:
			frappe.local.response["http_status_code"] = 400
			return {"approved": False, "reason": "missing_parameters"}

		rows = frappe.get_all(
			"Manage Change",
			filters={"version_control_url": pr_url, "branch": target_branch},
			fields=["name", "docstatus", "workflow_state", "approver", "ticket_id"],
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
			"ticket_id": mc.ticket_id,
			"approver": mc.approver,
			"workflow_state": mc.workflow_state,
			"docstatus": mc.docstatus,
			"pr_url": pr_url,
			"target_branch": target_branch,
		}
	except Exception as e:
		frappe.log_error(title="Manage Change Gate Error", message=frappe.get_traceback())
		frappe.local.response["http_status_code"] = 500
		return {
			"approved": False,
			"reason": "endpoint_error",
			"error": str(e),
		}
