# Originally authored by Krupal Vora (2025).
# Migrated to the ITGC app.

import frappe
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.utils import now


STATUS_DRAFT = "Draft"
STATUS_PENDING = "Pending Approval"
STATUS_APPROVED = "Approved"
STATUS_REJECTED = "Rejected"
STATUS_APPLIED = "Applied"
STATUS_FAILED = "Failed"

APPROVER_ROLE = "Access Request Approver"
DECISION_STATUSES = (STATUS_APPROVED, STATUS_REJECTED)


class AccessRequest(Document):
	def before_insert(self):
		if not self.requested_by:
			self.requested_by = frappe.session.user
		if not self.approver:
			self.approver = self._resolve_approver()
		if not self.status:
			self.status = STATUS_DRAFT

	def validate(self):
		if self.status in (STATUS_APPROVED, STATUS_PENDING) and not self._has_changes():
			frappe.throw(
				"This request has no changes to apply. Populate Role Profile, Roles, "
				"Modules, DocPerm or User Permissions before submitting."
			)
		if self.request_type != "New User" and self.target_user:
			has_rm = frappe.db.get_value("User", self.target_user, "custom_reporting_manager")
			if not has_rm:
				frappe.throw(
					f"Target user {self.target_user} has no Reporting Manager. "
					"An approver is required before raising this request."
				)
		self._enforce_approver_role()

	def _enforce_approver_role(self):
		# Defensive: workflow already gates the Approve/Reject buttons, but a direct
		# API call or script could still set status without going through the workflow.
		if self.status not in DECISION_STATUSES:
			return
		# If this isn't a transition (already in decision state at load), skip.
		previous = self.get_doc_before_save()
		if previous and previous.status == self.status:
			return
		if APPROVER_ROLE not in frappe.get_roles(frappe.session.user):
			verb = "approve" if self.status == STATUS_APPROVED else "reject"
			frappe.throw(
				f"Only users with the {APPROVER_ROLE!r} role can {verb} access requests.",
				title="Permission Denied",
			)

	def on_update(self):
		if self.status == STATUS_APPROVED and not self.applied_at:
			self.db_set("decided_at", now(), update_modified=False)
			from itgc.itgc.doctype.access_request.apply import apply_request
			apply_request(self)
		elif self.status == STATUS_REJECTED and not self.decided_at:
			self.db_set("decided_at", now(), update_modified=False)

	def _has_changes(self) -> bool:
		return any(
			[
				self.role_profile,
				self.requested_roles,
				self.requested_modules,
				self.docperm_changes,
				self.user_permissions,
			]
		)

	def _resolve_approver(self) -> str:
		if not self.target_user:
			return frappe.session.user
		rm = frappe.db.get_value("User", self.target_user, "custom_reporting_manager")
		return rm or frappe.session.user


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_filtered_user(doctype, txt, searchfield, start, page_len, filters):
	"""Suggest target users: direct reports of session.user, plus self."""
	User = DocType("User")
	query = (
		frappe.qb.from_(User)
		.select(User.name)
		.where(
			(
				(User.custom_reporting_manager == frappe.session.user)
				| (User.name == frappe.session.user)
			)
			& (User.name.like(f"%{txt}%"))
		)
		.limit(page_len)
		.offset(start)
	)
	return query.run()
