# Copyright (c) 2026, Krupal Vora and contributors
# For license information, please see license.txt

"""Guarded overrides for the core Doctype Permissions page (Role Permission Manager).

The page mutates Custom DocPerm via raw SQL for `update`/`remove`/`reset` (only `add`
goes through a document save), so a doc-event guard cannot catch it. Instead we wrap
its four whitelisted mutators via `override_whitelisted_methods`: block under Manage
Access governance, otherwise delegate to the untouched core implementation.

These are reached through `frappe.handler.execute_cmd`, which re-runs `is_whitelisted`
on the override target and binds args from `form_dict` to the signature -- so each
wrapper must be whitelisted and mirror the core signature exactly.
"""

import frappe
from frappe import _
from frappe.core.page.permission_manager import permission_manager as core_pm

from itgc.overrides.access_guard import _managed, _throw


def _guard():
	if _managed():
		_throw(_("Doctype permissions"))


@frappe.whitelist()
def add(parent, role, permlevel):
	_guard()
	return core_pm.add(parent, role, permlevel)


@frappe.whitelist()
def update(doctype, role, permlevel, ptype, value=None, if_owner=0):
	_guard()
	return core_pm.update(doctype, role, permlevel, ptype, value=value, if_owner=if_owner)


@frappe.whitelist()
def remove(doctype, role, permlevel, if_owner=0):
	_guard()
	return core_pm.remove(doctype, role, permlevel, if_owner=if_owner)


@frappe.whitelist()
def reset(doctype):
	_guard()
	return core_pm.reset(doctype)
