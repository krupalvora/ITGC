import frappe
from frappe.model.document import Document


class ITGCSettings(Document):
	pass


def is_enforcement_enabled() -> bool:
	return bool(
		frappe.db.get_single_value("ITGC Settings", "enable_access_request_enforcement")
	)
