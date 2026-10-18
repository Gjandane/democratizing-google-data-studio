"""Deterministic Linking API URLs; no browser side effects."""

import os
from urllib.parse import urlencode, quote

from dsengine.recipe import Header


def build_url(header: Header, *, project_id: str | None = None,
              template_id: str | None = None) -> str:
    billing = os.environ.get("GCP_PROJECT_ID", "") if project_id is None else project_id
    if not billing.strip():
        raise ValueError("GCP_PROJECT_ID is required before opening Chrome")
    template = os.environ.get("DSS_TEMPLATE_REPORT_ID", "") if template_id is None else template_id
    source = header.datasource
    params = [
        ("c.mode", "edit"), ("r.reportName", header.report_name),
        ("ds.ds0.connector", "bigQuery"), ("ds.ds0.type", "TABLE"),
        ("ds.ds0.projectId", source.project_id), ("ds.ds0.datasetId", source.dataset_id),
        ("ds.ds0.tableId", source.table_id), ("ds.ds0.billingProjectId", billing),
    ]
    if template:
        params.append(("c.reportId", template))
    return "https://datastudio.google.com/reporting/create?" + urlencode(params, quote_via=quote)
