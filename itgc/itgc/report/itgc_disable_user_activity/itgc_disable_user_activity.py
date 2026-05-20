import frappe
from frappe import _

# Whitelist: filter value (shown in UI) -> safe SQL column reference.
# Kept here so the column name interpolation below is provably safe.
DATE_FIELDS = {'creation': 'creation'}
DEFAULT_DATE_FIELD = 'creation'


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
				user AS user_email,
				MAX(creation) AS last_activity_date
			FROM `tabAccess Log`
			WHERE user IN (
				'rahul.w@solarsquare.in',
				'piyush.g@solarsquare.in',
				'pankaj.k@solarsquare.in',
				'rajeshwar.d@solarsquare.in',
				'kamal.g@solarsquare.in',
				'sachin.pagaria@solarsquare.in'
			)
			AND {date_filter}
			GROUP BY user
		""".format(date_filter=date_filter)
	data = frappe.db.sql(query, filters, as_dict=True)
	return get_columns(), data


def get_columns():
	return [{'fieldname': 'user_email', 'label': 'User', 'fieldtype': 'Link', 'options': 'User', 'width': 260}, {'fieldname': 'last_activity_date', 'label': 'Last Activity Date', 'fieldtype': 'Datetime', 'width': 200}]
