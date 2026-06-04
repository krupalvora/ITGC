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

class ManageAccess(Document):
	def before_insert(self):
		# Requester is always the creating user; read-only in the form, enforced
		# here too since this is the access system of record.
		if not self.user:
			self.user = frappe.session.user

	def validate(self):
		self.validate_request()

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
