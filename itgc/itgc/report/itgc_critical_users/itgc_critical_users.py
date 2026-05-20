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

	conditions = [f"{DATE_FIELDS[date_field]} BETWEEN %(from_date)s AND %(to_date)s"]

	if filters.get("role"):
		conditions.append(
			"modified_by IN ("
			"SELECT T1.name FROM `tabUser` T1 "
			"JOIN `tabHas Role` T2 ON T1.name = T2.parent "
			"WHERE T2.role = %(role)s)"
		)

	excluded = filters.get("excluded_users") or []
	if excluded:
		escaped = ", ".join(frappe.db.escape(u) for u in excluded)
		conditions.append(f"modified_by NOT IN ({escaped})")

	where = " AND ".join(conditions)
	query = f"""
		SELECT name, creation, modified, modified_by, docname, ref_doctype, data
		FROM `tabVersion`
		WHERE {where}
		ORDER BY modified, modified_by DESC
	"""
	return get_columns(), frappe.db.sql(query, filters, as_dict=True)


def get_columns():
	return [
		{"fieldname": "name", "label": "Version", "fieldtype": "Data", "width": 220},
		{"fieldname": "creation", "label": "Created On", "fieldtype": "Datetime", "width": 160},
		{"fieldname": "modified", "label": "Modified On", "fieldtype": "Datetime", "width": 160},
		{"fieldname": "modified_by", "label": "Modified By", "fieldtype": "Link", "options": "User", "width": 200},
		{"fieldname": "docname", "label": "Doc Name", "fieldtype": "Data", "width": 220},
		{"fieldname": "ref_doctype", "label": "Ref DocType", "fieldtype": "Link", "options": "DocType", "width": 160},
		{"fieldname": "data", "label": "Data", "fieldtype": "Code", "width": 400},
	]
