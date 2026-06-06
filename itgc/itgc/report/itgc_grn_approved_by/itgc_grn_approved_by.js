frappe.query_reports["ITGC-GRN Approved_By"] = {
	filters: [
		{
			fieldname: "date_field",
			label: __("Date Field"),
			fieldtype: "Select",
			options: "PR Created\nPR Posting Date\nPR Modified\nVersion Modified",
			default: "PR Created",
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "workflow_state_keyword",
			label: __("Workflow State Keyword"),
			fieldtype: "Data",
			default: "Complete",
			description: __("Matched against the version data via LIKE. Leave empty to skip."),
		},
		{
			fieldname: "limit",
			label: __("Row Limit"),
			fieldtype: "Int",
			default: 2000,
			description: __("Max rows returned (capped at 20000). Narrow the date range for more."),
		},
	],
};
