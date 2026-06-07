# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

"""Visibility rules for Manage Access requests.

Anyone may raise a request (the "All" role has create/read/write), so without
these hooks every user could list and open everyone else's access requests. We
narrow visibility to the people with a legitimate interest in a given request:

  - System Manager: sees everything (administration / audit).
  - The requester (`owner`): sees their own requests.
  - The request's approvers (the users in the `approver` table): see the
    requests routed to them so they can approve / reject.

`get_permission_query_conditions` scopes list/report views; `has_permission`
applies the same rule to opening a single document by URL.
"""

import frappe


def _is_admin(user):
	return "System Manager" in frappe.get_roles(user)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _is_admin(user):
		return ""

	user_esc = frappe.db.escape(user)
	return f"""(`tabManage Access`.`owner` = {user_esc} or exists (
		select 1 from `tabManage Access Approver` `a`
		where `a`.`parent` = `tabManage Access`.`name`
			and `a`.`parenttype` = 'Manage Access'
			and `a`.`parentfield` = 'approver'
			and `a`.`user` = {user_esc}
	))"""


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if _is_admin(user):
		return True

	# A new/unsaved doc (e.g. the create check) and the requester's own requests
	# defer to the standard role-based docperms.
	if not doc.get("name") or doc.owner == user:
		return None

	# Approvers may act on requests routed to them; defer to docperms for the rest.
	if user in {row.user for row in (doc.get("approver") or [])}:
		return None

	# Neither owner nor approver: hide it.
	return False
