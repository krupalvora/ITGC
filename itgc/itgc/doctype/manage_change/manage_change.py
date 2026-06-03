# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import os

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import get_bench_path, now_datetime


REQUIRED_WORKFLOW_FILES = (
	".github/workflows/manage-change-check.yml",
	".github/workflows/manage-change-recheck.yml",
)

# Canonical source for the workflow files — where devs should copy them from
# when onboarding a new app to the Manage Change gate.
CANONICAL_WORKFLOW_SOURCE_APP = "solar_square"


class ManageChange(Document):
	def autoname(self):
		if self.ticket_id:
			self.name = self.ticket_id
		else:
			formatted_date = now_datetime().strftime("%Y-%m-%d")
			self.name = make_autoname(f"MC-{formatted_date}-.##")

	def before_submit(self):
		self._enforce_workflow_files_present()

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
