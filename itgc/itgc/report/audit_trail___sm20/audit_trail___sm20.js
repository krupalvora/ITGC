// Originally authored by Krupal Vora (2025).
// Migrated to the ITGC app.

frappe.query_reports["Audit Trail - SM20"] = {
	filters: [
		{
			fieldname: "user",
			label: __("User"),
			fieldtype: "Link",
			options: "User",
		},
		{
			fieldname: "doctype",
			label: __("Doctype"),
			fieldtype: "Link",
			options: "DocType",
			reqd: 1,
		},
		{
			fieldname: "docname",
			label: __("Docname"),
			fieldtype: "Dynamic Link",
			options: "doctype",
		},
		{
			fieldname: "from_datetime",
			label: __("From Datetime"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_datetime",
			label: __("To Datetime"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "is_post_submission_only",
			label: __("Is Post Submission Only"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "limit",
			label: __("Row Limit"),
			fieldtype: "Int",
			default: 2000,
			description: __("Max Version rows scanned (capped at 20000). Narrow the date range for more."),
		},
	],
};
