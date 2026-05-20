import frappe
from frappe import _

DATE_FIELDS = {"modified": "modified", "creation": "creation"}
DEFAULT_DATE_FIELD = "modified"


def execute(filters=None):
	filters = frappe._dict(filters or {})

	date_field = filters.get("date_field") or DEFAULT_DATE_FIELD
	if date_field not in DATE_FIELDS:
		frappe.throw(_("Invalid date field: {0}").format(date_field))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are required"))

	# `modified != creation` is intrinsic — the report is about post-creation edits.
	conditions = [
		f"{DATE_FIELDS[date_field]} BETWEEN %(from_date)s AND %(to_date)s",
		"modified != creation",
	]

	if filters.get("role"):
		conditions.append(
			"modified_by IN ("
			"SELECT T1.name FROM `tabUser` T1 "
			"JOIN `tabHas Role` T2 ON T1.name = T2.parent "
			"WHERE T2.role = %(role)s)"
		)

	where = " AND ".join(conditions)
	query = f"""
		SELECT
			name AS id,
			email,
			username,
			full_name,
			modified AS modified_on,
			modified_by,
			1 AS cnt
		FROM `tabUser`
		WHERE {where}
		ORDER BY modified ASC
	"""
	return get_columns(), frappe.db.sql(query, filters, as_dict=True)


def get_columns():
	return [
		{"fieldname": "id", "label": "User", "fieldtype": "Link", "options": "User", "width": 240},
		{"fieldname": "email", "label": "Email", "fieldtype": "Data", "width": 220},
		{"fieldname": "username", "label": "Username", "fieldtype": "Data", "width": 160},
		{"fieldname": "full_name", "label": "Full Name", "fieldtype": "Data", "width": 200},
		{"fieldname": "modified_on", "label": "Modified On", "fieldtype": "Datetime", "width": 160},
		{"fieldname": "modified_by", "label": "Modified By", "fieldtype": "Link", "options": "User", "width": 200},
		{"fieldname": "cnt", "label": "Count", "fieldtype": "Int", "width": 80},
	]
