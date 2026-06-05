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
		restrict_request_type_options(frm);
	},

	document_type(frm) {
		fetch_current_perms(frm);
	},

	perm_role(frm) {
		fetch_current_perms(frm);
	},

	permission_level(frm) {
		fetch_current_perms(frm);
	},

	request_type(frm) {
		// Clear fields that no longer apply so hidden values don't get submitted.
		frm.set_value("role", null);
		frm.set_value("role_profile", null);

		// No-subject types (New User, Disable User, Change Doctype Permission) -> blank.
		// The remaining self-oriented types default to the current user (still editable).
		if (["New User", "Disable User", "Change Doctype Permission"].includes(frm.doc.request_type)) {
			frm.set_value("request_for", null);
		} else if (frm.doc.request_type) {
			frm.set_value("request_for", frappe.session.user);
		} else {
			frm.set_value("request_for", null);
		}
	},
});

function fetch_current_perms(frm) {
	// Pre-fill the permission checkboxes with the role's CURRENT permissions on the
	// doctype, so the admin edits from the real state (and the before-snapshot is
	// captured on submit). Only in doc-perm mode, only on a draft.
	if (frm.doc.request_type !== "Change Doctype Permission" || frm.doc.docstatus !== 0) {
		return;
	}
	if (!frm.doc.document_type || !frm.doc.perm_role) {
		return;
	}
	frappe.call({
		method: "itgc.itgc.doctype.manage_access.manage_access.get_current_doc_perm",
		args: {
			document_type: frm.doc.document_type,
			perm_role: frm.doc.perm_role,
			permission_level: frm.doc.permission_level || "0",
		},
		callback(r) {
			if (!r.message) {
				return;
			}
			Object.keys(r.message).forEach((field) => frm.set_value(field, r.message[field]));
		},
	});
}

function restrict_request_type_options(frm) {
	// "Change Doctype Permission" is a System-Manager-only action.
	if (frappe.user_roles.includes("System Manager")) {
		return;
	}
	const options = (frm.fields_dict.request_type.df.options || "")
		.split("\n")
		.filter((opt) => opt !== "Change Doctype Permission");
	frm.set_df_property("request_type", "options", options.join("\n"));
}

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
