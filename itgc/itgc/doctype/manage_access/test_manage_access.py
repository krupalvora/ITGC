# Copyright (c) 2026, Krupal Vora and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from itgc.itgc.doctype.manage_access.manage_access import (
	get_effective_doc_perm,
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
