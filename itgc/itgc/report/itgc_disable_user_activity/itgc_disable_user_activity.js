frappe.query_reports["ITGC-Disable-User-Activity"] = {
	filters: [
		{
			fieldname: "date_field",
			label: __("Date Field"),
			fieldtype: "Select",
			options: "creation",
			default: "creation",
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
			fieldname: "users",
			label: __("Users (overrides 'disabled users only')"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				return frappe.db.get_link_options("User", txt);
			},
		},
	],
};
