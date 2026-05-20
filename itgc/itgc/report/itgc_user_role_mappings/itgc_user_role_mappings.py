import frappe
from frappe import _

DATE_FIELDS = {"User Created": "T1.creation", "User Modified": "T1.modified"}
DEFAULT_DATE_FIELD = "User Created"


def execute(filters=None):
	filters = frappe._dict(filters or {})

	date_field = filters.get("date_field") or DEFAULT_DATE_FIELD
	if date_field not in DATE_FIELDS:
		frappe.throw(_("Invalid date field: {0}").format(date_field))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are required"))

	conditions = [f"{DATE_FIELDS[date_field]} BETWEEN %(from_date)s AND %(to_date)s"]

	# Default-on. Set to 0 to include disabled users too.
	if filters.get("only_enabled"):
		conditions.append("T1.enabled = 1")

	if filters.get("role"):
		conditions.append("T2.role = %(role)s")

	where = " AND ".join(conditions)
	query = f"""
		SELECT
			T1.name,
			T2.role,
			1 AS cnt
		FROM `tabUser` T1
		LEFT JOIN `tabHas Role` T2 ON T1.name = T2.parent
		WHERE {where}
	"""
	return get_columns(), frappe.db.sql(query, filters, as_dict=True)


def get_columns():
	return [
		{"fieldname": "name", "label": "User", "fieldtype": "Link", "options": "User", "width": 260},
		{"fieldname": "role", "label": "Role", "fieldtype": "Link", "options": "Role", "width": 220},
		{"fieldname": "cnt", "label": "Count", "fieldtype": "Int", "width": 80},
	]
