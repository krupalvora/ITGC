# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import os

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import get_bench_path, get_fullname, get_url_to_form, now_datetime


REQUIRED_WORKFLOW_FILES = (
	".github/workflows/manage-change-check.yml",
	".github/workflows/manage-change-recheck.yml",
)

# Canonical source for the workflow files — where devs should copy them from
# when onboarding a new app to the Manage Change gate. Manage Change lives in
# the itgc app, so itgc holds the canonical YAMLs.
CANONICAL_WORKFLOW_SOURCE_APP = "itgc"


class ManageChange(Document):
	def autoname(self):
		if self.ticket_id:
			self.name = self.ticket_id
		else:
			formatted_date = now_datetime().strftime("%Y-%m-%d")
			self.name = make_autoname(f"MC-{formatted_date}-.##")

	def validate(self):
		self._sync_approver_from_department()

	def _sync_approver_from_department(self):
		# Approver is a read-only Table MultiSelect that mirrors the HOD list of
		# the selected department. It can't use fetch_from (that only works for
		# scalar fields), so we copy the department's HOD rows here.
		self.set("approver", [])
		if not self.department:
			return
		hods = frappe.get_all(
			"Manage Change HOD",
			filters={"parent": self.department, "parenttype": "Manage Change Department"},
			pluck="user",
			order_by="idx asc",
		)
		for user in hods:
			self.append("approver", {"user": user})

	def before_submit(self):
		self._enforce_workflow_files_present()

	def after_insert(self):
		# A freshly raised change sits in the workflow's first state (Pending) and
		# needs the department's approvers to act on it.
		if self._notifications_enabled():
			self._notify_approvers_of_request()

	def on_submit(self):
		# Submit only happens via the workflow "Approve" transition, so reaching
		# docstatus 1 means the change was approved -> tell the requester.
		if self._notifications_enabled():
			self._notify_requester_of_approval()

	# --- Notifications -----------------------------------------------------
	def _notifications_enabled(self):
		settings = frappe.get_cached_doc("ITGC Settings")
		return bool(settings.enable_change_management and settings.notify_manage_change)

	def _approver_user_ids(self):
		# De-duplicate while preserving order.
		return list(dict.fromkeys(row.user for row in (self.approver or []) if row.user))

	def _notify_approvers_of_request(self):
		recipients = self._approver_user_ids()
		if not recipients:
			return

		url = get_url_to_form(self.doctype, self.name)
		raised_by = get_fullname(self.owner) or self.owner
		subject = _("Manage Change {0} awaiting your approval").format(self.name)
		message = _(
			"<p>A Manage Change request <b>{0}</b> has been raised and is awaiting your approval.</p>"
			"<ul>"
			"<li><b>Department:</b> {1}</li>"
			"<li><b>Change Type:</b> {2}</li>"
			"<li><b>App / Branch:</b> {3} / {4}</li>"
			"<li><b>Raised by:</b> {5}</li>"
			"</ul>"
			'<p><a href="{6}">Open the request</a> to approve or reject it.</p>'
		).format(
			self.name,
			self.department or "",
			self.change_type or "",
			self.erp_app or "",
			self.branch or "",
			raised_by,
			url,
		)
		self._send_notification(recipients, subject, message)

	def _notify_requester_of_approval(self):
		if not self.owner:
			return

		url = get_url_to_form(self.doctype, self.name)
		approved_by = get_fullname(frappe.session.user) or frappe.session.user
		subject = _("Your Manage Change {0} has been approved").format(self.name)
		message = _(
			"<p>Your Manage Change request <b>{0}</b> has been <b>approved</b> by {1}.</p>"
			'<p><a href="{2}">Open the request</a>.</p>'
		).format(self.name, approved_by, url)
		self._send_notification([self.owner], subject, message)

	def _send_notification(self, user_ids, subject, message):
		"""Deliver both an in-app (bell) alert and an email to each user."""
		for user in user_ids:
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"for_user": user,
					"type": "Alert",
					"subject": subject,
					"email_content": message,
					"document_type": self.doctype,
					"document_name": self.name,
				}
			).insert(ignore_permissions=True)

		emails = [frappe.db.get_value("User", u, "email") or u for u in user_ids]
		emails = [e for e in emails if e]
		if emails:
			frappe.sendmail(
				recipients=emails,
				subject=subject,
				message=message,
				reference_doctype=self.doctype,
				reference_name=self.name,
			)

	def _enforce_workflow_files_present(self):
		# The MC gate is enforced by GitHub Actions workflow files living in the
		# target app's repo. Submitting an MC for an app whose repo doesn't carry
		# those files would create an MC that can never actually gate a PR — so we
		# block submit until the files are committed in the app's repo.
		#
		# We deliberately do NOT offer to copy files from this UI — that would
		# constitute a Frappe-side write into another app's source tree without
		# going through that app's normal PR review, weakening the SoD that
		# Manage Change is meant to enforce. Devs add the files manually.
		repo_root = os.path.join(get_bench_path(), "apps", self.erp_app)
		if not os.path.isdir(repo_root):
			frappe.throw(
				f"App folder for {self.erp_app!r} not found at {repo_root}. "
				"Cannot verify Manage Change workflow files.",
				title="Workflow Files Missing",
			)

		missing = [
			rel for rel in REQUIRED_WORKFLOW_FILES
			if not os.path.isfile(os.path.join(repo_root, rel))
		]
		if not missing:
			return

		file_lines = "<br>".join(f"<code>{m}</code>" for m in missing)
		cp_cmd = (
			f"cp apps/{CANONICAL_WORKFLOW_SOURCE_APP}/.github/workflows/manage-change-*.yml "
			f"apps/{self.erp_app}/.github/workflows/"
		)
		frappe.throw(
			f"App {self.erp_app!r} is missing required GitHub workflow file(s):"
			f"<br>{file_lines}<br><br>"
			"Copy them from the canonical source and commit + push them via a normal PR "
			f"in <code>{self.erp_app}</code>'s repo:<br><br>"
			f"<code>mkdir -p apps/{self.erp_app}/.github/workflows && {cp_cmd}</code><br><br>"
			"After the PR is merged, re-submit this Manage Change.",
			title="Workflow Files Missing",
		)
