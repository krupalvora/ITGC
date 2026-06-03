# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import os
import shutil

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import get_bench_path, now_datetime


REQUIRED_WORKFLOW_FILES = (
	".github/workflows/manage-change-check.yml",
	".github/workflows/manage-change-recheck.yml",
)

# Canonical source for the workflow files when copying into another app's repo.
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
		status = _workflow_files_status(self.erp_app)
		if status["ok"]:
			return

		if status.get("app_missing"):
			frappe.throw(
				f"App folder for {self.erp_app!r} not found at {status['repo_root']}. "
				"Cannot verify Manage Change workflow files.",
				title="Workflow Files Missing",
			)

		file_lines = "<br>".join(f"<code>{m}</code>" for m in status["missing"])
		frappe.throw(
			f"App {self.erp_app!r} is missing required GitHub workflow file(s):"
			f"<br>{file_lines}<br><br>"
			"Add and commit these files to the app's repo before submitting this Manage Change.",
			title="Workflow Files Missing",
		)


def _workflow_files_status(erp_app: str) -> dict:
	"""Return whether erp_app has the required workflow files; list any missing."""
	if not erp_app:
		return {"ok": False, "missing": list(REQUIRED_WORKFLOW_FILES), "app_missing": True, "repo_root": None}

	repo_root = os.path.join(get_bench_path(), "apps", erp_app)
	if not os.path.isdir(repo_root):
		return {"ok": False, "missing": list(REQUIRED_WORKFLOW_FILES), "app_missing": True, "repo_root": repo_root}

	missing = [
		rel for rel in REQUIRED_WORKFLOW_FILES
		if not os.path.isfile(os.path.join(repo_root, rel))
	]
	return {"ok": not missing, "missing": missing, "app_missing": False, "repo_root": repo_root}


@frappe.whitelist()
def check_workflow_files(erp_app: str) -> dict:
	"""Form-side check used by manage_change.js before submit."""
	return _workflow_files_status(erp_app)


@frappe.whitelist()
def copy_workflow_files(target_app: str) -> dict:
	"""Copy the canonical Manage Change workflow files into target_app's repo.

	Only copies the files that are missing — existing files in the target are
	never overwritten. Caller must commit and push the result in the target
	app's repo for the GitHub check to actually run.
	"""
	frappe.only_for("System Manager")

	if not target_app:
		frappe.throw("target_app is required.")

	bench = get_bench_path()
	source_root = os.path.join(bench, "apps", CANONICAL_WORKFLOW_SOURCE_APP)
	target_root = os.path.join(bench, "apps", target_app)

	if target_app == CANONICAL_WORKFLOW_SOURCE_APP:
		frappe.throw(
			f"{CANONICAL_WORKFLOW_SOURCE_APP!r} is the canonical source — it cannot be its own target."
		)
	if not os.path.isdir(target_root):
		frappe.throw(f"Target app folder not found: {target_root}")
	if not os.path.isdir(source_root):
		frappe.throw(f"Canonical source folder not found: {source_root}")

	copied: list[str] = []
	skipped_existing: list[str] = []
	skipped_missing_source: list[str] = []

	for rel in REQUIRED_WORKFLOW_FILES:
		src = os.path.join(source_root, rel)
		dst = os.path.join(target_root, rel)

		if not os.path.isfile(src):
			skipped_missing_source.append(rel)
			continue
		if os.path.isfile(dst):
			skipped_existing.append(rel)
			continue

		os.makedirs(os.path.dirname(dst), exist_ok=True)
		shutil.copy2(src, dst)
		copied.append(rel)

	return {
		"copied": copied,
		"skipped_existing": skipped_existing,
		"skipped_missing_source": skipped_missing_source,
		"target_root": target_root,
	}
