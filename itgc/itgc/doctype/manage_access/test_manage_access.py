# Copyright (c) 2026, Krupal Vora and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import file_lock

from itgc.itgc.doctype.manage_access.manage_access import (
	_role_profile_roles,
	get_effective_doc_perm,
	get_protected_roles,
	users_without_role_profile,
)

TEST_ROLE = "System Manager"  # always present on a Frappe site; also a PROTECTED role
ROUTING_ROLE = "ITGC Test Routing Role"  # a plain, non-protected role for routing tests
ROUTING_ROLE_2 = "ITGC Test Routing Role 2"  # second plain role, for modify-profile tests
DEFAULT_DEPT = "ITGC-Test-Default-Dept"  # `department` is mandatory on Manage Access
MA_WORKFLOW = "ITGC Manage Access Approval"  # deactivated in the end-to-end txn tests
SSE_PROFILE = "SSE-Tech"  # the real System-User role profile used for the system-user cases


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
		_ensure_role(ROUTING_ROLE_2)
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

	def test_non_owner_cannot_edit_user_permission_rows(self):
		"""Maker-checker must also cover the `user_permissions` child table.

		It is the substance of a User Permission request, so an approver editing the
		rows then approving would grant access the requester never asked for. The
		guard must reject the row change by a non-owner just like a scalar change.
		"""
		doc = self._new_request(
			request_type="Request User Permission",
			request_for="Administrator",
			department=self.dept,
		)
		doc.append("user_permissions", self._up_row(for_value="Guest"))
		doc.insert(ignore_permissions=True)  # owner == Administrator (the session user)

		# A non-owner tampers with the requested permission value.
		doc.user_permissions[0].for_value = "Administrator"
		try:
			frappe.set_user("Guest")
			with self.assertRaises(frappe.PermissionError):
				doc.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_owner_can_edit_own_user_permission_rows(self):
		"""The requester may still edit their own User Permission rows."""
		doc = self._new_request(
			request_type="Request User Permission",
			request_for="Administrator",
			department=self.dept,
		)
		doc.append("user_permissions", self._up_row(for_value="Guest"))
		doc.insert(ignore_permissions=True)
		doc.user_permissions[0].for_value = "Administrator"
		doc.save(ignore_permissions=True)  # owner == session user → allowed
		self.assertEqual(doc.user_permissions[0].for_value, "Administrator")

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

	# ----------------------------------------------------- role-profile apply
	def _modify_request(self, target_profile, roles):
		req = self._new_request(
			request_type="Modify Role Profile",
			target_role_profile=target_profile,
			department=self.dept,
		)
		for role in roles:
			req.append("profile_roles", {"role": role})
		req.insert(ignore_permissions=True)
		return req

	def _apply_and_cleanup_lock(self, req, signature, handler="apply_modify_role_profile"):
		"""Run an apply handler exactly as on_submit does, then remove any lock file
		left on disk (locks are not transactional, so the test rollback won't)."""
		frappe.flags.in_manage_access = True
		try:
			getattr(req, handler)()
		finally:
			frappe.flags.in_manage_access = False
			file_lock.delete_lock(signature)

	def test_modify_role_profile_clears_stale_lock(self):
		"""Regression: a stale queue_action lock must not permanently block approval.

		Role Profile.on_update enqueues update_all_users() as an after-commit job and
		locks the doc; the lock is released only by the background worker (after_job),
		never within the approving request. If the worker never runs, the lock lingers
		and every later approval dies at check_if_locked() -> DocumentLockedError —
		exactly the staging failure. apply_modify_role_profile must clear it.
		"""
		rp = _make_role_profile("ITGC-Test-RP-Lock", [ROUTING_ROLE])
		# Simulate the orphaned lock left by a prior approval whose worker never ran.
		file_lock.create_lock(rp.get_signature())
		self.assertTrue(rp.is_locked)

		req = self._modify_request(rp.name, [ROUTING_ROLE, ROUTING_ROLE_2])
		# Must NOT raise DocumentLockedError.
		self._apply_and_cleanup_lock(req, rp.get_signature())

		roles = {r.role for r in frappe.get_doc("Role Profile", rp.name).roles}
		self.assertEqual(roles, {ROUTING_ROLE, ROUTING_ROLE_2})

	def test_modify_role_profile_leaves_profile_unlocked(self):
		"""After apply the profile must be left UNLOCKED so the next approval (whose
		worker may also never run) is not blocked — the lock must never wedge."""
		rp = _make_role_profile("ITGC-Test-RP-Unlock", [ROUTING_ROLE])
		req = self._modify_request(rp.name, [ROUTING_ROLE_2])
		self._apply_and_cleanup_lock(req, rp.get_signature())
		self.assertFalse(frappe.get_doc("Role Profile", rp.name).is_locked)

	def test_modify_role_profile_propagates_to_assigned_users_synchronously(self):
		"""An Approved Modify Role Profile must take effect on assigned users inline,
		without depending on the after-commit background worker."""
		rp = _make_role_profile("ITGC-Test-RP-Sync", [ROUTING_ROLE])
		email = _ensure_user("itgc-rp-sync-user@example.com")
		# Assign the profile and materialise its current role on the user, so
		# core's update_all_users() (an inner join on Has Role) sees the user.
		user = frappe.get_doc("User", email)
		user.role_profile_name = rp.name
		user.flags.ignore_permissions = True
		user.save(ignore_permissions=True)
		self.assertIn(ROUTING_ROLE, _db_user_roles(email))

		req = self._modify_request(rp.name, [ROUTING_ROLE, ROUTING_ROLE_2])
		self._apply_and_cleanup_lock(req, rp.get_signature())

		# The new profile role reached the user synchronously (no worker run).
		self.assertIn(ROUTING_ROLE_2, _db_user_roles(email))

	# ----------------------------------------------------- revoke vs profile role
	def test_revoke_role_supplied_by_profile_is_blocked(self):
		"""A per-user Revoke Role for a role the user gets from their Role Profile must
		be refused — core re-applies profile roles on save, so it would silently no-op
		(the production bug: saiyyam kept IT-Support after an approved revoke)."""
		rp = _make_role_profile("ITGC-Test-RP-Revoke", [ROUTING_ROLE])
		email = _ensure_user("itgc-revoke-profile-user@example.com")
		frappe.db.set_value("User", email, "role_profile_name", rp.name)

		req = self._new_request(
			request_type="Revoke Role",
			request_for=email,
			role=ROUTING_ROLE,  # supplied by the profile
			department=self.dept,
		)
		with self.assertRaises(frappe.ValidationError):
			req.insert(ignore_permissions=True)

	def test_revoke_role_not_in_profile_is_allowed(self):
		"""Revoking an ad-hoc role the user does NOT get from their profile is fine."""
		rp = _make_role_profile("ITGC-Test-RP-Revoke-OK", [ROUTING_ROLE])
		email = _ensure_user("itgc-revoke-adhoc-user@example.com")
		frappe.db.set_value("User", email, "role_profile_name", rp.name)

		req = self._new_request(
			request_type="Revoke Role",
			request_for=email,
			role=ROUTING_ROLE_2,  # NOT in the profile
			department=self.dept,
		)
		req.insert(ignore_permissions=True)  # must not raise
		self.assertEqual(req.role, ROUTING_ROLE_2)

	def test_revoke_role_for_user_without_profile_is_allowed(self):
		"""No Role Profile at all → ordinary ad-hoc revoke, always allowed."""
		email = _ensure_user("itgc-revoke-noprofile-user@example.com")
		frappe.db.set_value("User", email, "role_profile_name", None)

		req = self._new_request(
			request_type="Revoke Role",
			request_for=email,
			role=ROUTING_ROLE,
			department=self.dept,
		)
		req.insert(ignore_permissions=True)  # must not raise
		self.assertEqual(req.role, ROUTING_ROLE)

	def test_create_role_profile_creates_and_leaves_unlocked(self):
		"""apply_create_role_profile must mint the profile and not leave it locked."""
		name = "ITGC-Test-RP-Create"
		if frappe.db.exists("Role Profile", name):
			frappe.delete_doc("Role Profile", name, force=True, ignore_permissions=True)

		req = self._new_request(
			request_type="Create Role Profile",
			new_role_profile_name=name,
			department=self.dept,
		)
		req.append("profile_roles", {"role": ROUTING_ROLE})
		req.insert(ignore_permissions=True)

		signature = frappe.get_doc({"doctype": "Role Profile", "name": name}).get_signature()
		self._apply_and_cleanup_lock(req, signature, handler="apply_create_role_profile")

		self.assertTrue(frappe.db.exists("Role Profile", name))
		self.assertFalse(frappe.get_doc("Role Profile", name).is_locked)


class TestManageAccessTransactions(FrappeTestCase):
	"""End-to-end coverage of every subject-acting transaction across 4 user kinds.

	Each transaction is applied through a real submit() (which runs on_submit ->
	apply with frappe.flags.in_manage_access set, exactly like an approval), then the
	user's ACTUAL state — materialised roles (Has Role), role_profile_name, enabled,
	and User Permission rows — is asserted, i.e. we check the change really happened.

	The four categories (per the request):
	  1. Normal (Website) user, newly created
	  2. Normal (Website) user, existing
	  3. System user, newly created, assigned the SSE-Tech Role Profile
	  4. System user, existing, already on the SSE-Tech Role Profile

	The approval Workflow is deactivated for the duration so submit() drives apply()
	directly without needing a live approver/transition; everything is rolled back by
	FrappeTestCase. The access-master guards are inert in tests (no HTTP request).
	"""

	def setUp(self):
		_ensure_role(ROUTING_ROLE)
		_ensure_role(ROUTING_ROLE_2)
		self.dept = _make_department("ITGC-Txn-Dept", ["Administrator"])
		# Deactivate the approval workflow so submit() runs on_submit directly.
		if frappe.db.exists("Workflow", MA_WORKFLOW):
			frappe.db.set_value("Workflow", MA_WORKFLOW, "is_active", 0)
			frappe.clear_cache()
		self.sse_role = self._a_safe_profile_role()

	def tearDown(self):
		frappe.set_user("Administrator")

	# --------------------------------------------------------------- helpers
	def _a_safe_profile_role(self):
		"""A real, non-protected role from the SSE-Tech profile (for the revoke tests),
		or None if the profile is absent on this site."""
		if not frappe.db.exists("Role Profile", SSE_PROFILE):
			return None
		protected = get_protected_roles()
		for role in sorted(_role_profile_roles(SSE_PROFILE)):
			if role not in protected and frappe.db.exists("Role", role):
				return role
		return None

	def _new(self, **kwargs):
		req = frappe.new_doc("Manage Access")
		req.update(kwargs)
		return req

	def _submit(self, req):
		"""Insert + submit a request, running the real apply() via on_submit."""
		req.flags.ignore_permissions = True
		req.insert(ignore_permissions=True)
		req.submit()
		return req

	def _up_request(self, email, allow, for_value, revoke=False):
		req = self._new(
			request_type="Revoke User Permission" if revoke else "Request User Permission",
			request_for=email,
			department=self.dept,
		)
		req.append(
			"user_permissions", {"allow": allow, "for_value": for_value, "apply_to_all_doctypes": 1}
		)
		return req

	def _up_exists(self, email, allow, for_value):
		return bool(
			frappe.db.exists("User Permission", {"user": email, "allow": allow, "for_value": for_value})
		)

	def _assign_profile(self, email, profile):
		"""Put a user on a Role Profile as an 'existing' starting state (materialises
		the profile's roles into Has Role via core's populate_role_profile_roles)."""
		user = frappe.get_doc("User", email)
		user.role_profile_name = profile
		user.flags.ignore_permissions = True
		user.save(ignore_permissions=True)

	def _fresh_user(self, email, user_type):
		email = _ensure_user(email, user_type=user_type)
		frappe.db.set_value("User", email, {"role_profile_name": None, "enabled": 1})
		frappe.db.delete("Has Role", {"parent": email, "parenttype": "User"})
		return email

	# --------------------------------------------------------------- 1) normal, new
	def test_cat1_normal_new_user(self):
		email = self._fresh_user("itgc-txn-normal-new@example.com", "Website User")

		# New User → assign a role
		self._submit(self._new(request_type="New User", request_for=email, role=ROUTING_ROLE, department=self.dept))
		self.assertIn(ROUTING_ROLE, _db_user_roles(email))

		# Request Role → add a second ad-hoc role
		self._submit(self._new(request_type="Request Role", request_for=email, role=ROUTING_ROLE_2, department=self.dept))
		self.assertIn(ROUTING_ROLE_2, _db_user_roles(email))

		# Request User Permission → row created
		self._submit(self._up_request(email, "User", "Administrator"))
		self.assertTrue(self._up_exists(email, "User", "Administrator"))

		# Revoke User Permission → row removed
		self._submit(self._up_request(email, "User", "Administrator", revoke=True))
		self.assertFalse(self._up_exists(email, "User", "Administrator"))

		# Revoke Role → ad-hoc role removed
		self._submit(self._new(request_type="Revoke Role", request_for=email, role=ROUTING_ROLE_2, department=self.dept))
		self.assertNotIn(ROUTING_ROLE_2, _db_user_roles(email))

		# Disable User → user disabled
		self._submit(self._new(request_type="Disable User", request_for=email, department=self.dept))
		self.assertEqual(frappe.db.get_value("User", email, "enabled"), 0)

	# --------------------------------------------------------------- 2) normal, existing
	def test_cat2_normal_existing_user(self):
		email = self._fresh_user("itgc-txn-normal-existing@example.com", "Website User")

		# Request Role (ad-hoc) → present
		self._submit(self._new(request_type="Request Role", request_for=email, role=ROUTING_ROLE, department=self.dept))
		self.assertIn(ROUTING_ROLE, _db_user_roles(email))

		# Request Role Profile → profile set, its role materialised, ad-hoc role retained
		rp = _make_role_profile("ITGC-Txn-Profile", [ROUTING_ROLE_2])
		self._submit(self._new(request_type="Request Role Profile", request_for=email, role_profile=rp.name, department=self.dept))
		self.assertEqual(frappe.db.get_value("User", email, "role_profile_name"), rp.name)
		self.assertIn(ROUTING_ROLE_2, _db_user_roles(email))
		self.assertIn(ROUTING_ROLE, _db_user_roles(email))  # ad-hoc grant re-asserted

		# Revoke Role Profile → link cleared AND the profile's role removed (the fix);
		# the independently-granted ad-hoc role survives.
		self._submit(self._new(request_type="Revoke Role Profile", request_for=email, role_profile=rp.name, department=self.dept))
		self.assertFalse(frappe.db.get_value("User", email, "role_profile_name"))
		self.assertNotIn(ROUTING_ROLE_2, _db_user_roles(email))
		self.assertIn(ROUTING_ROLE, _db_user_roles(email))

		# Disable User
		self._submit(self._new(request_type="Disable User", request_for=email, department=self.dept))
		self.assertEqual(frappe.db.get_value("User", email, "enabled"), 0)

	# --------------------------------------------------------------- 3) system, new + SSE-Tech
	def test_cat3_system_new_user_sse_tech_profile(self):
		if not self.sse_role:
			self.skipTest(f"{SSE_PROFILE} profile/role not available on this site")
		email = self._fresh_user("itgc-txn-sys-new@example.com", "System User")

		# New User assigning the SSE-Tech Role Profile → profile set, its roles materialised
		self._submit(self._new(request_type="New User", request_for=email, role_profile=SSE_PROFILE, department=self.dept))
		self.assertEqual(frappe.db.get_value("User", email, "role_profile_name"), SSE_PROFILE)
		self.assertIn(self.sse_role, _db_user_roles(email))

		# Revoke Role of a PROFILE-supplied role → refused (would silently no-op).
		with self.assertRaises(frappe.ValidationError):
			self._submit(self._new(request_type="Revoke Role", request_for=email, role=self.sse_role, department=self.dept))

		# Revoke Role Profile → link cleared AND profile roles removed.
		self._submit(self._new(request_type="Revoke Role Profile", request_for=email, role_profile=SSE_PROFILE, department=self.dept))
		self.assertFalse(frappe.db.get_value("User", email, "role_profile_name"))
		self.assertNotIn(self.sse_role, _db_user_roles(email))

		# Disable User
		self._submit(self._new(request_type="Disable User", request_for=email, department=self.dept))
		self.assertEqual(frappe.db.get_value("User", email, "enabled"), 0)

	# --------------------------------------------------------------- 4) system, existing on SSE-Tech
	def test_cat4_system_existing_user_with_sse_tech(self):
		if not self.sse_role:
			self.skipTest(f"{SSE_PROFILE} profile/role not available on this site")
		email = self._fresh_user("itgc-txn-sys-existing@example.com", "System User")
		self._assign_profile(email, SSE_PROFILE)  # existing: already on SSE-Tech
		self.assertIn(self.sse_role, _db_user_roles(email))

		# Request Role (ad-hoc extra) → persists despite profile sync (re-asserted)
		self._submit(self._new(request_type="Request Role", request_for=email, role=ROUTING_ROLE_2, department=self.dept))
		self.assertIn(ROUTING_ROLE_2, _db_user_roles(email))
		self.assertIn(self.sse_role, _db_user_roles(email))  # profile role still there

		# Revoke the ad-hoc role → removed; profile role stays
		self._submit(self._new(request_type="Revoke Role", request_for=email, role=ROUTING_ROLE_2, department=self.dept))
		self.assertNotIn(ROUTING_ROLE_2, _db_user_roles(email))
		self.assertIn(self.sse_role, _db_user_roles(email))

		# Revoke the PROFILE-supplied role → refused
		with self.assertRaises(frappe.ValidationError):
			self._submit(self._new(request_type="Revoke Role", request_for=email, role=self.sse_role, department=self.dept))

		# User Permission grant + revoke
		self._submit(self._up_request(email, "User", "Administrator"))
		self.assertTrue(self._up_exists(email, "User", "Administrator"))
		self._submit(self._up_request(email, "User", "Administrator", revoke=True))
		self.assertFalse(self._up_exists(email, "User", "Administrator"))

		# Revoke Role Profile → profile roles removed
		self._submit(self._new(request_type="Revoke Role Profile", request_for=email, role_profile=SSE_PROFILE, department=self.dept))
		self.assertNotIn(self.sse_role, _db_user_roles(email))


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


def _make_role_profile(name, roles):
	"""Create (replacing any existing) a Role Profile with exactly `roles`, left
	unlocked so a test starts from a clean lock state."""
	if frappe.db.exists("Role Profile", name):
		frappe.delete_doc("Role Profile", name, force=True, ignore_permissions=True)
	rp = frappe.new_doc("Role Profile")
	rp.role_profile = name
	for role in roles:
		rp.append("roles", {"role": role})
	rp.flags.ignore_permissions = True
	rp.insert(ignore_permissions=True)
	# insert() -> on_update -> queue_action also locks the doc; clear it so the test
	# observes only the lock state produced by the code under test.
	if rp.is_locked:
		rp.unlock()
	return rp


def _db_user_roles(user):
	return {
		r.role
		for r in frappe.get_all(
			"Has Role",
			filters={"parent": user, "parenttype": "User"},
			fields=["role"],
		)
	}


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
