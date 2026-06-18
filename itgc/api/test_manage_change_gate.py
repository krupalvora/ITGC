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


def _ensure_vc_branch(branch):
	if not frappe.db.exists("Manage Change VC Branch", branch):
		frappe.get_doc({"doctype": "Manage Change VC Branch", "branch": branch}).insert(
			ignore_permissions=True
		)


def _new_mc(url, branch):
	doc = frappe.new_doc("Manage Change")
	doc.version_control_url = url
	doc.branch = branch
	doc.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
	return doc


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

	def test_pre_match_response_is_minimal(self):
		"""Before a record is matched there is no identity to return, so the
		unknown-branch / no-record responses stay minimal (no governance fields)."""
		_set_token(TOKEN)
		_ensure_vc_branch("prod")
		with patch.object(frappe, "get_request_header", return_value=TOKEN):
			result = check_pr_approval(
				pr_url="https://example.com/pr/does-not-exist", target_branch="prod"
			)
		self.assertEqual(result["reason"], "no_manage_change_record")
		for key in ("raised_by", "approvers", "approved_by", "ticket"):
			self.assertNotIn(key, result)

	def test_matched_record_returns_governance_context(self):
		"""A matched record carries who raised it (+ context) for the PR comment.

		The endpoint is token-protected, so surfacing this to the gate is intended.
		An unsubmitted record yields `not_approved` with the requester populated and
		`approved_by` left None (nobody has approved it yet)."""
		_set_token(TOKEN)
		_ensure_vc_branch("staging")
		pr = "https://example.com/pr/context"
		mc = _new_mc(pr, "staging")  # docstatus 0 -> exists but not approved
		with patch.object(frappe, "get_request_header", return_value=TOKEN):
			result = check_pr_approval(pr_url=pr, target_branch="staging")
		self.assertFalse(result["approved"])
		self.assertEqual(result["reason"], "not_approved")
		self.assertEqual(result["name"], mc.name)
		self.assertEqual(result["raised_by"], mc.owner)
		self.assertTrue(result["raised_by_name"])
		self.assertIn("approvers", result)
		self.assertIsInstance(result["approvers"], list)
		self.assertIsNone(result["approved_by"])

	def test_unknown_branch_is_flagged(self):
		"""A target branch with no VC Branch record gets its own reason, not a
		misleading 'no record'."""
		_set_token(TOKEN)
		branch = "branch-that-does-not-exist"
		self.assertFalse(frappe.db.exists("Manage Change VC Branch", branch))
		with patch.object(frappe, "get_request_header", return_value=TOKEN):
			result = check_pr_approval(pr_url="https://x/pr/1", target_branch=branch)
		self.assertFalse(result["approved"])
		self.assertEqual(result["reason"], "unknown_branch")

	def test_branch_mismatch_is_flagged(self):
		"""An MC bound to this PR URL but a different branch -> branch_mismatch,
		naming the MC's actual branch so the dev can fix it."""
		_set_token(TOKEN)
		_ensure_vc_branch("prod")
		_ensure_vc_branch("staging")
		pr = "https://example.com/pr/mismatch"
		mc = _new_mc(pr, "staging")  # MC says staging...
		with patch.object(frappe, "get_request_header", return_value=TOKEN):
			result = check_pr_approval(pr_url=pr, target_branch="prod")  # ...PR targets prod
		self.assertFalse(result["approved"])
		self.assertEqual(result["reason"], "branch_mismatch")
		self.assertEqual(result["mc_branch"], "staging")
		self.assertEqual(result["name"], mc.name)

	def test_missing_parameters_returns_400(self):
		_set_token(TOKEN)
		with patch.object(frappe, "get_request_header", return_value=TOKEN):
			result = check_pr_approval(pr_url=None, target_branch=None)
		self.assertEqual(result["reason"], "missing_parameters")
		self.assertEqual(frappe.local.response.get("http_status_code"), 400)
