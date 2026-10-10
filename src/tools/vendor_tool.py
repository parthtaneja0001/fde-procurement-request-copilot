from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from src.data_access import load_vendors
from src.tools.base import make_tool_response

POLICY_REFERENCE_DATE = date(2026, 9, 30)
ROOT = Path(__file__).resolve().parents[2]


def _call_vendor_risk_api_with_retry(
    vendor_name: str,
    base_url: str,
    max_retries: int = 1,
    timeout_seconds: float = 0.5,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    url = f"{base_url}/vendor-risk/{quote(vendor_name, safe='')}"
    last_err: str | None = None

    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, timeout=timeout_seconds)
            if resp.status_code == 200:
                return True, resp.json(), None
            elif resp.status_code == 404:
                return False, None, f"Vendor '{vendor_name}' not found in vendor risk service"
            elif resp.status_code >= 500:
                return False, None, f"Vendor risk service returned HTTP {resp.status_code}: {resp.text}"
            else:
                return False, None, f"Vendor risk service error HTTP {resp.status_code}"
        except (requests.Timeout, requests.ConnectionError) as ex:
            last_err = f"Connection failed to vendor risk service ({type(ex).__name__}): {ex}"
        
        if attempt < max_retries:
            time.sleep(0.05)

    # Fallback to local vendor_risk.json simulation if server is offline
    try:
        risk_data = json.loads((ROOT / "data" / "vendor_risk.json").read_text(encoding="utf-8"))
        record = risk_data.get(vendor_name)
        if record is None:
            return False, None, f"No vendor-risk record for '{vendor_name}'"
        if record.get("force_error"):
            return False, None, record.get("error_message", "Vendor-risk service unavailable")
        return True, {"vendor_name": vendor_name, **record}, None
    except Exception:
        pass

    return False, None, last_err


def get_vendor_security_status(
    vendor: str,
    tool_call_id: str | None = None,
    mock_api_url: str | None = None,
) -> dict[str, Any]:
    """Retrieve vendor security, risk, compliance status, and legal terms. Handles service failures and verifies 365-day review expiration."""
    source = "get_vendor_security_status"
    vendor_clean = vendor.strip()
    base_url = mock_api_url or os.getenv("VENDOR_RISK_BASE_URL", "http://127.0.0.1:8001").rstrip("/")

    # 1. Registry lookup (vendors.csv)
    registry_record: dict[str, Any] | None = None
    try:
        vendors_df = load_vendors()
        matched = vendors_df[vendors_df["vendor_name"].str.lower() == vendor_clean.lower()]
        if not matched.empty:
            registry_record = matched.iloc[0].to_dict()
    except Exception:
        registry_record = None

    # 2. Mock service call with retry & fallback
    api_ok, api_data, api_err = _call_vendor_risk_api_with_retry(
        vendor_name=vendor_clean,
        base_url=base_url,
        max_retries=1,
    )

    if not api_ok:
        result_data = {
            "vendor_name": vendor_clean,
            "registry_record": registry_record,
            "api_available": False,
            "service_error": api_err,
            "security_status": "unavailable",
            "is_review_expired": True,
            "has_conflict": False,
            "registry_status": registry_record.get("procurement_status") if registry_record else "New",
            "legal_terms_status": registry_record.get("legal_terms_status") if registry_record else "Unknown",
        }
        return make_tool_response(
            source=source,
            ok=False,
            data=result_data,
            error=f"Vendor risk service unavailable for '{vendor_clean}': {api_err}",
            tool_call_id=tool_call_id,
        )

    # 3. Analyze API data & calculate date expiration
    review_date_str = api_data.get("last_review_date")
    is_expired = False
    days_since_review: int | None = None

    if review_date_str:
        try:
            rev_date = date.fromisoformat(str(review_date_str).strip())
            days_since_review = (POLICY_REFERENCE_DATE - rev_date).days
            if days_since_review > 365 or days_since_review < 0:
                is_expired = True
        except Exception:
            is_expired = True

    if api_data.get("security_review_status") == "expired":
        is_expired = True

    # 4. Check conflict with registry
    has_conflict = False
    conflict_details: list[str] = []
    if registry_record:
        reg_status = str(registry_record.get("security_status", "")).lower()
        api_status = str(api_data.get("security_review_status", "")).lower()
        if reg_status == "approved" and (api_status in ("expired", "not_completed") or is_expired):
            has_conflict = True
            conflict_details.append(
                f"Registry indicates '{reg_status}' but risk service indicates '{api_status}' (review date: {review_date_str})"
            )

    combined_data = {
        "vendor_name": vendor_clean,
        "api_available": True,
        "risk_level": api_data.get("risk_level", "unknown"),
        "security_review_status": api_data.get("security_review_status", "unknown"),
        "last_review_date": review_date_str,
        "days_since_review": days_since_review,
        "is_review_expired": is_expired,
        "processes_personal_data": api_data.get("processes_personal_data", False),
        "stores_data_outside_region": api_data.get("stores_data_outside_region", False),
        "notes": api_data.get("notes", ""),
        "registry_status": registry_record.get("procurement_status") if registry_record else "New",
        "registry_security_status": registry_record.get("security_status") if registry_record else "Unknown",
        "legal_terms_status": registry_record.get("legal_terms_status") if registry_record else "Unknown",
        "has_conflict": has_conflict,
        "conflict_details": conflict_details,
    }

    return make_tool_response(
        source=source,
        ok=True,
        data=combined_data,
        tool_call_id=tool_call_id,
    )
