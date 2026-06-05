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

# Types that do not act on a subject user (request_for).
NO_SUBJECT_TYPES = (NEW_USER, DISABLE_USER, CHANGE_DOC_PERM)

class ManageAccess(Document):
	def before_insert(self):
		# Requester is always the creating user; read-only in the form, enforced
		# here too since this is the access system of record.
		if not self.user:
			self.user = frappe.session.user

		# Default the subject to the requester for the self-oriented types. New User /
		# Disable User target someone else; Change Doctype Permission has no subject.
		if self.request_type and self.request_type not in NO_SUBJECT_TYPES and not self.request_for:
			self.request_for = self.user

	def validate(self):
		self.validate_request()

	def before_submit(self):
		# Snapshot the role's current permissions on this doctype for the audit
		# trail, BEFORE apply() mutates them in on_submit.
		if self.request_type == CHANGE_DOC_PERM:
			snapshot = get_effective_doc_perm(
				self.document_type, self.perm_role, int(self.permission_level or 0)
			)
			self.previous_permission = frappe.as_json(snapshot)

	def on_submit(self):
		self.apply()

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
