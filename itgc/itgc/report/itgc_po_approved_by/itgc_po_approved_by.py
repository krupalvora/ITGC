import frappe
from frappe import _

DATE_FIELDS = {
	"PO Created": "po.creation",
	"PO Transaction Date": "po.transaction_date",
	"PO Modified": "po.modified",
	"Version Modified": "version.modified",
}
DEFAULT_DATE_FIELD = "PO Created"


def execute(filters=None):
	filters = frappe._dict(filters or {})

	date_field = filters.get("date_field") or DEFAULT_DATE_FIELD
	if date_field not in DATE_FIELDS:
		frappe.throw(_("Invalid date field: {0}").format(date_field))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are required"))

	# version.ref_doctype is fixed because this report is specific to Purchase Order.
	conditions = [
		"version.ref_doctype = 'Purchase Order'",
		f"{DATE_FIELDS[date_field]} BETWEEN %(from_date)s AND %(to_date)s",
	]

	if filters.get("workflow_state_keyword"):
		conditions.append("version.data LIKE %(workflow_state_pattern)s")
		filters["workflow_state_pattern"] = f"%{filters['workflow_state_keyword']}%"

	where = " AND ".join(conditions)
	query = f"""
		SELECT
			version.docname AS purchase_order_name,
			po.creation AS created_on,
			po.transaction_date AS transaction_date,
			po.owner AS created_by,
			version.modified_by AS action_by,
			po.workflow_state AS workflow_state
		FROM `tabVersion` version
		INNER JOIN `tabPurchase Order` po ON po.name = version.docname
		WHERE {where}
		ORDER BY po.modified ASC
	"""
	return get_columns(), frappe.db.sql(query, filters, as_dict=True)


def get_columns():
	return [
		{"fieldname": "purchase_order_name", "label": "Purchase Order", "fieldtype": "Link", "options": "Purchase Order", "width": 200},
		{"fieldname": "created_on", "label": "Created On", "fieldtype": "Datetime", "width": 160},
		{"fieldname": "transaction_date", "label": "Transaction Date", "fieldtype": "Date", "width": 140},
		{"fieldname": "created_by", "label": "Created By", "fieldtype": "Link", "options": "User", "width": 200},
		{"fieldname": "action_by", "label": "Action By", "fieldtype": "Link", "options": "User", "width": 200},
		{"fieldname": "workflow_state", "label": "Workflow State", "fieldtype": "Data", "width": 160},
	]
