import frappe
from frappe import _

DATE_FIELDS = {"creation": "creation"}
DEFAULT_DATE_FIELD = "creation"


def execute(filters=None):
	filters = frappe._dict(filters or {})

	date_field = filters.get("date_field") or DEFAULT_DATE_FIELD
	if date_field not in DATE_FIELDS:
		frappe.throw(_("Invalid date field: {0}").format(date_field))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are required"))

	conditions = [f"{DATE_FIELDS[date_field]} BETWEEN %(from_date)s AND %(to_date)s"]

	users = filters.get("users") or []
	if users:
		escaped = ", ".join(frappe.db.escape(u) for u in users)
		conditions.append(f"user IN ({escaped})")
	else:
		# Default: every currently-disabled user.
		conditions.append("user IN (SELECT name FROM `tabUser` WHERE enabled = 0)")

	where = " AND ".join(conditions)
	query = f"""
		SELECT
			user AS user_email,
			MAX(creation) AS last_activity_date
		FROM `tabAccess Log`
		WHERE {where}
		GROUP BY user
	"""
	return get_columns(), frappe.db.sql(query, filters, as_dict=True)


def get_columns():
	return [
		{"fieldname": "user_email", "label": "User", "fieldtype": "Link", "options": "User", "width": 260},
		{"fieldname": "last_activity_date", "label": "Last Activity Date", "fieldtype": "Datetime", "width": 200},
	]
