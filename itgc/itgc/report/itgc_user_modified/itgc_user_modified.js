frappe.query_reports["ITGC-User Modified"] = {
	filters: [
		{
			fieldname: "date_field",
			label: __("Date Field"),
			fieldtype: "Select",
			options: "modified\ncreation",
			default: "modified",
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
			fieldname: "role",
			label: __("Modifier Role"),
			fieldtype: "Link",
			options: "Role",
			default: "System Manager",
			description: __("Restrict to users modified by accounts with this role. Leave empty for all."),
		},
	],
};
