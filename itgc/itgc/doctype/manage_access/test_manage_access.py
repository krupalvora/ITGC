# Copyright (c) 2026, Krupal Vora and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from itgc.itgc.doctype.manage_access.manage_access import (
	get_effective_doc_perm,
	users_without_role_profile,
)

TEST_ROLE = "System Manager"  # always present on a Frappe site; also a PROTECTED role
ROUTING_ROLE = "ITGC Test Routing Role"  # a plain, non-protected role for routing tests
DEFAULT_DEPT = "ITGC-Test-Default-Dept"  # `department` is mandatory on Manage Access


class TestManageAccess(FrappeTestCase):
	"""Tests for the access system of record.

	Records are created but NOT submitted, so on_submit/apply() never mutates
	real users/roles. FrappeTestCase wraps each test in a transaction that is
	rolled back, so nothing persists.

	`department` is mandatory, so every request that is actually inserted is given
	one. Routing tests use ROUTING_ROLE (a plain role): System Manager is a
	protected role, so a request for it is routed to the protected approvers rather
	than the department — see `_sync_approver_from_department`.
	"""

	def setUp(self):
		_ensure_role(ROUTING_ROLE)
		self.dept = _make_department(DEFAULT_DEPT, ["Guest"])

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
			role=ROUTING_ROLE,
			department=self.dept,
		)
		doc.insert(ignore_permissions=True)

		self.assertEqual(doc.user, frappe.session.user)
		self.assertNotEqual(doc.user, "spoofed@example.com")

	def test_requester_set_when_blank(self):
		doc = self._new_request(
			request_type="Request Role",
			request_for="Administrator",
			role=ROUTING_ROLE,
			department=self.dept,
		)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.user, frappe.session.user)

	def test_subject_defaults_to_requester(self):
		"""For self-oriented types, request_for defaults to the requester."""
		doc = self._new_request(
			request_type="Request Role", role=ROUTING_ROLE, department=self.dept
		)
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.request_for, frappe.session.user)

	def test_request_role_requires_role(self):
		doc = self._new_request(
			request_type="Request Role",
			request_for="Administrator",
			department=self.dept,
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_request_type_is_mandatory(self):
		doc = self._new_request(request_for="Administrator", department=self.dept)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_department_is_mandatory(self):
		"""A request can never be raised without a Department (the approval router)."""
		doc = self._new_request(
			request_type="Request Role", request_for="Administrator", role=ROUTING_ROLE
		)
		with self.assertRaises(frappe.MandatoryError):
			doc.insert(ignore_permissions=True)

	def test_change_doc_perm_requires_doctype_and_role(self):
		doc = self._new_request(
			request_type="Change Doctype Permission", department=self.dept
		)
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
		A plain (non-protected) role is used so routing goes to the department.
		"""
		dept = _make_department("ITGC-Test-Dept-A", ["Guest"])
		doc = self._new_request(
			request_type="Request Role", role=ROUTING_ROLE, department=dept
		)
		doc.insert(ignore_permissions=True)
		self.assertEqual(self._approver_users(doc), ["Guest"])

	def test_no_department_escalates_to_global_access_manager(self):
		"""With no department, the global Access Manager is the fallback approver.

		`department` is mandatory at insert, so the no-department fallback branch is
		exercised by calling the router directly (as it would run mid-validate).
		"""
		_set_global_access_manager("Administrator")
		doc = self._new_request(
			request_type="Request Role", role=ROUTING_ROLE, request_for="Administrator"
		)
		doc.user = frappe.session.user
		doc.department = None
		doc._sync_approver_from_department()
		self.assertEqual(self._approver_users(doc), ["Administrator"])

	def test_requester_only_department_escalates_to_fallback(self):
		"""If the requester is the department's sole approver, escalate so the
		request still has someone (other than the requester) who can approve."""
		_set_global_access_manager("Administrator")
		dept = _make_department("ITGC-Test-Dept-B", [frappe.session.user])
		doc = self._new_request(
			request_type="Request Role", role=ROUTING_ROLE, department=dept
		)
		doc.insert(ignore_permissions=True)
		# The global Access Manager (Administrator) is appended as the fallback.
		self.assertIn("Administrator", self._approver_users(doc))

	def test_approver_resynced_on_save(self):
		"""Changing the department re-derives the approver list on the next save."""
		other = _ensure_user("itgc-approver-b@example.com")
		dept_a = _make_department("ITGC-Test-Dept-C", ["Guest"])
		dept_b = _make_department("ITGC-Test-Dept-D", [other])
		doc = self._new_request(
			request_type="Request Role", role=ROUTING_ROLE, department=dept_a
		)
		doc.insert(ignore_permissions=True)
		self.assertEqual(self._approver_users(doc), ["Guest"])
		doc.department = dept_b
		doc.save(ignore_permissions=True)
		self.assertEqual(self._approver_users(doc), [other])

	# ----------------------------------------------------- maker-checker
	def test_non_owner_cannot_edit_request_content(self):
		"""An approver (any non-owner, non-System-Manager) must not alter a request.

		Otherwise they could edit a pending request and approve their own edited
		version. The guard runs in `validate`, so it holds even when permissions are
		bypassed (e.g. a privileged REST path).
		"""
		doc = self._new_request(
			request_type="Request Role",
			request_for="Administrator",
			role=ROUTING_ROLE,
			department=self.dept,
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
			request_type="Request Role",
			request_for="Administrator",
			role=ROUTING_ROLE,
			department=self.dept,
		)
		doc.insert(ignore_permissions=True)
		doc.role = "Guest"
		doc.save(ignore_permissions=True)  # owner == session user → allowed
		self.assertEqual(doc.role, "Guest")

	# ----------------------------------------------------- user permissions
	def _up_row(self, **kwargs):
		row = {"allow": "User", "for_value": "Administrator", "apply_to_all_doctypes": 1}
		row.update(kwargs)
		return row

	def test_request_user_permission_requires_a_row(self):
		doc = self._new_request(
			request_type="Request User Permission",
			request_for="Administrator",
			department=self.dept,
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_request_user_permission_row_requires_allow_and_value(self):
		doc = self._new_request(
			request_type="Request User Permission",
			request_for="Administrator",
			department=self.dept,
		)
		doc.append("user_permissions", {"allow": "User", "apply_to_all_doctypes": 1})
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_scoped_row_requires_applicable_for(self):
		doc = self._new_request(
			request_type="Request User Permission",
			request_for="Administrator",
			department=self.dept,
		)
		doc.append("user_permissions", self._up_row(apply_to_all_doctypes=0))
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_valid_request_user_permission_passes_validation(self):
		doc = self._new_request(
			request_type="Request User Permission", department=self.dept
		)
		doc.append("user_permissions", self._up_row())
		doc.insert(ignore_permissions=True)  # must not raise
		self.assertEqual(doc.request_for, frappe.session.user)  # self-service default

	def test_apply_creates_and_revoke_removes_user_permission(self):
		"""apply() must mint the User Permission, and the revoke path remove it.

		Calls the apply handlers directly with the sanctioned-writer flag set, exactly
		as on_submit does, so the access-master guard does not block the writes.
		"""
		target = "Administrator"
		allow, for_value = "User", "Guest"
		frappe.db.delete(
			"User Permission", {"user": target, "allow": allow, "for_value": for_value}
		)

		grant = self._new_request(
			request_type="Request User Permission", request_for=target, department=self.dept
		)
		grant.append("user_permissions", self._up_row(for_value=for_value))
		grant.insert(ignore_permissions=True)

		frappe.flags.in_manage_access = True
		try:
			grant.apply_request_user_permission()
			self.assertTrue(
				frappe.db.exists(
					"User Permission",
					{"user": target, "allow": allow, "for_value": for_value},
				)
			)

			revoke = self._new_request(
				request_type="Revoke User Permission",
				request_for=target,
				department=self.dept,
			)
			revoke.append("user_permissions", self._up_row(for_value=for_value))
			revoke.insert(ignore_permissions=True)
			revoke.apply_revoke_user_permission()
			self.assertFalse(
				frappe.db.exists(
					"User Permission",
					{"user": target, "allow": allow, "for_value": for_value},
				)
			)
		finally:
			frappe.flags.in_manage_access = False

	# ----------------------------------------------------- new-user link query
	def test_new_user_query_includes_website_users_without_role_profile(self):
		"""The 'New User' link query keys on absence of a Role Profile, not user_type.

		A fresh self-signup lands as a Website User with no Role Profile (see
		frappe.core ... user.sign_up). It is exactly the user a New User onboarding
		request needs to target, so it must appear in the 'For User' dropdown.
		"""
		email = "itgc-test-website-user@example.com"
		_ensure_user(email, user_type="Website User")

		rows = users_without_role_profile("User", email, "name", 0, 20, None)
		self.assertIn(email, [r[0] for r in rows])

	def test_new_user_query_excludes_users_with_role_profile(self):
		"""A user who already has a Role Profile is onboarded — never a 'New User' target."""
		profile = _ensure_role_profile("ITGC Test Profile")
		email = "itgc-test-onboarded@example.com"
		_ensure_user(email, user_type="System User")
		# Set via db to avoid triggering role-profile role sync on save.
		frappe.db.set_value("User", email, "role_profile_name", profile)

		rows = users_without_role_profile("User", email, "name", 0, 20, None)
		self.assertNotIn(email, [r[0] for r in rows])


def _ensure_role(role_name):
	if not frappe.db.exists("Role", role_name):
		frappe.get_doc(
			{"doctype": "Role", "role_name": role_name, "desk_access": 1}
		).insert(ignore_permissions=True)
	return role_name


def _ensure_user(email, user_type="System User"):
	"""Create (or reuse) an enabled user without sending a welcome email.

	The welcome mail path decrypts the outgoing email account password, which fails
	on a test site whose encryption key does not match — so it is suppressed here.
	"""
	if frappe.db.exists("User", email):
		return email
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "ITGC Test",
			"user_type": user_type,
			"send_welcome_email": 0,
		}
	)
	user.flags.no_welcome_mail = True
	user.insert(ignore_permissions=True)
	return user.name


def _ensure_role_profile(name):
	if frappe.db.exists("Role Profile", name):
		return name
	rp = frappe.new_doc("Role Profile")
	rp.role_profile = name
	rp.append("roles", {"role": ROUTING_ROLE})
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
