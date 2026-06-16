# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# request_type values
NEW_USER = "New User"
REQUEST_ROLE = "Request Role"
REQUEST_ROLE_PROFILE = "Request Role Profile"
DISABLE_USER = "Disable User"
REVOKE_ROLE = "Revoke Role"
REVOKE_ROLE_PROFILE = "Revoke Role Profile"
CHANGE_DOC_PERM = "Change Doctype Permission"  # System-Manager-only doc-perm change
CREATE_ROLE_PROFILE = "Create Role Profile"  # System-Manager-only: create a Role Profile
MODIFY_ROLE_PROFILE = "Modify Role Profile"  # System-Manager-only: edit a Role Profile's roles

# Types that do not act on a subject user (request_for). Create/Modify Role Profile
# act on the Role Profile itself; core's update_all_users() re-syncs assigned users.
NO_SUBJECT_TYPES = (NEW_USER, DISABLE_USER, CHANGE_DOC_PERM, CREATE_ROLE_PROFILE, MODIFY_ROLE_PROFILE)

# Revoke types are raised FOR another user, never auto-defaulted to the requester.
REVOKE_TYPES = (REVOKE_ROLE, REVOKE_ROLE_PROFILE)

# Admin actions that only an ITGC Access Manager (or System Manager) may raise, and
# that always target another user — not self-service.
ACCESS_MANAGER_ONLY_TYPES = (REVOKE_ROLE, REVOKE_ROLE_PROFILE, DISABLE_USER)

# Role whose holders can grant/revoke access (see itgc/install.py).
ACCESS_MANAGER_ROLE = "ITGC Access Manager"

# Scalar fields that carry the substance of a request. The maker-checker guard
# (ManageAccess._guard_maker_checker) forbids a non-owner from changing any of
# these once the request exists; the `profile_roles` child table is compared
# separately. `user`/`approver` are server-set (before_insert / validate) and
# `workflow_state`/docstatus are the approver's legitimate channel, so they are
# intentionally excluded.
REQUEST_CONTENT_FIELDS = (
	"request_for", "request_type", "role", "role_profile", "department",
	"document_type", "perm_role", "permission_level", "if_owner",
	"perm_select", "perm_read", "perm_write", "perm_create", "perm_delete",
	"perm_submit", "perm_cancel", "perm_amend", "perm_print", "perm_email",
	"perm_report", "perm_import", "perm_export", "perm_share",
	"new_role_profile_name", "target_role_profile",
)

class ManageAccess(Document):
	def before_insert(self):
		# Requester is always the creating user. This is the access system of
		# record, so we ALWAYS overwrite server-side (never trust a client-supplied
		# value) — even though the field is read-only in the form, the API path
		# could otherwise be used to spoof the requester.
		self.user = frappe.session.user

		# Default the subject to the requester for the self-oriented types (Request
		# Role / Request Role Profile). New User / Disable User and the revoke types
		# target someone else, so they are never defaulted to the requester; Change
		# Doctype Permission and the Role Profile types have no subject.
		if (
			self.request_type
			and self.request_type not in NO_SUBJECT_TYPES
			and self.request_type not in REVOKE_TYPES
			and not self.request_for
		):
			self.request_for = self.user

	def validate(self):
		self._guard_maker_checker()
		self.validate_request()
		self._sync_approver_from_department()

	def _guard_maker_checker(self):
		"""Maker-checker: an approver must not edit the request they are judging.

		Only the requester (`owner`, who edits to fix and resubmit a rejected
		request) or a System Manager may change a request's content once it exists.
		An approver may review it and act on the workflow (Approve/Reject) — and the
		Reject transition is a docstatus-0 `save`, so Frappe hands them `write` — but
		they must not alter the request itself, or they could edit a pending request
		and approve their own edited version. Enforced here in `validate` so it holds
		for the REST API too, not just the desk form.
		"""
		if self.is_new():
			return

		user = frappe.session.user
		if user == self.owner or "System Manager" in frappe.get_roles(user):
			return

		before = self.get_doc_before_save()
		if before is None:
			# Couldn't load the prior version — fail closed rather than trust the
			# incoming values from a non-owner.
			frappe.throw(_("You are not permitted to edit this request."), frappe.PermissionError)

		changed = [f for f in REQUEST_CONTENT_FIELDS if self.get(f) != before.get(f)]
		if [r.role for r in (self.profile_roles or [])] != [r.role for r in (before.profile_roles or [])]:
			changed.append("profile_roles")
		if changed:
			frappe.throw(
				_("Approvers cannot modify a request — only the requester may edit and resubmit it."),
				frappe.PermissionError,
			)

	def _sync_approver_from_department(self):
		"""Populate the read-only `approver` table that the workflow gates approval on.

		The requester picks a Department; its Access Managers (from the Manage
		Access Department mapping) become this request's approvers. The workflow
		transition then narrows the *identity* to exactly these users via
		`frappe.session.user in [d.user for d in doc.approver]`.

		SoD / escalation: `allow_self_approval` is off on the workflow, so a
		requester listed among their department's approvers still cannot approve
		their own request. If that would leave nobody able to approve (the
		requester is the department's only approver, or no department is set), we
		append the global Access Manager from ITGC Settings as a fallback so the
		request is never stuck.

		Protected-role grants override this: only the Sudo User / System Managers
		may approve them, so the approver list is the set of authorised approvers
		(see `_protected_role_approvers`), not the department's Access Managers.
		"""
		self.set("approver", [])

		if get_protected_roles() & self._roles_granted_by_request():
			approvers = list(dict.fromkeys(self._protected_role_approvers()))
			for user in approvers:
				self.append("approver", {"user": user})
			if not approvers:
				frappe.msgprint(
					_(
						"No eligible approver for this protected-role request. "
						"Set a Sudo User in ITGC Settings so it can be approved."
					),
					indicator="orange",
					alert=True,
				)
			return

		users = []
		if self.department:
			users = frappe.get_all(
				"Manage Access Approver",
				filters={"parent": self.department, "parenttype": "Manage Access Department"},
				pluck="user",
				order_by="idx asc",
			)

		requester = self.user or frappe.session.user
		# Is there at least one approver who isn't the requester? If not, escalate.
		if not any(u and u != requester for u in users):
			fallback = frappe.db.get_single_value("ITGC Settings", "access_manager")
			if fallback:
				users = list(users) + [fallback]

		for user in dict.fromkeys(u for u in users if u):  # de-dup, preserve order
			self.append("approver", {"user": user})

	def before_submit(self):
		# Granting a protected role may only be APPROVED by the Sudo User or a
		# System Manager. before_submit runs as the approver acts (docstatus 0->1),
		# so frappe.session.user here is the approver.
		self._guard_protected_role_approval()

		# Snapshot the role's current permissions on this doctype for the audit
		# trail, BEFORE apply() mutates them in on_submit.
		if self.request_type == CHANGE_DOC_PERM:
			snapshot = get_effective_doc_perm(
				self.document_type, self.perm_role, int(self.permission_level or 0)
			)
			self.previous_permission = frappe.as_json(snapshot)

	def on_submit(self):
		# Mark this as the sanctioned writer so the access-master guards
		# (itgc.overrides.access_guard) let our User / Role Profile / Custom DocPerm
		# writes through while Manage Access governance is enabled.
		frappe.flags.in_manage_access = True
		try:
			self.apply()
		finally:
			frappe.flags.in_manage_access = False

	# ------------------------------------------------------------------ helpers
	@property
	def target_user(self):
		"""The user this request acts on (admin-on-behalf: always request_for)."""
		return self.request_for

	def get_target_doc(self):
		user = self.target_user
		if not user or not frappe.db.exists("User", user):
			frappe.throw(_("Target user {0} does not exist.").format(frappe.bold(user or "")))
		doc = frappe.get_doc("User", user)
		# Application is gated by submit permission on this record, so act with
		# elevated rights on the User doc itself.
		doc.flags.ignore_permissions = True
		return doc

	# --------------------------------------------------------------- validation
	def validate_request(self):
		if not self.request_type:
			frappe.throw(_("Request Type is required."))

		# A FULLY RESTRICTED role (e.g. System Manager) may only be REQUESTED by the
		# Sudo User or a System Manager — including when pulled in via a Role Profile.
		# (Approval-Gated roles can be requested by anyone; they are instead gated at
		# approval time in before_submit.) Checked up front so it covers every grant
		# path and the REST API, before the per-type early returns below.
		self._guard_restricted_role_request()

		# Change Doctype Permission: Doctype + Role are required, no subject user.
		if self.request_type == CHANGE_DOC_PERM:
			if not self.document_type or not self.perm_role:
				frappe.throw(_("To change permissions, select both Doctype and Role."))
			return

		# Create / Modify Role Profile: System-Manager-only, acts on the Role Profile
		# itself (no subject user). Requires at least one role row.
		if self.request_type in (CREATE_ROLE_PROFILE, MODIFY_ROLE_PROFILE):
			frappe.only_for("System Manager")
			if not self.profile_roles:
				frappe.throw(_("Add at least one Role to the Role Profile."))
			if self.request_type == CREATE_ROLE_PROFILE:
				if not self.new_role_profile_name:
					frappe.throw(_("Enter a name for the new Role Profile."))
				if frappe.db.exists("Role Profile", self.new_role_profile_name):
					frappe.throw(
						_("Role Profile {0} already exists. Use 'Modify Role Profile' instead.").format(
							frappe.bold(self.new_role_profile_name)
						)
					)
			elif not self.target_role_profile:
				frappe.throw(_("Select the Role Profile to modify."))
			return

		# Revoke / Disable are Access-Manager actions raised FOR another user, not
		# self-service. Enforced here (not just in the form) so the REST API path is
		# covered too. Gated to creation — the requester is fixed at insert.
		if self.request_type in ACCESS_MANAGER_ONLY_TYPES and self.is_new():
			self._require_access_manager()

		# A revoke/disable must not strip the last active holder of a protected role
		# (e.g. the last System Manager) — that would lock everyone out. Re-checked on
		# every save, so it still holds at approval time if the role state has changed.
		if self.request_type in ACCESS_MANAGER_ONLY_TYPES:
			self._guard_protected_role_lockout()

		if not self.request_for:
			frappe.throw(_("Please select the user in 'For User'."))

		if self.request_type == NEW_USER and not (self.role or self.role_profile):
			frappe.throw(_("For a New User, select a Role and/or a Role Profile to assign."))

		if self.request_type in (REQUEST_ROLE, REVOKE_ROLE) and not self.role:
			frappe.throw(_("Please select a Role."))

		if self.request_type in (REQUEST_ROLE_PROFILE, REVOKE_ROLE_PROFILE) and not self.role_profile:
			frappe.throw(_("Please select a Role Profile."))

	def _require_access_manager(self):
		"""Only an ITGC Access Manager, a System Manager, or the Sudo User may raise
		the admin actions in ACCESS_MANAGER_ONLY_TYPES — they act on another user's
		access. The Sudo User is included so the people who can SEE protected roles
		(Sudo User / System Manager) can also revoke them."""
		if ACCESS_MANAGER_ROLE in frappe.get_roles(frappe.session.user):
			return
		if _may_grant_protected_roles(frappe.session.user):
			return
		frappe.throw(
			_("Only an ITGC Access Manager, a System Manager, or the Sudo User can raise a {0} request.").format(
				frappe.bold(self.request_type)
			),
			frappe.PermissionError,
		)

	def _guard_restricted_role_request(self):
		"""Block REQUESTING a fully-restricted role unless the requester may grant it.

		Fully-restricted roles (ITGC Settings -> Fully Restricted Roles, e.g. System
		Manager) may only be requested by the Sudo User or a System Manager. Covers
		direct grants (`role`) and roles pulled in via a Role Profile, so a profile
		containing one can't be used as a bypass.

		Approval-Gated roles are intentionally NOT blocked here — anyone may request
		them; they are gated at approval time (`_guard_protected_role_approval`).

		Authorisation is evaluated against the REQUESTER (`self.user`), not the
		session user, so the check is stable across the approver's workflow saves.
		"""
		granted = self._roles_granted_by_request()
		if not granted:
			return

		restricted = get_restricted_roles() & granted
		if not restricted:
			return

		if _may_grant_protected_roles(self.user):
			return

		frappe.throw(
			_("Only the Sudo User or a System Manager may request the fully-restricted role(s): {0}.").format(
				frappe.bold(", ".join(sorted(restricted)))
			),
			frappe.PermissionError,
		)

	def _guard_protected_role_approval(self):
		"""Block APPROVING a protected-role grant unless the approver may grant it.

		Applies to BOTH tiers (Fully Restricted + Approval-Gated): the user actually
		approving the request (frappe.session.user at submit) must be the Sudo User
		or a System Manager. This is the real grant gate — `_sync_approver_from_department`
		routes such requests to authorised approvers, and this enforces it server-side
		even if the workflow/approver table is bypassed.
		"""
		granted = self._roles_granted_by_request()
		if not granted:
			return

		protected = get_protected_roles() & granted
		if not protected:
			return

		if _may_grant_protected_roles(frappe.session.user):
			return

		frappe.throw(
			_("Only the Sudo User or a System Manager may approve a grant of the protected role(s): {0}.").format(
				frappe.bold(", ".join(sorted(protected)))
			),
			frappe.PermissionError,
		)

	def _protected_role_approvers(self):
		"""Users allowed to approve a protected-role grant.

		Must satisfy BOTH gates: hold the ITGC Access Manager role (so they can act
		on the approval workflow — Frappe checks the transition's `allowed` role
		strictly) AND be able to grant protected roles (Sudo User / System Manager).
		The Sudo User is auto-granted the ITGC Access Manager role, so it always
		qualifies once configured.
		"""
		am_holders = _enabled_role_holders(ACCESS_MANAGER_ROLE)
		return sorted(u for u in am_holders if _may_grant_protected_roles(u))

	def _roles_granted_by_request(self):
		"""The set of roles this request would ADD to a user.

		Empty for revoke / disable / doc-perm requests (those don't mint a role onto
		a user). Role Profile requests expand to the profile's roles; Create/Modify
		Role Profile expand to the roles in the table being applied.
		"""
		roles = set()
		if self.request_type in (NEW_USER, REQUEST_ROLE) and self.role:
			roles.add(self.role)
		if self.request_type in (NEW_USER, REQUEST_ROLE_PROFILE) and self.role_profile:
			roles |= _role_profile_roles(self.role_profile)
		if self.request_type in (CREATE_ROLE_PROFILE, MODIFY_ROLE_PROFILE):
			roles |= {r.role for r in (self.profile_roles or []) if r.role}
		return roles

	def _guard_protected_role_lockout(self):
		"""Block a revoke/disable that would remove the last ACTIVE holder of a
		protected role (e.g. the last System Manager).

		Only the protected roles the target actually holds are considered, and only
		those this request would strip: the role itself (Revoke Role), the protected
		roles inside the profile (Revoke Role Profile), or every held protected role
		(Disable User). If no other enabled user would still hold the role afterwards,
		the request is refused.
		"""
		protected = get_protected_roles()
		if not protected:
			return

		target = self.target_user
		if not target:
			return

		held = _user_roles(target) & protected
		if not held:
			return

		if self.request_type == REVOKE_ROLE:
			removing = {self.role} & held
		elif self.request_type == REVOKE_ROLE_PROFILE:
			removing = _role_profile_roles(self.role_profile) & held
		elif self.request_type == DISABLE_USER:
			removing = held
		else:
			return

		for role in sorted(removing):
			if not _enabled_role_holders(role, exclude_user=target):
				frappe.throw(
					_(
						"This would remove the last active holder of the protected role {0}. "
						"Grant it to another active user first."
					).format(frappe.bold(role)),
					frappe.ValidationError,
				)

	# -------------------------------------------------------------------- apply
	def apply(self):
		if self.request_type == CHANGE_DOC_PERM:
			self.apply_doc_perm()
			return

		handlers = {
			NEW_USER: self.apply_new_user,
			REQUEST_ROLE: self.apply_request_role,
			REQUEST_ROLE_PROFILE: self.apply_request_role_profile,
			DISABLE_USER: self.apply_disable_user,
			REVOKE_ROLE: self.apply_revoke_role,
			REVOKE_ROLE_PROFILE: self.apply_revoke_role_profile,
			CREATE_ROLE_PROFILE: self.apply_create_role_profile,
			MODIFY_ROLE_PROFILE: self.apply_modify_role_profile,
		}
		handler = handlers.get(self.request_type)
		if not handler:
			frappe.throw(_("Unsupported Request Type: {0}").format(self.request_type))
		handler()

	def apply_new_user(self):
		# Assign a Role Profile and/or an individual Role to the new user.
		user = self.get_target_doc()
		if self.role_profile:
			user.role_profile_name = self.role_profile
		if self.role:
			# add_roles() saves; the User validate hook re-asserts this grant
			# after core's role-profile sync would otherwise strip it.
			user.add_roles(self.role)
		else:
			user.save()

	def apply_request_role(self):
		self.get_target_doc().add_roles(self.role)

	def apply_revoke_role(self):
		# Once this revoke is submitted it is excluded from the active grants the
		# User validate hook re-asserts, so the role will not reappear on save.
		self.get_target_doc().remove_roles(self.role)

	def apply_request_role_profile(self):
		user = self.get_target_doc()
		user.role_profile_name = self.role_profile
		user.save()

	def apply_revoke_role_profile(self):
		user = self.get_target_doc()
		if user.role_profile_name == self.role_profile:
			user.role_profile_name = None
			user.save()

	def apply_disable_user(self):
		user = self.get_target_doc()
		user.enabled = 0
		user.save()

	def apply_create_role_profile(self):
		# Create the real Role Profile record. Its roles come from the profile_roles table.
		rp = frappe.new_doc("Role Profile")
		rp.role_profile = self.new_role_profile_name
		for r in self.profile_roles:
			rp.append("roles", {"role": r.role})
		rp.flags.ignore_permissions = True
		rp.insert()

	def apply_modify_role_profile(self):
		# Replace the profile's roles with the table; saving fires core's on_update ->
		# update_all_users(), which re-syncs roles onto every user assigned this profile.
		rp = frappe.get_doc("Role Profile", self.target_role_profile)
		rp.set("roles", [])
		for r in self.profile_roles:
			rp.append("roles", {"role": r.role})
		rp.flags.ignore_permissions = True
		rp.save()

	# Maps Manage Access checkbox fields -> Custom DocPerm permission properties.
	DOC_PERM_RIGHTS = {
		"perm_select": "select",
		"perm_read": "read",
		"perm_write": "write",
		"perm_create": "create",
		"perm_delete": "delete",
		"perm_submit": "submit",
		"perm_cancel": "cancel",
		"perm_amend": "amend",
		"perm_print": "print",
		"perm_email": "email",
		"perm_report": "report",
		"perm_import": "import",
		"perm_export": "export",
		"perm_share": "share",
	}

	def apply_doc_perm(self):
		"""Apply the requested permission row to the doctype's Custom DocPerm.

		Mirrors what the Role Permissions Manager does: ensures a permission row
		for (document_type, perm_role, permission_level) and sets each right /
		the "if owner" flag to match the checkboxes on this record.
		"""
		from frappe.permissions import add_permission, update_permission_property

		permlevel = int(self.permission_level or 0)
		add_permission(self.document_type, self.perm_role, permlevel)

		for fieldname, ptype in self.DOC_PERM_RIGHTS.items():
			update_permission_property(
				self.document_type, self.perm_role, permlevel, ptype,
				1 if self.get(fieldname) else 0, validate=False,
			)
		update_permission_property(
			self.document_type, self.perm_role, permlevel, "if_owner",
			1 if self.if_owner else 0, validate=False,
		)
		frappe.clear_cache(doctype=self.document_type)


# All DocPerm permission flags tracked for doc-perm changes (checkbox ptypes + if_owner).
DOC_PERM_PTYPES = (
	"select", "read", "write", "create", "delete", "submit", "cancel", "amend",
	"print", "email", "report", "import", "export", "share", "if_owner",
)


def get_effective_doc_perm(document_type, role, permlevel=0):
	"""Current effective permission flags for (doctype, role, permlevel).

	Custom DocPerm overrides standard DocPerm whenever any Custom DocPerm row
	exists for the doctype (Frappe's rule), so read from whichever is in effect.
	"""
	permlevel = int(permlevel or 0)
	table = "Custom DocPerm" if frappe.db.exists("Custom DocPerm", {"parent": document_type}) else "DocPerm"
	rows = frappe.get_all(
		table,
		filters={"parent": document_type, "role": role, "permlevel": permlevel},
		fields=[f"`{p}`" for p in DOC_PERM_PTYPES],
		limit=1,
	)
	if not rows:
		return {p: 0 for p in DOC_PERM_PTYPES}
	return {p: int(rows[0].get(p) or 0) for p in DOC_PERM_PTYPES}


@frappe.whitelist()
def get_current_doc_perm(document_type, perm_role, permission_level=0):
	"""Form helper: current permissions keyed by Manage Access field names.

	Used to pre-fill the checkboxes so an admin edits from the real current state
	(and so submitting never silently wipes rights they didn't intend to remove).
	"""
	frappe.only_for("System Manager")
	snapshot = get_effective_doc_perm(document_type, perm_role, permission_level)
	return {
		("if_owner" if ptype == "if_owner" else f"perm_{ptype}"): value
		for ptype, value in snapshot.items()
	}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def users_without_role_profile(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for the 'New User' flow: enabled users with no Role Profile yet.

	"Not yet onboarded" is defined solely by the absence of a Role Profile, NOT by
	user_type. Self-signups land as `Website User` (frappe.core ... user.sign_up
	hard-codes it) and only flip to `System User` once granted a desk-access role —
	so filtering on `user_type = "System User"` hid fresh signups from the 'For User'
	dropdown. They are exactly the users this flow exists to onboard, so we key on
	`role_profile_name` alone and accept any user_type.

	`role_profile_name` is a permlevel-1 field on User, so a client-side filter on it
	(applied via set_query) silently returns nothing for a requester who lacks
	permlevel-1 read access — which also hid the just-created user. Running the filter
	server-side with ignore_permissions evaluates it correctly regardless of the
	requester's field-level access.
	"""
	conditions = {
		"enabled": 1,
		"role_profile_name": ["is", "not set"],
		"name": ["not in", ("Administrator", "Guest")],
	}
	or_filters = None
	if txt:
		or_filters = {"name": ["like", f"%{txt}%"], "full_name": ["like", f"%{txt}%"]}

	return frappe.get_list(
		"User",
		filters=conditions,
		or_filters=or_filters,
		fields=["name", "full_name"],
		start=start,
		page_length=page_len,
		order_by="name asc",
		as_list=True,
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_role_profile_roles(role_profile):
	"""Form helper: a Role Profile's current roles, for prefilling the modify table.

	So the admin edits from the real current state and submitting doesn't silently
	drop roles they didn't intend to remove.
	"""
	frappe.only_for("System Manager")
	roles = frappe.get_all(
		"Has Role",
		filters={"parent": role_profile, "parenttype": "Role Profile"},
		fields=["role"],
		order_by="idx asc",
	)
	return [{"role": r.role} for r in roles]


# --------------------------------------------------------- protected-role helpers
def _settings_roles(parentfield):
	rows = frappe.get_all(
		"Has Role",
		filters={"parenttype": "ITGC Settings", "parentfield": parentfield},
		pluck="role",
	)
	return {r for r in rows if r}


def get_restricted_roles():
	"""Fully-restricted roles (hidden in picker; only Sudo/SM may request)."""
	return _settings_roles("restricted_roles")


def get_approval_gated_roles():
	"""Approval-gated roles (anyone may request; only Sudo/SM may approve)."""
	return _settings_roles("approval_gated_roles")


def get_protected_roles():
	"""All protected roles across both tiers (used by the approval + lockout gates)."""
	return get_restricted_roles() | get_approval_gated_roles()


def _role_profile_roles(role_profile):
	"""The set of roles contained in a Role Profile."""
	if not role_profile:
		return set()
	rows = frappe.get_all(
		"Has Role",
		filters={"parent": role_profile, "parenttype": "Role Profile"},
		pluck="role",
	)
	return {r for r in rows if r}


def _user_roles(user):
	"""The set of roles currently assigned to a user (materialised in Has Role)."""
	if not user:
		return set()
	rows = frappe.get_all(
		"Has Role",
		filters={"parent": user, "parenttype": "User"},
		pluck="role",
	)
	return {r for r in rows if r}


def _enabled_role_holders(role, exclude_user=None):
	"""Enabled users who hold `role`, excluding `exclude_user`."""
	holders = set(
		frappe.get_all(
			"Has Role",
			filters={"parenttype": "User", "role": role},
			pluck="parent",
		)
	)
	holders.discard(exclude_user)
	if not holders:
		return []
	return frappe.get_all(
		"User",
		filters={"name": ["in", list(holders)], "enabled": 1},
		pluck="name",
	)


def _may_grant_protected_roles(user):
	"""True if `user` may grant protected roles: a System Manager, or the configured
	Sudo User (break-glass) in ITGC Settings."""
	if "System Manager" in frappe.get_roles(user):
		return True
	sudo = frappe.db.get_single_value("ITGC Settings", "sudo_user")
	return bool(sudo) and user == sudo


@frappe.whitelist()
def get_protected_role_context():
	"""Form helper: which roles to HIDE from the role pickers, and whether the
	current user may pick them anyway.

	Only FULLY-RESTRICTED roles are hidden; Approval-Gated roles stay visible so
	anyone can request them (their grant is gated server-side at approval time).
	UX only — the real gates are the server-side guards in ManageAccess."""
	return {
		"hidden_roles": sorted(get_restricted_roles()),
		"may_grant": _may_grant_protected_roles(frappe.session.user),
	}
