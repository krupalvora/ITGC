# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

ACCESS_MANAGER_ROLE = "ITGC Access Manager"


class ITGCSettings(Document):
	def validate(self):
		self.validate_sudo_user_for_manage_access()

	def validate_sudo_user_for_manage_access(self):
		"""Fail-secure: Manage Access cannot be ON without a valid, enabled Sudo User.

		The Sudo User is the break-glass approver for protected-role grants
		(`ManageAccess._protected_role_approvers`). Without a usable one, a
		protected-role request can be raised but never approved — it stalls with no
		eligible approver and the only recovery is the `bench console` break-glass.
		Block that misconfiguration at save time rather than discovering it when a
		grant is stuck. Enforced whenever the flag is on (not just on the enabling
		transition) so the settings can never be saved in an inconsistent state.
		"""
		if not self.enable_manage_access:
			return

		if not self.sudo_user:
			frappe.throw(
				_(
					"Set a Sudo User before enabling Manage Access. The Sudo User is the "
					"break-glass approver for protected-role grants; without it such "
					"requests can be raised but never approved."
				),
				title=_("Sudo User required"),
			)

		enabled = frappe.db.get_value("User", self.sudo_user, "enabled")
		if enabled is None:
			frappe.throw(
				_("The Sudo User {0} does not exist.").format(frappe.bold(self.sudo_user)),
				title=_("Sudo User required"),
			)
		if not enabled:
			frappe.throw(
				_(
					"The Sudo User {0} is disabled. Choose an enabled user before enabling "
					"Manage Access, or it will not be able to approve protected-role grants."
				).format(frappe.bold(self.sudo_user)),
				title=_("Sudo User required"),
			)

	def on_update(self):
		self.sync_access_manager_role()
		self.sync_sudo_user_role()
		self.sync_change_management_workflow()
		self.sync_manage_access_workflow()

	def sync_sudo_user_role(self):
		"""Ensure the Sudo User can operate the Manage Access approval workflow.

		Protected-role approvals go through the workflow whose 'allowed' role is
		'ITGC Access Manager' (Frappe checks the role strictly — even a System
		Manager cannot act on a transition without it). The Sudo User is the
		designated approver for protected-role grants, so it is granted that role
		here.

		Grant-only: we never strip it on change, to avoid removing the role from a
		user who holds it for another reason (e.g. they are also a department Access
		Manager). The grant self-heals on every User save via
		itgc.overrides.user.ensure_access_manager_role.
		"""
		if not self.sudo_user or not frappe.db.exists("User", self.sudo_user):
			return
		if ACCESS_MANAGER_ROLE in frappe.get_roles(self.sudo_user):
			return

		frappe.flags.in_manage_access = True
		try:
			frappe.flags.itgc_access_manager = self.sudo_user
			try:
				frappe.get_doc("User", self.sudo_user).add_roles(ACCESS_MANAGER_ROLE)
			finally:
				frappe.flags.itgc_access_manager = False
		finally:
			frappe.flags.in_manage_access = False

	def sync_manage_access_workflow(self):
		"""Keep the Manage Access approval workflow's active state in sync.

		The single "Enable Manage Access" flag drives both the access-master
		lockdown (see itgc.overrides.access_guard) and this maker-checker approval
		workflow, so turning the feature on routes every request through approval.

		Enforced on every save (not just on change) so the workflow and flag are
		self-healing if they ever drift apart; the call is a no-op when in sync.
		"""
		from itgc.install import set_manage_access_workflow_active

		set_manage_access_workflow_active(bool(self.enable_manage_access))

	def sync_change_management_workflow(self):
		"""Keep the Manage Change approval workflow's active state in sync.

		The workflow ships disabled with the app; the "Enable Change Management"
		flag is what turns the gated approval flow on (and off again).

		We enforce the workflow state on *every* save rather than only when the
		flag changes. That makes it self-healing: if the workflow and flag ever
		drift apart (e.g. the workflow was toggled by hand, or the flag was set
		while this hook wasn't deployed), the next Settings save reconciles them.
		`set_manage_change_workflow_active` is a no-op when already in sync.
		"""
		from itgc.install import set_manage_change_workflow_active

		set_manage_change_workflow_active(bool(self.enable_change_management))

	def sync_access_manager_role(self):
		"""Keep the 'ITGC Access Manager' role in sync with the selected access_manager.

		Grants the role to the newly selected user and removes it from the
		previously selected user when the field changes. The grant is also
		re-asserted on every User save by `itgc.overrides.user`, which is what
		makes it stick for users that have a Role Profile (Frappe core wipes
		ad-hoc roles during profile sync).
		"""
		previous = (self.get_doc_before_save() or {}).get("access_manager")
		current = self.access_manager
		if previous == current:
			return

		# Changing the Access Manager here IS a sanctioned access change, but it
		# saves the User doc (add/remove_roles) — which the access_guard lockdown
		# would otherwise block once Manage Access is enabled. Mark this as the
		# Manage Access writer so the guard lets the role sync through, exactly as
		# the Manage Access apply path does.
		frappe.flags.in_manage_access = True
		try:
			if previous and frappe.db.exists("User", previous):
				frappe.get_doc("User", previous).remove_roles(ACCESS_MANAGER_ROLE)

			if current and frappe.db.exists("User", current):
				# Pass the new manager explicitly so the User validate hook re-asserts
				# the role after Frappe's role-profile sync strips it on save.
				frappe.flags.itgc_access_manager = current
				try:
					frappe.get_doc("User", current).add_roles(ACCESS_MANAGER_ROLE)
				finally:
					frappe.flags.itgc_access_manager = False
		finally:
			frappe.flags.in_manage_access = False


@frappe.whitelist()
def get_access_manager_role_users():
	"""Return users who currently hold the 'ITGC Access Manager' role.

	Read live from `Has Role` so the list always reflects the true state,
	regardless of where the role was assigned/removed.
	"""
	user_ids = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ACCESS_MANAGER_ROLE},
		pluck="parent",
	)
	if not user_ids:
		return []

	return frappe.get_all(
		"User",
		filters={"name": ["in", user_ids]},
		fields=["name as user", "full_name", "enabled"],
		order_by="enabled desc, full_name asc",
	)
