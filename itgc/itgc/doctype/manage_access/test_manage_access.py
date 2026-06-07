# Copyright (c) 2026, Krupal Vora and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from itgc.itgc.doctype.manage_access.manage_access import (
	get_effective_doc_perm,
	users_without_role_profile,
)

TEST_ROLE = "System Manager"  # always present on a Frappe site


class TestManageAccess(FrappeTestCase):
	"""Tests for the access system of record.

	Records are created but NOT submitted, so on_submit/apply() never mutates
	real users/roles. FrappeTestCase wraps each test in a transaction that is
	rolled back, so nothing persists.
	"""

	def _new_request(self, **kwargs):
		doc = frappe.new_doc("Manage Access")
		doc.update(kwargs)
		return doc

	def test_requester_is_forced_to_session_user(self):
		"""A client-supplied `user` must be overwritten with the session user.

		This is the anti-spoofing guard: the requester is the audit actor and
		must never be settable by the caller (e.g. via the REST API).
		"""
		doc = self._new_request(
			user="spoofed@example.com",
			request_type="Request Role",
			request_for="Administrator",
			role=TEST_ROLE,
		)
		doc.insert(ignore_permissions=True)

		self.assertEqual(doc.user, frappe.session.user)
		self.assertNotEqual(doc.user, "spoofed@example.com")

	def test_requester_set_when_blank(self):
		doc = self._new_request(
			request_type="Request Role",
			request_for="Administrator",
			role=TEST_ROLE,
		)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.user, frappe.session.user)

	def test_subject_defaults_to_requester(self):
		"""For self-oriented types, request_for defaults to the requester."""
		doc = self._new_request(request_type="Request Role", role=TEST_ROLE)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.request_for, frappe.session.user)

	def test_request_role_requires_role(self):
		doc = self._new_request(
			request_type="Request Role",
			request_for="Administrator",
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_request_type_is_mandatory(self):
		doc = self._new_request(request_for="Administrator")
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_change_doc_perm_requires_doctype_and_role(self):
		doc = self._new_request(request_type="Change Doctype Permission")
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_get_effective_doc_perm_shape(self):
		"""The snapshot helper returns every tracked ptype as 0/1 ints."""
		snap = get_effective_doc_perm("User", TEST_ROLE, 0)
		self.assertIn("read", snap)
		self.assertIn("if_owner", snap)
		for value in snap.values():
			self.assertIn(value, (0, 1))

	# ----------------------------------------------------- approver routing
	def _approver_users(self, doc):
		return [row.user for row in doc.approver]

	def test_approver_synced_from_department(self):
		"""The department's Access Managers become the request's approvers.

		Uses Guest (never the test session user) as the department approver so the
		result reflects a pure department sync, not the requester escalation path.
		"""
		dept = _make_department("ITGC-Test-Dept-A", ["Guest"])
		doc = self._new_request(
			request_type="Request Role", role=TEST_ROLE, department=dept
		)
		doc.insert(ignore_permissions=True)
		self.assertEqual(self._approver_users(doc), ["Guest"])

	def test_no_department_escalates_to_global_access_manager(self):
		"""With no department, the global Access Manager is the fallback approver."""
		_set_global_access_manager("Administrator")
		doc = self._new_request(request_type="Request Role", role=TEST_ROLE)
		doc.insert(ignore_permissions=True)
		self.assertEqual(self._approver_users(doc), ["Administrator"])

	def test_requester_only_department_escalates_to_fallback(self):
		"""If the requester is the department's sole approver, escalate so the
		request still has someone (other than the requester) who can approve."""
		_set_global_access_manager("Administrator")
		dept = _make_department("ITGC-Test-Dept-B", [frappe.session.user])
		doc = self._new_request(
			request_type="Request Role", role=TEST_ROLE, department=dept
		)
		doc.insert(ignore_permissions=True)
		# The global Access Manager (Administrator) is appended as the fallback.
		self.assertIn("Administrator", self._approver_users(doc))

	def test_approver_resynced_on_save(self):
		"""Changing the department re-derives the approver list on the next save."""
		dept_a = _make_department("ITGC-Test-Dept-C", ["Administrator"])
		dept_b = _make_department("ITGC-Test-Dept-D", ["Guest"])
		doc = self._new_request(
			request_type="Request Role", role=TEST_ROLE, department=dept_a
		)
		doc.insert(ignore_permissions=True)
		self.assertEqual(self._approver_users(doc), ["Administrator"])
		doc.department = dept_b
		doc.save(ignore_permissions=True)
		self.assertEqual(self._approver_users(doc), ["Guest"])

	# ----------------------------------------------------- maker-checker
	def test_non_owner_cannot_edit_request_content(self):
		"""An approver (any non-owner, non-System-Manager) must not alter a request.

		Otherwise they could edit a pending request and approve their own edited
		version. The guard runs in `validate`, so it holds even when permissions are
		bypassed (e.g. a privileged REST path).
		"""
		doc = self._new_request(
			request_type="Request Role", request_for="Administrator", role=TEST_ROLE
		)
		doc.insert(ignore_permissions=True)  # owner == Administrator (the session user)

		doc.role = "Guest"  # tamper with the request content
		try:
			frappe.set_user("Guest")  # a non-owner without System Manager
			with self.assertRaises(frappe.PermissionError):
				doc.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_owner_can_edit_own_request(self):
		"""The requester may still edit their own request (e.g. fix and resubmit)."""
		doc = self._new_request(
			request_type="Request Role", request_for="Administrator", role=TEST_ROLE
		)
		doc.insert(ignore_permissions=True)
		doc.role = "Guest"
		doc.save(ignore_permissions=True)  # owner == session user → allowed
		self.assertEqual(doc.role, "Guest")

	def test_new_user_query_includes_website_users_without_role_profile(self):
		"""The 'New User' link query keys on absence of a Role Profile, not user_type.

		A fresh self-signup lands as a Website User with no Role Profile (see
		frappe.core ... user.sign_up). It is exactly the user a New User onboarding
		request needs to target, so it must appear in the 'For User' dropdown.
		"""
		email = "itgc-test-website-user@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = "ITGC Website"
		user.user_type = "Website User"
		user.insert(ignore_permissions=True)

		rows = users_without_role_profile("User", email, "name", 0, 20, None)
		self.assertIn(email, [r[0] for r in rows])

	def test_new_user_query_excludes_users_with_role_profile(self):
		"""A user who already has a Role Profile is onboarded — never a 'New User' target."""
		profile = _ensure_role_profile("ITGC Test Profile")
		email = "itgc-test-onboarded@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = "ITGC Onboarded"
		user.user_type = "System User"
		user.insert(ignore_permissions=True)
		# Set via db to avoid triggering role-profile role sync on save.
		frappe.db.set_value("User", email, "role_profile_name", profile)

		rows = users_without_role_profile("User", email, "name", 0, 20, None)
		self.assertNotIn(email, [r[0] for r in rows])


def _ensure_role_profile(name):
	if frappe.db.exists("Role Profile", name):
		return name
	rp = frappe.new_doc("Role Profile")
	rp.role_profile = name
	rp.append("roles", {"role": TEST_ROLE})
	rp.insert(ignore_permissions=True)
	return rp.name


def _make_department(name, users):
	if frappe.db.exists("Manage Access Department", name):
		frappe.delete_doc("Manage Access Department", name, force=True)
	dept = frappe.new_doc("Manage Access Department")
	dept.name1 = name
	for user in users:
		dept.append("approver", {"user": user})
	dept.insert(ignore_permissions=True)
	return dept.name


def _set_global_access_manager(user):
	frappe.db.set_single_value("ITGC Settings", "access_manager", user)
