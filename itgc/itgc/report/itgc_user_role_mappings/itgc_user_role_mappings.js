frappe.query_reports["ITGC-User-Role-Mappings"] = {
	filters: [
		{
			fieldname: "date_field",
			label: __("Date Field"),
			fieldtype: "Select",
			options: "User Created\nUser Modified",
			default: "User Created",
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
			fieldname: "only_enabled",
			label: __("Only Enabled Users"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "role",
			label: __("Role"),
			fieldtype: "Link",
			options: "Role",
			description: __("Restrict to a single role. Leave empty for all."),
		},
	],
};
