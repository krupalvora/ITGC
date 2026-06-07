# Copyright (c) 2026, Krupal Vora and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

PR1 = "https://github.com/solar-square/erp-next/pull/901"
PR2 = "https://github.com/solar-square/erp-next/pull/902"


class TestManageChange(FrappeTestCase):
	"""Tests for the version_control_url binding controls.

	Docs are kept at docstatus 0 (never submitted) so we don't depend on the
	workflow-file check; the freeze/uniqueness rules run in validate() regardless
	of docstatus. ignore_mandatory/ignore_links lets us skip the unrelated reqd
	master links (department/branch/etc.). FrappeTestCase rolls back per test.

	The post-submit case is covered separately by faking docstatus=1 (the URL is
	allow_on_submit, so real edits happen after submit via update_after_submit,
	which skips validate()).
	"""

	def _new_mc(self, url=None):
		doc = frappe.new_doc("Manage Change")
		if url is not None:
			doc.version_control_url = url
		doc.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
		return doc

	def test_unbound_url_is_editable(self):
		"""An MC left at the 'Not Set' default isn't locked — it can be bound."""
		doc = self._new_mc()  # default "Not Set"
		doc.version_control_url = PR1
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.version_control_url, PR1)

	def test_url_is_frozen_once_set(self):
		"""Once a real URL is saved it cannot be repointed at another PR."""
		doc = self._new_mc(PR1)
		doc.version_control_url = PR2
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_bound_url_cannot_be_cleared(self):
		"""Clearing a bound URL (to later rebind) is also blocked."""
		doc = self._new_mc(PR1)
		doc.version_control_url = "Not Set"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_url_must_be_unique_across_active_records(self):
		"""The same PR URL can't be linked to two active Manage Changes."""
		self._new_mc(PR1)
		dup = frappe.new_doc("Manage Change")
		dup.version_control_url = PR1
		with self.assertRaises(frappe.ValidationError):
			dup.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)

	def test_resaving_same_url_is_allowed(self):
		"""Saving an MC again without touching the (already-bound) URL is fine —
		uniqueness must not flag the record against itself."""
		doc = self._new_mc(PR1)
		doc.description = "edited"
		doc.save(ignore_permissions=True)  # should not raise
		self.assertEqual(doc.version_control_url, PR1)

	def test_url_frozen_after_submit_edit(self):
		"""The freeze must hold on a SUBMITTED doc too.

		allow_on_submit edits route through update_after_submit, which skips
		validate() — so the guard must also run in before_update_after_submit.
		First post-submit attach (Not Set -> PR1) is allowed; repointing is not.
		"""
		doc = self._new_mc()  # docstatus 0, "Not Set"
		# Fake an approved/submitted MC without before_submit's workflow-file check.
		frappe.db.set_value("Manage Change", doc.name, "docstatus", 1, update_modified=False)
		doc.reload()

		# First post-submit attach: Not Set -> PR1 is fine.
		doc.version_control_url = PR1
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.version_control_url, PR1)

		# Repointing the submitted MC at another PR must be blocked.
		doc.version_control_url = PR2
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_cancelled_record_does_not_block_reuse(self):
		"""A cancelled (docstatus 2) MC's URL is freed for a new binding."""
		# Simulate a cancelled record holding PR1, then bind a fresh MC to PR1.
		doc = self._new_mc(PR1)
		frappe.db.set_value("Manage Change", doc.name, "docstatus", 2, update_modified=False)
		fresh = self._new_mc()
		fresh.version_control_url = PR1
		fresh.save(ignore_permissions=True)  # uniqueness excludes the cancelled one
		self.assertEqual(fresh.version_control_url, PR1)
