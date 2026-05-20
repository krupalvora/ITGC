// Originally authored by Krupal Vora (2025).
// Migrated to the ITGC app.

frappe.ui.form.on("Access Request", {
	setup(frm) {
		// User-permission rows: only let the approver pick reports of themselves.
		frm.set_query("user", "user_permissions", () => ({
			query: "itgc.itgc.doctype.access_request.access_request.get_filtered_user",
		}));
	},

	refresh(frm) {
		// New requests default the raiser to the current user.
		if (frm.is_new()) {
			frm.set_value("requested_by", frappe.session.user);
		}
	},

	request_type(frm) {
		// "New User" requests target a Website User waiting to be enabled;
		// other types target an existing System User.
		if (frm.doc.request_type === "New User") {
			frm.set_query("target_user", () => ({
				query: "itgc.api.user.get_guest_user_list",
			}));
		} else {
			frm.set_query("target_user", () => ({}));
		}
	},
});
