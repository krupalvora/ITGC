import frappe

from itgc.itgc.doctype.itgc_settings.itgc_settings import is_enforcement_enabled


def validate(doc, method):
	"""Block modification of existing Role Profile records when ITGC enforcement is on.
	New profiles can still be created; bypassed when called from Access Request flow."""
	if not is_enforcement_enabled():
		return
	if doc.flags.get("from_access_request"):
		return
	if doc.is_new():
		return

	frappe.throw(
		"Role Profile changes are blocked by ITGC enforcement. "
		"Raise an Access Request to modify role assignments.",
		title="Access Request Required",
	)
