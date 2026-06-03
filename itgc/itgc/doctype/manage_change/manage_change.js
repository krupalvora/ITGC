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

	before_submit(frm) {
		// Block submit if the target app's repo is missing the workflow files.
		// Offer to copy them from the canonical source (solar_square) in a popup.
		if (!frm.doc.erp_app) return;

		return frappe.call({
			method: "itgc.itgc.doctype.manage_change.manage_change.check_workflow_files",
			args: { erp_app: frm.doc.erp_app },
		}).then((r) => {
			const status = r.message || {};
			if (status.ok) return;  // files present — let submit proceed.

			const missing_html = (status.missing || [])
				.map((m) => `<code>${frappe.utils.escape_html(m)}</code>`)
				.join("<br>");
			const app_html = `<code>${frappe.utils.escape_html(frm.doc.erp_app)}</code>`;

			frappe.msgprint({
				title: __("Workflow Files Missing"),
				indicator: "red",
				message:
					`App ${app_html} is missing required GitHub workflow file(s):<br><br>` +
					`${missing_html}<br><br>` +
					`Click <b>Add Files</b> to copy them from <code>solar_square</code> into ${app_html}'s repo. ` +
					`You'll still need to <code>git add</code>, <code>commit</code>, and <code>push</code> ` +
					`them before the GitHub check can pass.`,
				primary_action: {
					label: __("Add Files"),
					action() {
						frappe.call({
							method: "itgc.itgc.doctype.manage_change.manage_change.copy_workflow_files",
							args: { target_app: frm.doc.erp_app },
							freeze: true,
							freeze_message: __("Copying workflow files…"),
						}).then((copy_r) => {
							const data = copy_r.message || {};
							const copied = data.copied || [];
							const skipped = data.skipped_existing || [];
							const missing_src = data.skipped_missing_source || [];

							const lines = [];
							if (copied.length) {
								lines.push(
									__("Copied:") +
										"<br>" +
										copied.map((f) => `<code>${frappe.utils.escape_html(f)}</code>`).join("<br>")
								);
							}
							if (skipped.length) {
								lines.push(
									__("Already present (skipped):") +
										"<br>" +
										skipped.map((f) => `<code>${frappe.utils.escape_html(f)}</code>`).join("<br>")
								);
							}
							if (missing_src.length) {
								lines.push(
									`<span class="text-danger">${__("Missing in source — could not copy:")}</span><br>` +
										missing_src.map((f) => `<code>${frappe.utils.escape_html(f)}</code>`).join("<br>")
								);
							}
							lines.push("");
							lines.push(
								__("Next:") +
									` <code>cd apps/${frappe.utils.escape_html(frm.doc.erp_app)} && git add .github && git commit -m "Add Manage Change workflows" && git push</code>`
							);
							lines.push(__("Then re-submit this Manage Change."));

							frappe.hide_msgprint();
							frappe.msgprint({
								title: __("Files Added"),
								indicator: copied.length ? "green" : "orange",
								message: lines.join("<br>"),
							});
						});
					},
				},
			});

			// Block the submit; dev needs to push the files first, then re-submit.
			frappe.validated = false;
		});
	},
});
