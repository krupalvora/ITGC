import frappe
from frappe import _
from frappe.utils import cint

DATE_FIELDS = {
	"User Modified": "u.modified",
	"User Created": "u.creation",
	"Version Modified": "v.modified",
	"Version Created": "v.creation",
}
DEFAULT_DATE_FIELD = "User Modified"
DEFAULT_LIMIT = 2000
MAX_LIMIT = 20000


def execute(filters=None):
	filters = frappe._dict(filters or {})

	date_field = filters.get("date_field") or DEFAULT_DATE_FIELD
	if date_field not in DATE_FIELDS:
		frappe.throw(_("Invalid date field: {0}").format(date_field))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are required"))

	# v.ref_doctype is fixed (this report is User-version specific).
	# Password patterns are excluded for security — never leak tokens to audit output.
	conditions = [
		"v.ref_doctype = 'User'",
		"u.modified != u.creation",
		f"{DATE_FIELDS[date_field]} BETWEEN %(from_date)s AND %(to_date)s",
		"v.data NOT LIKE '%%reset_password_key%%'",
		"v.data NOT LIKE '%%new_password%%'",
		"v.data NOT LIKE '%%last_password_reset_date%%'",
	]

	if filters.get("exclude_role"):
		# Exclude changes made by ANY user who holds the excluded role. Using a
		# NOT IN against the set of users who have the role is correct; a
		# `T2.role != role` join would wrongly keep such users via their *other*
		# role rows.
		conditions.append(
			"v.modified_by NOT IN ("
			"SELECT T2.parent FROM `tabHas Role` T2 "
			"WHERE T2.parenttype = 'User' AND T2.role = %(exclude_role)s)"
		)

	# cint() guarantees an int, so inlining the limit is injection-safe.
	limit = min(cint(filters.get("limit")) or DEFAULT_LIMIT, MAX_LIMIT)

	where = " AND ".join(conditions)
	query = f"""
		SELECT
			1 AS cnt,
			u.name AS id,
			u.email,
			u.username,
			u.full_name,
			u.modified AS modified_on,
			u.modified_by AS modified_by,
			v.docname,
			v.data
		FROM `tabUser` AS u
		INNER JOIN `tabVersion` AS v ON v.docname = u.name
		WHERE {where}
		ORDER BY v.modified DESC
		LIMIT {limit}
	"""
	return get_columns(), frappe.db.sql(query, filters, as_dict=True)


def get_columns():
	return [
		{"fieldname": "cnt", "label": "Count", "fieldtype": "Int", "width": 80},
		{"fieldname": "id", "label": "User", "fieldtype": "Link", "options": "User", "width": 240},
		{"fieldname": "email", "label": "Email", "fieldtype": "Data", "width": 220},
		{"fieldname": "username", "label": "Username", "fieldtype": "Data", "width": 160},
		{"fieldname": "full_name", "label": "Full Name", "fieldtype": "Data", "width": 200},
		{"fieldname": "modified_on", "label": "User Modified On", "fieldtype": "Datetime", "width": 170},
		{"fieldname": "modified_by", "label": "Modified By", "fieldtype": "Link", "options": "User", "width": 200},
		{"fieldname": "docname", "label": "Doc Name", "fieldtype": "Data", "width": 220},
		{"fieldname": "data", "label": "Data", "fieldtype": "Code", "width": 400},
	]
