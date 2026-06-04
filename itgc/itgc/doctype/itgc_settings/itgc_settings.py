# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

ACCESS_MANAGER_ROLE = "ITGC Access Manager"


class ITGCSettings(Document):
	def on_update(self):
		self.sync_access_manager_role()

	def sync_access_manager_role(self):
		"""Keep the 'ITGC Access Manager' role in sync with the selected access_manager.

		Grants the role to the newly selected user and removes it from the
		previously selected user when the field changes.
		"""
		previous = (self.get_doc_before_save() or {}).get("access_manager")
		current = self.access_manager

		if previous == current:
			return

		if previous and frappe.db.exists("User", previous):
			frappe.get_doc("User", previous).remove_roles(ACCESS_MANAGER_ROLE)

		if current and frappe.db.exists("User", current):
			frappe.get_doc("User", current).add_roles(ACCESS_MANAGER_ROLE)
