# Copyright (c) 2026, Krupal Vora and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from itgc.overrides.user import restrict_signup_domain

ALLOWED = "solarsquare.in"


class TestSignupDomainRestriction(FrappeTestCase):
	"""Public self sign-up must be restricted to the ITGC Settings allow-list.

	The control is keyed on a Guest session (a logged-out self sign-up). Config is
	written directly to the DB (flag via set_single_value, domain rows via db_insert)
	to avoid triggering the ITGC Settings on_update workflow sync — the same pattern
	the access-guard tests use. FrappeTestCase rolls the transaction back afterwards.
	"""

	def setUp(self):
		frappe.db.set_single_value("ITGC Settings", "restrict_signup_to_domains", 1)
		self._set_domains([ALLOWED])
		frappe.set_user("Guest")

	def tearDown(self):
		frappe.set_user("Administrator")

	def _set_domains(self, domains):
		frappe.db.delete("ITGC Signup Domain", {"parenttype": "ITGC Settings"})
		for d in domains:
			frappe.get_doc(
				{
					"doctype": "ITGC Signup Domain",
					"parenttype": "ITGC Settings",
					"parent": "ITGC Settings",
					"parentfield": "signup_allowed_domains",
					"domain": d,
				}
			).db_insert()

	def _signup_doc(self, email):
		"""An un-inserted User as the public sign-up path would build it."""
		return frappe.get_doc({"doctype": "User", "email": email, "first_name": "ITGC Test"})

	# ----------------------------------------------------- core gate
	def test_disallowed_domain_is_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			restrict_signup_domain(self._signup_doc("intruder@gmail.com"))

	def test_allowed_domain_passes(self):
		restrict_signup_domain(self._signup_doc("staff@solarsquare.in"))  # must not raise

	def test_match_is_case_insensitive(self):
		restrict_signup_domain(self._signup_doc("Staff@SolarSquare.IN"))  # must not raise

	def test_subdomain_is_not_allowed_implicitly(self):
		"""A sub-domain must be listed explicitly; it is not covered by the parent."""
		with self.assertRaises(frappe.ValidationError):
			restrict_signup_domain(self._signup_doc("staff@mail.solarsquare.in"))

	# ----------------------------------------------------- fail-secure / toggles
	def test_fail_secure_when_enabled_but_no_domains(self):
		"""Control ON with an empty list blocks ALL signups — never a silent no-op."""
		self._set_domains([])
		with self.assertRaises(frappe.ValidationError):
			restrict_signup_domain(self._signup_doc("staff@solarsquare.in"))

	def test_exempt_when_control_off(self):
		frappe.db.set_single_value("ITGC Settings", "restrict_signup_to_domains", 0)
		restrict_signup_domain(self._signup_doc("intruder@gmail.com"))  # off -> must not raise

	# ----------------------------------------------------- scope: only self sign-up
	def test_admin_created_user_is_exempt(self):
		"""A logged-in (non-Guest) creator is the governed/admin path — never gated,
		even for an off-list domain."""
		frappe.set_user("Administrator")
		restrict_signup_domain(self._signup_doc("contractor@gmail.com"))  # must not raise

	# ----------------------------------------------------- end-to-end via before_insert
	def test_insert_blocked_end_to_end(self):
		email = "itgc-signup-block@gmail.com"
		frappe.set_user("Administrator")
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.set_user("Guest")
		doc = self._signup_doc(email)
		doc.flags.no_welcome_mail = True
		doc.send_welcome_email = 0
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_insert_allowed_end_to_end(self):
		email = "itgc-signup-ok@solarsquare.in"
		frappe.set_user("Administrator")
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.set_user("Guest")
		doc = self._signup_doc(email)
		doc.flags.no_welcome_mail = True
		doc.send_welcome_email = 0
		doc.insert(ignore_permissions=True)  # must not raise
		self.assertTrue(frappe.db.exists("User", email))
