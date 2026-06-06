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

	target_role_profile(frm) {
		prefill_profile_roles(frm);
	},

	request_type(frm) {
		// Clear fields that no longer apply so hidden values don't get submitted.
		frm.set_value("role", null);
		frm.set_value("role_profile", null);
		frm.set_value("new_role_profile_name", null);
		frm.set_value("target_role_profile", null);
		frm.clear_table("profile_roles");
		frm.refresh_field("profile_roles");

		// No-subject types -> blank. Create/Modify Role Profile act on the profile
		// itself, not a user. The remaining self-oriented types default to the current
		// user (still editable).
		const no_subject = [
			"New User",
			"Disable User",
			"Change Doctype Permission",
			"Create Role Profile",
			"Modify Role Profile",
		];
		if (no_subject.includes(frm.doc.request_type)) {
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

function prefill_profile_roles(frm) {
	// On selecting an existing Role Profile to modify, load its current roles into the
	// table so the admin edits from the real state (submit replaces the profile's roles).
	if (frm.doc.request_type !== "Modify Role Profile" || frm.doc.docstatus !== 0) {
		return;
	}
	if (!frm.doc.target_role_profile) {
		frm.clear_table("profile_roles");
		frm.refresh_field("profile_roles");
		return;
	}
	frappe.call({
		method: "itgc.itgc.doctype.manage_access.manage_access.get_role_profile_roles",
		args: { role_profile: frm.doc.target_role_profile },
		callback(r) {
			if (!r.message) {
				return;
			}
			frm.clear_table("profile_roles");
			r.message.forEach((row) => {
				frm.add_child("profile_roles", { role: row.role });
			});
			frm.refresh_field("profile_roles");
		},
	});
}

function restrict_request_type_options(frm) {
	// "Change Doctype Permission" and the Role Profile management types are
	// System-Manager-only actions.
	if (frappe.user_roles.includes("System Manager")) {
		return;
	}
	const sm_only = ["Change Doctype Permission", "Create Role Profile", "Modify Role Profile"];
	const options = (frm.fields_dict.request_type.df.options || "")
		.split("\n")
		.filter((opt) => !sm_only.includes(opt));
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
