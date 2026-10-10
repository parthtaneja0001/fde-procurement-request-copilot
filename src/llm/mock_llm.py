from __future__ import annotations

from typing import Any
from src.contracts import RecommendationEnum


def generate_mock_procurement_decision(
    request: dict[str, Any],
    executed_tools: dict[str, dict[str, Any]],
    architecture: str = "single",
) -> dict[str, Any]:
    """Deterministic, schema-compliant mock LLM generator for testing and offline evaluation."""
    req_id = request.get("request_id", "REQ-UNKNOWN")
    cost = request.get("annual_cost_usd")
    product_name = request.get("product_name", "")
    vendor_name = request.get("vendor_name", "")
    category = request.get("category", "")
    justification = request.get("business_justification", "")
    data_access = request.get("data_access_level", "")

    evidence_items = []
    missing_info = []
    risk_flags = []

    # Check for missing info
    if cost is None:
        missing_info.append("Estimated annual cost or pricing model")
    if request.get("user_count") is None:
        missing_info.append("Number of required user seats/licenses")
    if not data_access or data_access == "unknown":
        missing_info.append("Specific data-access level and integration scope")

    catalog_alts = []

    for cid, t_env in executed_tools.items():
        src = t_env.get("source")
        data_block = t_env.get("data") or {}

        if src == "get_employee_and_budget":
            b_data = data_block.get("department_budget")
            if b_data:
                evidence_items.append({
                    "claim": f"Department available software budget is ${b_data.get('available_usd', 0):,.2f}",
                    "tool_call_id": cid,
                    "source_tool": src,
                    "value": b_data,
                })
        elif src == "search_software_catalog":
            matches = data_block.get("potential_alternatives", [])
            catalog_alts = matches
            if matches:
                top = matches[0]
                evidence_items.append({
                    "claim": f"Catalog contains alternative software: {top.get('product_name')} ({top.get('category')})",
                    "tool_call_id": cid,
                    "source_tool": src,
                    "value": top,
                })
        elif src == "get_vendor_security_status":
            if not t_env.get("ok"):
                evidence_items.append({
                    "claim": f"Vendor security risk service is unavailable for {vendor_name}",
                    "tool_call_id": cid,
                    "source_tool": src,
                    "value": t_env.get("error"),
                })
            else:
                evidence_items.append({
                    "claim": f"Vendor security status is {data_block.get('security_review_status')} (expired: {data_block.get('is_review_expired')})",
                    "tool_call_id": cid,
                    "source_tool": src,
                    "value": data_block,
                })
        elif src == "get_purchase_history":
            if data_block.get("is_existing_purchase"):
                evidence_items.append({
                    "claim": f"Existing company purchase record exists: {data_block.get('existing_purchase_summary')}",
                    "tool_call_id": cid,
                    "source_tool": src,
                    "value": data_block.get("existing_purchase_summary"),
                })

    # Exact duplication check:
    # A true duplicate replacement (USE_EXISTING_TOOL) is when the request is for a new duplicate tool
    # (e.g. TaskFlow Pro or WikiSpace) when the company already has full enterprise capacity,
    # and NOT an authorized expansion, add-on, training, or tier increase.
    is_overlap = False
    overlap_product = ""
    prod_lower = product_name.lower()

    if "taskflow pro" in prod_lower or "wikispace" in prod_lower or ("project management" in category.lower() and "taskflow" in prod_lower and "add-on" not in prod_lower):
        is_overlap = True
        overlap_product = "TaskFlow" if "taskflow" in prod_lower else "DocSpace"

    # Recommendation determination
    if missing_info:
        rec = RecommendationEnum.NEEDS_MORE_INFO
        rationale = "Request is missing material cost, seat count, or data access parameters."
        next_step = "Request clarification from requester regarding missing details."
    elif is_overlap:
        rec = RecommendationEnum.USE_EXISTING_TOOL
        rationale = f"An enterprise license for {overlap_product or product_name} already exists in the company catalog."
        next_step = f"Direct requester to access existing company license for {overlap_product or product_name}."
    else:
        rec = RecommendationEnum.APPROVE_TO_PROCEED
        rationale = f"Request for {product_name} meets standard operational criteria."
        next_step = "Submit to required departmental approvers."

    return {
        "request_id": req_id,
        "recommendation": rec,
        "rationale": rationale,
        "evidence": evidence_items,
        "approvals_required": [{"role": "Manager", "why": "Initial request review"}],
        "missing_information": missing_info,
        "risk_flags": risk_flags,
        "next_step": next_step,
        "requires_human_review": True,
        "human_review_reason": "Human approval required per procurement guidelines.",
    }
