# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from itgc.itgc.report.itgc_user_modified_logs.itgc_user_modified_logs import execute

EXCL_ROLE = "ITGC Test Excluded Role"
MODIFIER_WITH_ROLE = "itgc_excl_modifier@example.com"
MODIFIER_NO_ROLE = "itgc_plain_modifier@example.com"
TARGET_USER = "itgc_target_user@example.com"


def _ensure_role(name):
	if not frappe.db.exists("Role", name):
		frappe.get_doc({"doctype": "Role", "role_name": name}).insert(ignore_permissions=True)


def _ensure_user(email, roles=None):
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"enabled": 1,
			}
		)
		user.flags.ignore_permissions = True
		user.insert(ignore_permissions=True)
	if roles:
		frappe.get_doc("User", email).add_roles(*roles)


def _make_user_version(docname, modified_by):
	"""A Version row attributed to `modified_by` against a User doc."""
	v = frappe.get_doc(
		{
			"doctype": "Version",
			"ref_doctype": "User",
			"docname": docname,
			"data": '{"changed": []}',
		}
	)
	v.flags.ignore_permissions = True
	v.insert(ignore_permissions=True)
	# modified_by is auto-set to the session user on insert; force the actor.
	frappe.db.set_value("Version", v.name, "modified_by", modified_by, update_modified=False)
	return v.name


class TestITGCUserModifiedLogs(FrappeTestCase):
	"""Regression guard for the exclude_role bug.

	The old query used `T2.role != exclude_role`, which still surfaced changes
	by users who hold the excluded role (via their other role rows). The fix
	excludes any modifier who holds the role at all.
	"""

	def setUp(self):
		_ensure_role(EXCL_ROLE)
		_ensure_user(MODIFIER_WITH_ROLE, roles=[EXCL_ROLE])
		_ensure_user(MODIFIER_NO_ROLE)
		# Give the excluded modifier a second (common) role too, to reproduce the
		# exact false-negative the old `!=` logic produced.
		frappe.get_doc("User", MODIFIER_WITH_ROLE).add_roles("System Manager")
		_ensure_user(TARGET_USER)

		# Make the target User look "modified after creation" and inside range.
		frappe.db.set_value(
			"User", TARGET_USER, {"creation": "2026-01-01 00:00:00", "modified": "2026-01-02 00:00:00"},
			update_modified=False,
		)

		_make_user_version(TARGET_USER, MODIFIER_WITH_ROLE)
		_make_user_version(TARGET_USER, MODIFIER_NO_ROLE)

	def _run(self, exclude_role=None):
		filters = {
			"date_field": "User Modified",
			"from_date": "2026-01-01",
			"to_date": "2026-12-31",
		}
		if exclude_role:
			filters["exclude_role"] = exclude_role
		_columns, rows = execute(filters)
		return [r["modified_by"] for r in rows if r["id"] == TARGET_USER]

	def test_without_exclude_both_modifiers_present(self):
		modifiers = self._run()
		self.assertIn(MODIFIER_WITH_ROLE, modifiers)
		self.assertIn(MODIFIER_NO_ROLE, modifiers)

	def test_exclude_role_hides_only_role_holder(self):
		modifiers = self._run(exclude_role=EXCL_ROLE)
		# The role holder is gone even though they also hold System Manager.
		self.assertNotIn(MODIFIER_WITH_ROLE, modifiers)
		# The unrelated modifier is still shown.
		self.assertIn(MODIFIER_NO_ROLE, modifiers)
