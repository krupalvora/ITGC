# Copyright (c) 2026, Krupal Vora and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

BLOCK_HOOK = "itgc.overrides.access_guard.block_user_role_change"
ENSURE_ACCESS_MANAGER = "itgc.overrides.user.ensure_access_manager_role"
ENSURE_GRANTED = "itgc.overrides.user.ensure_granted_roles"


class TestUserValidateHookOrder(FrappeTestCase):
	"""Pin the `User` validate hook order so a reorder fails CI.

	`block_user_role_change` MUST run before the re-assert hooks
	(`ensure_access_manager_role`, `ensure_granted_roles`). It compares the
	submitted roles against the committed DB state to detect a direct role change;
	the ensure_* hooks then mutate the roles table to re-assert privileged/granted
	roles. If a reorder placed an ensure_* hook first, the block guard would see the
	already-mutated table and the maker-checker / access lockdown would silently
	break — with no other test failing. This test is the tripwire for that.
	"""

	def _validate_hooks(self):
		return frappe.get_hooks("doc_events").get("User", {}).get("validate", [])

	def test_all_three_hooks_are_registered(self):
		hooks = self._validate_hooks()
		for hook in (BLOCK_HOOK, ENSURE_ACCESS_MANAGER, ENSURE_GRANTED):
			self.assertIn(hook, hooks, f"{hook} is missing from User validate hooks")

	def test_block_runs_before_reassert_hooks(self):
		hooks = self._validate_hooks()
		block_idx = hooks.index(BLOCK_HOOK)
		self.assertLess(
			block_idx,
			hooks.index(ENSURE_ACCESS_MANAGER),
			"block_user_role_change must run before ensure_access_manager_role",
		)
		self.assertLess(
			block_idx,
			hooks.index(ENSURE_GRANTED),
			"block_user_role_change must run before ensure_granted_roles",
		)


class TestSudoUserRequiredForManageAccess(FrappeTestCase):
	"""Manage Access cannot be enabled without a valid, enabled Sudo User.

	Exercises the controller directly (no DB save) so the rolled-back txn and the
	live ITGC Settings single are untouched. The Sudo User is the break-glass
	approver for protected-role grants; enabling governance without one would let a
	protected-role request stall with no eligible approver.
	"""

	def _settings(self, enable, sudo_user):
		doc = frappe.get_doc("ITGC Settings")
		doc.enable_manage_access = enable
		doc.sudo_user = sudo_user
		return doc

	def test_enabling_without_sudo_user_is_blocked(self):
		doc = self._settings(enable=1, sudo_user=None)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_sudo_user_for_manage_access()

	def test_enabling_with_disabled_sudo_user_is_blocked(self):
		user = self._make_user(enabled=0)
		doc = self._settings(enable=1, sudo_user=user)
		with self.assertRaises(frappe.ValidationError):
			doc.validate_sudo_user_for_manage_access()

	def test_enabling_with_enabled_sudo_user_is_allowed(self):
		user = self._make_user(enabled=1)
		doc = self._settings(enable=1, sudo_user=user)
		doc.validate_sudo_user_for_manage_access()  # must not raise

	def test_disabled_feature_does_not_require_sudo_user(self):
		doc = self._settings(enable=0, sudo_user=None)
		doc.validate_sudo_user_for_manage_access()  # must not raise

	def _make_user(self, enabled):
		email = f"sudo-test-{'on' if enabled else 'off'}@itgc.test"
		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
		else:
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Sudo Test",
					"send_welcome_email": 0,
				}
			)
			user.flags.no_welcome_mail = True
			user.insert(ignore_permissions=True)
		if user.enabled != enabled:
			user.db_set("enabled", enabled)
		return user.name
