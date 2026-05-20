import frappe
from frappe import _

# Whitelist: filter value (shown in UI) -> safe SQL column reference.
# Kept here so the column name interpolation below is provably safe.
DATE_FIELDS = {'PR Created': 'pr.creation', 'PR Posting Date': 'pr.posting_date', 'PR Modified': 'pr.modified', 'Version Modified': 'version.modified'}
DEFAULT_DATE_FIELD = 'PR Created'


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
				version.docname AS purchase_receipt_name,
				pr.creation AS created_on,
				pr.posting_date AS posting_date,
				pr.owner AS created_by,
				version.modified_by AS action_by,
				pr.workflow_state AS workflow_state
			FROM `tabVersion` version
			INNER JOIN `tabPurchase Receipt` pr ON pr.name = version.docname
			WHERE version.ref_doctype = 'Purchase Receipt'
			  AND {date_filter}
			  AND version.data LIKE '%%Complete%%'
			ORDER BY pr.modified ASC
		""".format(date_filter=date_filter)
	data = frappe.db.sql(query, filters, as_dict=True)
	return get_columns(), data


def get_columns():
	return [{'fieldname': 'purchase_receipt_name', 'label': 'Purchase Receipt', 'fieldtype': 'Link', 'options': 'Purchase Receipt', 'width': 200}, {'fieldname': 'created_on', 'label': 'Created On', 'fieldtype': 'Datetime', 'width': 160}, {'fieldname': 'posting_date', 'label': 'Posting Date', 'fieldtype': 'Date', 'width': 120}, {'fieldname': 'created_by', 'label': 'Created By', 'fieldtype': 'Link', 'options': 'User', 'width': 200}, {'fieldname': 'action_by', 'label': 'Action By', 'fieldtype': 'Link', 'options': 'User', 'width': 200}, {'fieldname': 'workflow_state', 'label': 'Workflow State', 'fieldtype': 'Data', 'width': 160}]
