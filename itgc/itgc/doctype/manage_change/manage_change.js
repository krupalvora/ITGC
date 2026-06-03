// Copyright (c) 2026, Krupal Vora and contributors
// For license information, please see license.txt

frappe.ui.form.on("Manage Change", {
	onload(frm) {
		// Populate `erp_app` with the list of apps currently installed on this site.
		// `frappe.boot.versions` is `{app_name: version}` for every installed app —
		// pre-loaded at desk boot, so no server call needed.
		const apps = Object.keys(frappe.boot.versions || {}).sort();
		if (apps.length) {
			frm.set_df_property("erp_app", "options", ["", ...apps].join("\n"));
		}
	},
});
