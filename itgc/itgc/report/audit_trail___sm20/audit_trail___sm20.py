import frappe
from frappe.query_builder import DocType
from pypika import Order, Query
from frappe.utils import cint, get_datetime
from frappe.core.doctype.version.version import get_diff

# Cap on the number of Version rows scanned/parsed per run. Each row is JSON the
# report parses in Python, so an unbounded fetch over `tabVersion` can blow up
# memory; this keeps the report responsive. Override via the "Row Limit" filter.
DEFAULT_LIMIT = 2000
MAX_LIMIT = 20000


class VersionReport:
    def __init__(self, filters=None):
        self.filters = filters or {}
        self.version = DocType("Version")
        self.results = []

    @property
    def row_limit(self):
        limit = cint(self.filters.get("limit")) or DEFAULT_LIMIT
        return min(limit, MAX_LIMIT)

    def apply_filters(self, query):
        if user := self.filters.get("user"):
            query = query.where(self.version.owner == user)
        if doctype := self.filters.get("doctype"):
            query = query.where(self.version.ref_doctype == doctype)
        if docname := self.filters.get("docname"):
            query = query.where(self.version.docname == docname)
        if from_datetime := self.filters.get("from_datetime"):
            query = query.where(self.version.creation >= get_datetime(from_datetime))
        if to_datetime := self.filters.get("to_datetime"):
            query = query.where(self.version.creation <= get_datetime(to_datetime))

        return query

    def build_query(self):
        query = frappe.qb.from_(self.version).select(
            self.version.ref_doctype.as_("doctype"),
            self.version.docname.as_("docname"),
            self.version.data.as_("data"),
            self.version.creation.as_("creation"),
            self.version.owner.as_("user"),
            self.version.name.as_("version"),
        )
        query = self.apply_filters(query)
        # Newest first, and bound the scan so an unfiltered run can't fetch the
        # entire Version table.
        return query.orderby(self.version.creation, order=Order.desc).limit(self.row_limit)

    def fetch_versions(self):
        query = self.build_query()
        return frappe.db.sql(query.get_sql(), as_dict=True)

    def parse_version_data(self, version):
        version_data = frappe.parse_json(version.data)
        changes = version_data.get("changed", [])
        rows_added = version_data.get("added", [])
        rows_removed = version_data.get("removed", [])
        rows_changed = version_data.get("row_changed", [])

        parsed = []
        for field, old, new in changes:
            parsed.append(
                {
                    "doctype": version.doctype,
                    "docname": version.docname,
                    "field_changed": get_field_label(field, version.doctype),
                    "version": version.version,
                    "initial_value": old,
                    "final_value": new,
                    "user": version.user,
                    "creation": version.creation,
                }
            )
        
        for table, row in rows_added:
            parsed.append(
                {
                    "doctype": version.doctype,
                    "docname": version.docname,
                    "field_changed": f"Row Added in {table}",
                    "version": version.version,
                    "initial_value": None,
                    "final_value": frappe.as_json(row),
                    "user": version.user,
                    "creation": version.creation,
                }
            )
        
        for table, row in rows_removed:
            parsed.append(
                {
                    "doctype": version.doctype,
                    "docname": version.docname,
                    "field_changed": f"Row Removed from {table}",
                    "version": version.version,
                    "initial_value": frappe.as_json(row),
                    "final_value": None,
                    "user": version.user,
                    "creation": version.creation,
                }
            )
        
        for table, index, row_id, changes in rows_changed:
            for field, old, new in changes:
                parsed.append(
                    {
                        "doctype": version.doctype,
                        "docname": version.docname,
                        "field_changed": f"{field} in {table} (Row {row_id})",
                        "version": version.version,
                        "initial_value": old,
                        "final_value": new,
                        "user": version.user,
                        "creation": version.creation,
                    }
                )

        return parsed

    def execute(self):
        versions = self.fetch_versions()
        if versions and frappe.get_cached_value("DocType", versions[0]['doctype'], "is_submittable"):
            if self.filters.get("is_post_submission_only"):
                versions = self.filter_post_submission_versions(versions)
        for version in versions:
            self.results.extend(self.parse_version_data(version))
        return self.get_columns(), self.results

    def filter_post_submission_versions(self, versions):
        filtered_versions = []
        submission_dates = {}

        for version in versions:
            version_data = frappe.parse_json(version["data"])
            changes = version_data.get("changed", [])
            if ['docstatus', 0, 1] in changes:
                submission_dates[version["docname"]] = version["creation"]

        for version in versions:
            submission_date = submission_dates.get(version["docname"])
            if submission_date and version["creation"] > submission_date:
                filtered_versions.append(version)

        return filtered_versions

    def get_columns(self):
        return [
            {
                "label": "Version",
                "fieldname": "version",
                "fieldtype": "Link",
                "options": "Version",
                "width": 150,
            },
            {
                "label": "Doctype",
                "fieldname": "doctype",
                "fieldtype": "Link",
                "options": "DocType",
                "width": 150,
            },
            {
                "label": "Docname",
                "fieldname": "docname",
                "fieldtype": "Dynamic Link",
                "options": "doctype",
                "width": 150,
            },
            {
                "label": "Field Changed",
                "fieldname": "field_changed",
                "fieldtype": "Data",
                "width": 150,
            },
            {
                "label": "Initial Value",
                "fieldname": "initial_value",
                "fieldtype": "HTML",
                "width": 150,
            },
            {
                "label": "Final Value",
                "fieldname": "final_value",
                "fieldtype": "HTML",
                "width": 150,
            },
            {
                "label": "Creation",
                "fieldname": "creation",
                "fieldtype": "Datetime",
                "width": 120,
            },
            {
                "label": "User",
                "fieldname": "user",
                "fieldtype": "Link",
                "options": "User",
                "width": 150,
            },
        ]

def execute(filters=None):
    return VersionReport(filters).execute()

def get_field_label(fieldname, doctype):
    if doctype in ["Series", "E Commerce Settings"]:
        return doctype
    meta = frappe.get_meta(doctype)
    label = meta.get_label(fieldname)
    return label if label not in ["No Label", None, ""] else fieldname
