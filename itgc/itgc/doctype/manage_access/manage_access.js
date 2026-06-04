// Copyright (c) 2026, Krupal Vora and contributors
// For license information, please see license.txt

frappe.ui.form.on("Manage Access", {
	onload(frm) {
		// Default the requester to the current session user on new records.
		if (frm.is_new() && !frm.doc.user) {
			frm.set_value("user", frappe.session.user);
		}
	},

	refresh(frm) {
		set_request_for_query(frm);
	},

	request_type(frm) {
		// Clear fields that no longer apply so hidden values don't get submitted.
		frm.set_value("role", null);
		frm.set_value("role_profile", null);

		// New User / Disable User act on someone else -> blank. Every other type
		// defaults to the current user (still editable).
		if (["New User", "Disable User"].includes(frm.doc.request_type)) {
			frm.set_value("request_for", null);
		} else if (frm.doc.request_type) {
			frm.set_value("request_for", frappe.session.user);
		} else {
			frm.set_value("request_for", null);
		}
	},
});

function set_request_for_query(frm) {
	frm.set_query("request_for", () => {
		// "New User" requests may only target users that have no Role Profile yet.
		// Other types (e.g. Disable User) may target any user.
		if (frm.doc.request_type === "New User") {
			return { filters: { role_profile_name: ["is", "not set"] } };
		}
		return {};
	});
}
