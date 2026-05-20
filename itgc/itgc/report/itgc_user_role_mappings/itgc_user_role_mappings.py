import frappe
from frappe import _

# Whitelist: filter value (shown in UI) -> safe SQL column reference.
# Kept here so the column name interpolation below is provably safe.
DATE_FIELDS = {'User Created': 'T1.creation', 'User Modified': 'T1.modified'}
DEFAULT_DATE_FIELD = 'User Created'


def execute(filters=None):
	filters = frappe._dict(filters or {})
	date_field = filters.get("date_field") or DEFAULT_DATE_FIELD
	if date_field not in DATE_FIELDS:
		frappe.throw(_("Invalid date field: {0}").format(date_field))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are required"))

	date_sql = DATE_FIELDS[date_field]
	date_filter = f"{date_sql} BETWEEN %(from_date)s AND %(to_date)s"

	query = """
			SELECT
				T1.name,
				T2.role,
				1 AS cnt
			FROM `tabUser` T1
			LEFT JOIN `tabHas Role` T2 ON T1.name = T2.parent
			WHERE T1.enabled = 1
			  AND {date_filter}
		""".format(date_filter=date_filter)
	data = frappe.db.sql(query, filters, as_dict=True)
	return get_columns(), data


def get_columns():
	return [{'fieldname': 'name', 'label': 'User', 'fieldtype': 'Link', 'options': 'User', 'width': 260}, {'fieldname': 'role', 'label': 'Role', 'fieldtype': 'Link', 'options': 'Role', 'width': 220}, {'fieldname': 'cnt', 'label': 'Count', 'fieldtype': 'Int', 'width': 80}]
