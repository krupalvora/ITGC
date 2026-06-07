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

		# Default the subject to the requester for the self-oriented types. New User /
		# Disable User target someone else; Change Doctype Permission has no subject.
		if self.request_type and self.request_type not in NO_SUBJECT_TYPES and not self.request_for:
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
		"""
		self.set("approver", [])

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

		if not self.request_for:
			frappe.throw(_("Please select the user in 'For User'."))

		if self.request_type == NEW_USER and not (self.role or self.role_profile):
			frappe.throw(_("For a New User, select a Role and/or a Role Profile to assign."))

		if self.request_type in (REQUEST_ROLE, REVOKE_ROLE) and not self.role:
			frappe.throw(_("Please select a Role."))

		if self.request_type in (REQUEST_ROLE_PROFILE, REVOKE_ROLE_PROFILE) and not self.role_profile:
			frappe.throw(_("Please select a Role Profile."))

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
