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
		filter_protected_roles(frm);
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

		// Types that target someone else (or no user) -> blank, so the requester picks
		// the subject. Create/Modify Role Profile act on the profile itself; New User /
		// Disable User and the revoke types are raised FOR another user. The remaining
		// self-oriented types (Request Role / Request Role Profile) default to the
		// current user (still editable).
		const not_self = [
			"New User",
			"Disable User",
			"Change Doctype Permission",
			"Create Role Profile",
			"Modify Role Profile",
			"Revoke Role",
			"Revoke Role Profile",
		];
		if (not_self.includes(frm.doc.request_type)) {
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
	// Gate request types by the requester's roles. System Manager sees everything.
	const is_system_manager = frappe.user_roles.includes("System Manager");
	if (is_system_manager) {
		return;
	}

	// "Change Doctype Permission" and the Role Profile management types are
	// System-Manager-only actions.
	let hidden = ["Change Doctype Permission", "Create Role Profile", "Modify Role Profile"];

	// Revoke / Disable act on another user's access — only ITGC Access Managers
	// may raise them. The server re-enforces this in validate_request.
	if (!frappe.user_roles.includes("ITGC Access Manager")) {
		hidden = hidden.concat(["Revoke Role", "Revoke Role Profile", "Disable User"]);
	}

	const options = (frm.fields_dict.request_type.df.options || "")
		.split("\n")
		.filter((opt) => !hidden.includes(opt));
	frm.set_df_property("request_type", "options", options.join("\n"));
}

function filter_protected_roles(frm) {
	// Hide only FULLY-RESTRICTED roles (e.g. System Manager) from the Role pickers
	// unless the user may grant them (Sudo User / System Manager). Approval-Gated
	// roles (e.g. ITGC Access Manager) stay visible so anyone can request them — the
	// grant is gated server-side at approval time. UX only; the server re-enforces.
	frappe.call({
		method: "itgc.itgc.doctype.manage_access.manage_access.get_protected_role_context",
		callback(r) {
			const ctx = r.message || {};
			const hidden = ctx.hidden_roles || [];
			const role_query =
				ctx.may_grant || !hidden.length
					? () => ({})
					: () => ({ filters: { name: ["not in", hidden] } });
			frm.set_query("role", role_query);
			frm.set_query("perm_role", role_query);
		},
	});
}

function set_request_for_query(frm) {
	frm.set_query("request_for", () => {
		// "New User" requests target not-yet-onboarded users — defined solely by the
		// absence of a Role Profile, regardless of user_type (self-signups land as
		// Website Users). role_profile_name is a permlevel-1 field on User, so a
		// client-side filter returns nothing for a requester without permlevel-1
		// access (hiding the new user). Evaluate that rule server-side instead.
		if (frm.doc.request_type === "New User") {
			return {
				query: "itgc.itgc.doctype.manage_access.manage_access.users_without_role_profile",
			};
		}
		// All other request types modify access of users already in the system,
		// so they only target enabled System Users.
		return { filters: { enabled: 1, user_type: "System User" } };
	});
}
