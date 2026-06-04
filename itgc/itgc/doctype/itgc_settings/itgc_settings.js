// Copyright (c) 2026, Krupal Vora and contributors
// For license information, please see license.txt

frappe.ui.form.on("ITGC Settings", {
	refresh(frm) {
		render_access_manager_role_holders(frm);
	},
	enable_manage_access(frm) {
		render_access_manager_role_holders(frm);
	},
	access_manager(frm) {
		// re-fetch after a save so the list reflects the newly synced role
		if (!frm.is_dirty()) {
			render_access_manager_role_holders(frm);
		}
	},
});

function render_access_manager_role_holders(frm) {
	const wrapper = frm.get_field("access_manager_role_holders").$wrapper;

	if (!frm.doc.enable_manage_access) {
		wrapper.empty();
		return;
	}

	frappe.call({
		method: "itgc.itgc.doctype.itgc_settings.itgc_settings.get_access_manager_role_users",
		callback(r) {
			const users = r.message || [];
			wrapper.empty();

			if (!users.length) {
				wrapper.html(
					`<div class="text-muted" style="padding:8px 0;">
						${__("No users currently hold the \"ITGC Access Manager\" role.")}
					</div>`
				);
				return;
			}

			const rows = users
				.map((u) => {
					const status = u.enabled
						? `<span class="indicator-pill green">${__("Enabled")}</span>`
						: `<span class="indicator-pill red">${__("Disabled")}</span>`;
					const name = frappe.utils.escape_html(u.full_name || u.user);
					const email = frappe.utils.escape_html(u.user);
					return `<tr>
						<td><a href="/app/user/${encodeURIComponent(u.user)}">${name}</a></td>
						<td class="text-muted">${email}</td>
						<td>${status}</td>
					</tr>`;
				})
				.join("");

			wrapper.html(`
				<table class="table table-bordered" style="margin-top:8px;">
					<thead>
						<tr>
							<th>${__("User")}</th>
							<th>${__("Email")}</th>
							<th>${__("Status")}</th>
						</tr>
					</thead>
					<tbody>${rows}</tbody>
				</table>
			`);
		},
	});
}
