"""Deterministic Linking API URLs; no browser side effects."""

import os
from urllib.parse import urlencode, quote

from dsengine.recipe import GcsDatasource, Header


def build_url(header: Header, *, project_id: str | None = None,
              template_id: str | None = None) -> str:
    source = header.datasource
    params = [("c.mode", "edit"), ("r.reportName", header.report_name)]
    if isinstance(source, GcsDatasource):
        # Data Studio reads the file as the signed-in account: no billing project.
        params += [
            ("ds.ds0.connector", "googleCloudStorage"), ("ds.ds0.pathType", source.path_type),
            ("ds.ds0.path", source.path),
        ]
    else:
        billing = os.environ.get("GCP_PROJECT_ID", "") if project_id is None else project_id
        if not billing.strip():
            raise ValueError("GCP_PROJECT_ID is required before opening Chrome")
        params += [
            ("ds.ds0.connector", "bigQuery"), ("ds.ds0.type", "TABLE"),
            ("ds.ds0.projectId", source.project_id), ("ds.ds0.datasetId", source.dataset_id),
            ("ds.ds0.tableId", source.table_id), ("ds.ds0.billingProjectId", billing),
        ]
    template = os.environ.get("DSS_TEMPLATE_REPORT_ID", "") if template_id is None else template_id
    if template:
        params.append(("c.reportId", template))
    return "https://datastudio.google.com/reporting/create?" + urlencode(params, quote_via=quote)
