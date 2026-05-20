import frappe
from frappe import _

# Whitelist: filter value (shown in UI) -> safe SQL column reference.
# Kept here so the column name interpolation below is provably safe.
DATE_FIELDS = {'modified': 'modified', 'creation': 'creation'}
DEFAULT_DATE_FIELD = 'modified'


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
				name AS id,
				email,
				username,
				full_name,
				modified AS modified_on,
				modified_by,
				1 AS cnt
			FROM `tabUser`
			WHERE {date_filter}
			  AND modified != creation
			  AND modified_by IN (
				  SELECT T1.name FROM `tabUser` T1
				  JOIN `tabHas Role` T2 ON T1.name = T2.parent
				  WHERE T2.role = 'System Manager'
			  )
			ORDER BY modified ASC
		""".format(date_filter=date_filter)
	data = frappe.db.sql(query, filters, as_dict=True)
	return get_columns(), data


def get_columns():
	return [{'fieldname': 'id', 'label': 'User', 'fieldtype': 'Link', 'options': 'User', 'width': 240}, {'fieldname': 'email', 'label': 'Email', 'fieldtype': 'Data', 'width': 220}, {'fieldname': 'username', 'label': 'Username', 'fieldtype': 'Data', 'width': 160}, {'fieldname': 'full_name', 'label': 'Full Name', 'fieldtype': 'Data', 'width': 200}, {'fieldname': 'modified_on', 'label': 'Modified On', 'fieldtype': 'Datetime', 'width': 160}, {'fieldname': 'modified_by', 'label': 'Modified By', 'fieldtype': 'Link', 'options': 'User', 'width': 200}, {'fieldname': 'cnt', 'label': 'Count', 'fieldtype': 'Int', 'width': 80}]
