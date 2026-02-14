"""Fetch schedule CSV from Google Sheets."""

import requests


EXPORT_URL_TEMPLATE = (
    "https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export"
    "?format=xlsx&gid={gid}"
)


def fetch_schedule(spreadsheet_id: str, gid: str = "0") -> bytes:
    """Download the schedule as XLSX from a public Google Sheet.

    Args:
        spreadsheet_id: The Google Sheets document ID.
        gid: The sheet/tab ID (default "0" for the first tab).

    Returns:
        Raw XLSX bytes.

    Raises:
        requests.HTTPError: If the download fails.
    """
    url = EXPORT_URL_TEMPLATE.format(spreadsheet_id=spreadsheet_id, gid=gid)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.content
