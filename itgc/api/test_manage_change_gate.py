# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import set_encrypted_password

from itgc.api.manage_change_gate import _is_authorized, check_pr_approval

TOKEN = "s3cr3t-gate-token"


def _set_token(token):
	set_encrypted_password(
		"ITGC Settings", "ITGC Settings", token, "manage_change_status_endpoint_token"
	)


class TestManageChangeGate(FrappeTestCase):
	"""The merge gate is the CI-facing approval oracle, so its auth must be
	fail-closed: a valid token is always mandatory — there is no public mode.

	Each test sets the token via set_encrypted_password (avoiding the doctype's
	on_update side effects) and mocks the request header. FrappeTestCase rolls
	everything back per test.
	"""

	def _auth_with_header(self, header_value):
		with patch.object(frappe, "get_request_header", return_value=header_value):
			return _is_authorized()

	def test_default_is_fail_closed(self):
		"""No token configured => deny, regardless of the header sent."""
		_set_token("")
		self.assertFalse(self._auth_with_header(None))
		self.assertFalse(self._auth_with_header("anything"))

	def test_token_is_always_required(self):
		_set_token(TOKEN)
		self.assertTrue(self._auth_with_header(TOKEN))
		self.assertFalse(self._auth_with_header("wrong"))
		self.assertFalse(self._auth_with_header(None))
		self.assertFalse(self._auth_with_header(""))

	def test_endpoint_returns_401_when_unauthorized(self):
		_set_token(TOKEN)
		with patch.object(frappe, "get_request_header", return_value="wrong"):
			result = check_pr_approval(pr_url="https://x/pr/1", target_branch="prod")
		self.assertFalse(result["approved"])
		self.assertEqual(result["reason"], "unauthorized")
		self.assertEqual(frappe.local.response.get("http_status_code"), 401)

	def test_authorized_call_does_not_leak_requester_fields(self):
		"""On a successful auth the response must not include approver/ticket data."""
		_set_token(TOKEN)
		with patch.object(frappe, "get_request_header", return_value=TOKEN):
			result = check_pr_approval(
				pr_url="https://example.com/pr/does-not-exist", target_branch="prod"
			)
		# No matching Manage Change, but the point is the contract: no leak keys.
		self.assertNotIn("approver", result)
		self.assertNotIn("ticket_id", result)

	def test_missing_parameters_returns_400(self):
		_set_token(TOKEN)
		with patch.object(frappe, "get_request_header", return_value=TOKEN):
			result = check_pr_approval(pr_url=None, target_branch=None)
		self.assertEqual(result["reason"], "missing_parameters")
		self.assertEqual(frappe.local.response.get("http_status_code"), 400)
