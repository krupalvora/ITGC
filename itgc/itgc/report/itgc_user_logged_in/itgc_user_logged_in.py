import frappe
from frappe import _

# Whitelist: filter value (shown in UI) -> safe SQL column reference.
# Kept here so the column name interpolation below is provably safe.
DATE_FIELDS = {'communication_date': 'communication_date', 'creation': 'creation'}
DEFAULT_DATE_FIELD = 'communication_date'


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
				subject,
				operation,
				status,
				communication_date AS date
			FROM `tabActivity Log`
			WHERE {date_filter}
			ORDER BY communication_date DESC
		""".format(date_filter=date_filter)
	data = frappe.db.sql(query, filters, as_dict=True)
	return get_columns(), data


def get_columns():
	return [{'fieldname': 'subject', 'label': 'Subject', 'fieldtype': 'Data', 'width': 300}, {'fieldname': 'operation', 'label': 'Operation', 'fieldtype': 'Data', 'width': 140}, {'fieldname': 'status', 'label': 'Status', 'fieldtype': 'Data', 'width': 120}, {'fieldname': 'date', 'label': 'Date', 'fieldtype': 'Datetime', 'width': 180}]
