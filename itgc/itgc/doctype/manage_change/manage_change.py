# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import now_datetime


class ManageChange(Document):
	def autoname(self):
		if self.ticket_id:
			self.name = self.ticket_id
		else:
			formatted_date = now_datetime().strftime("%Y-%m-%d")
			self.name = make_autoname(f"MC-{formatted_date}-.##")
