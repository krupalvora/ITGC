# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ManageAccess(Document):
	def before_insert(self):
		# Requester is always the creating user; the field is read-only in the
		# form but enforce it here too since this is the access system of record.
		if not self.user:
			self.user = frappe.session.user
