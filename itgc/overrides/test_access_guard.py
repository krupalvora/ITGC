# Copyright (c) 2026, Krupal Vora and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from itgc.overrides.access_guard import (
	block_doctype_perm_change,
	block_user_role_change,
	capture_user_access_state,
)


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


class TestUserRoleGuard(FrappeTestCase):
	"""The User-roles guard must block *only* role / role-profile changes.

	Regression: a role-profile user who also holds an extra role (the re-asserted
	ITGC Access Manager role, or a Manage-Access-granted role) was wrongly blocked
	from editing non-role fields (password, API key). Core's `validate()` runs
	`populate_role_profile_roles()` first, stripping the live roles table down to the
	Role Profile, so the validate-time guard saw the stripped table differ from the
	DB and threw. The guard now compares the user-SUBMITTED snapshot captured on
	`before_validate`, so an unchanged-roles save (any non-role edit) passes.
	"""

	PROFILE = "ITGC Guard Test Profile"
	PROFILE_ROLE = "Newsletter Manager"  # any stock desk role not tied to the profile machinery
	EXTRA_ROLE = "Dashboard Manager"  # an ad-hoc / granted role beyond the profile
	NEW_ROLE = "Blogger"  # a role the user is trying to add
	EMAIL = "itgc-guard-user@example.com"

	def setUp(self):
		# Build the fixture with governance OFF so setup saves are not themselves blocked.
		frappe.db.set_single_value("ITGC Settings", "enable_manage_access", 0)

		if not frappe.db.exists("Role Profile", self.PROFILE):
			rp = frappe.new_doc("Role Profile")
			rp.role_profile = self.PROFILE
			rp.append("roles", {"role": self.PROFILE_ROLE})
			rp.insert(ignore_permissions=True)

		if not frappe.db.exists("User", self.EMAIL):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": self.EMAIL,
					"first_name": "ITGC Guard",
					"user_type": "System User",
					"send_welcome_email": 0,
					"role_profile_name": self.PROFILE,
				}
			)
			user.flags.no_welcome_mail = True
			user.insert(ignore_permissions=True)  # roles now == {PROFILE_ROLE}

		# Persist an extra role directly, mimicking the DB state left by the re-assert
		# hooks (a role beyond the profile that the form will resubmit unchanged).
		if not frappe.db.exists(
			"Has Role", {"parent": self.EMAIL, "parenttype": "User", "role": self.EXTRA_ROLE}
		):
			frappe.get_doc(
				{
					"doctype": "Has Role",
					"parenttype": "User",
					"parent": self.EMAIL,
					"parentfield": "roles",
					"role": self.EXTRA_ROLE,
				}
			).db_insert()

		# Now turn governance on for the assertions (no HTTP request in tests -> in_import).
		frappe.db.set_single_value("ITGC Settings", "enable_manage_access", 1)
		frappe.flags.in_import = True

	def tearDown(self):
		frappe.flags.in_import = False

	def _load_with_submission(self):
		"""Fresh User doc (roles table == DB) with the before_validate snapshot taken."""
		doc = frappe.get_doc("User", self.EMAIL)
		capture_user_access_state(doc)  # before_validate
		return doc

	def test_non_role_edit_allowed_for_role_profile_user_with_extra_role(self):
		"""Password / API-key edit: core strips the live table, but the snapshot matches DB."""
		doc = self._load_with_submission()
		doc.api_key = "itgc-test-key"  # a non-role field edit
		# Simulate core's validate() rewriting the live roles table to the profile.
		doc.populate_role_profile_roles()
		self.assertEqual({r.role for r in doc.get("roles")}, {self.PROFILE_ROLE})
		block_user_role_change(doc)  # roles unchanged vs submission -> must not raise

	def test_adding_a_role_is_blocked(self):
		doc = frappe.get_doc("User", self.EMAIL)
		doc.append("roles", {"role": self.NEW_ROLE})  # user tries to add a role
		capture_user_access_state(doc)  # snapshot includes the new role
		with self.assertRaises(frappe.ValidationError):
			block_user_role_change(doc)

	def test_changing_role_profile_is_blocked(self):
		doc = frappe.get_doc("User", self.EMAIL)
		doc.role_profile_name = ""  # user tries to clear the profile
		capture_user_access_state(doc)
		with self.assertRaises(frappe.ValidationError):
			block_user_role_change(doc)

	def test_exempt_when_flag_off(self):
		frappe.db.set_single_value("ITGC Settings", "enable_manage_access", 0)
		doc = frappe.get_doc("User", self.EMAIL)
		doc.append("roles", {"role": self.NEW_ROLE})
		capture_user_access_state(doc)
		block_user_role_change(doc)  # governance off -> must not raise
