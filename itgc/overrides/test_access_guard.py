# Copyright (c) 2026, Krupal Vora and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from itgc.overrides.access_guard import block_doctype_perm_change


class TestDoctypePermGuard(FrappeTestCase):
	"""The DocType-form back door: a custom doctype's standard DocPerm rows are
	editable straight from the DocType form, bypassing the Custom DocPerm guard.
	`block_doctype_perm_change` closes it while Manage Access governance is on.

	`in_import` is used to satisfy `_managed()` (no HTTP request in tests). Each
	test toggles the real `enable_manage_access` flag inside the rolled-back txn.
	"""

	def setUp(self):
		frappe.db.set_single_value("ITGC Settings", "enable_manage_access", 1)
		frappe.flags.in_import = True

	def tearDown(self):
		frappe.flags.in_import = False

	def _flip_a_perm(self, doc):
		doc.permissions[0].delete = 0 if doc.permissions[0].delete else 1

	def test_perm_change_is_blocked_when_governed(self):
		doc = frappe.get_doc("DocType", "ToDo")
		self._flip_a_perm(doc)
		with self.assertRaises(frappe.ValidationError):
			block_doctype_perm_change(doc)

	def test_no_perm_change_is_allowed(self):
		doc = frappe.get_doc("DocType", "ToDo")
		block_doctype_perm_change(doc)  # unchanged perms -> must not raise

	def test_non_permission_edit_is_allowed(self):
		doc = frappe.get_doc("DocType", "ToDo")
		doc.description = "structural edit, permissions untouched"
		block_doctype_perm_change(doc)  # perms unchanged -> must not raise

	def test_exempt_when_not_governed(self):
		"""Break-glass: with no request/import (e.g. bench console) it is exempt."""
		frappe.flags.in_import = False
		doc = frappe.get_doc("DocType", "ToDo")
		self._flip_a_perm(doc)
		block_doctype_perm_change(doc)  # not managed -> must not raise

	def test_exempt_when_flag_off(self):
		frappe.db.set_single_value("ITGC Settings", "enable_manage_access", 0)
		doc = frappe.get_doc("DocType", "ToDo")
		self._flip_a_perm(doc)
		block_doctype_perm_change(doc)  # governance off -> must not raise
