from __future__ import annotations

from typing import Any
from src.tools.base import make_tool_response

SENSITIVE_DATA_LEVELS = {
    "source_code",
    "production_telemetry",
    "production_cloud",
    "confidential_documents",
    "employee_pii",
    "customer_pii",
    "credentials_secrets",
    "credentials",
    "secrets",
}

PII_DATA_LEVELS = {
    "employee_pii",
    "customer_pii",
}


def check_policy_and_approvals(
    cost: float | None = None,
    user_count: int | None = None,
    category: str | None = None,
    data_sensitivity: str | None = None,
    vendor_status: str | None = None,
    available_budget: float | None = None,
    is_new_vendor: bool = False,
    legal_terms_status: str | None = None,
    stores_data_outside_region: bool = False,
    processes_personal_data: bool = False,
    vendor_review_expired: bool = False,
    has_vendor_conflict: bool = False,
    vendor_api_unavailable: bool = False,
    has_prompt_injection: bool = False,
    has_tool_overlap: bool = False,
    is_employee_missing: bool = False,
    tool_call_id: str | None = None,
) -> dict[str, Any]:
    """DETERMINISTIC policy engine: computes financial approval tiers, specialized reviews (Security, Privacy, Legal),
    risk flags, and hard-block conditions purely in code. LLM can NEVER override this."""
    source = "check_policy_and_approvals"

    approvals: list[dict[str, str]] = []
    risk_flags: list[dict[str, str]] = []
    hard_blocks: list[str] = []
    missing_fields: list[str] = []

    # 1. Missing parameters verification
    if cost is None:
        missing_fields.append("annual_cost_usd")
    if user_count is None:
        missing_fields.append("user_count")
    if not data_sensitivity or data_sensitivity == "unknown":
        missing_fields.append("data_access_level")
    if is_employee_missing:
        missing_fields.append("requester_id")

    if missing_fields:
        risk_flags.append({
            "flag": "missing_information",
            "severity": "HIGH",
            "reason": f"Required fields missing or unverified: {', '.join(missing_fields)}",
        })

    # 2. Cost & Financial Thresholds
    if cost is None:
        approvals.append({"role": "Manager", "reason": "Base line-manager review required (cost missing)"})
    else:
        cost_val = float(cost)
        if cost_val <= 1000.00:
            approvals.append({"role": "Manager", "reason": f"Standard tier up to $1,000 (cost: ${cost_val:,.2f})"})
        elif 1000.00 < cost_val <= 10000.00:
            approvals.append({"role": "Department Head", "reason": f"Spend tier $1,000.01 - $10,000 (cost: ${cost_val:,.2f})"})
            approvals.append({"role": "Procurement", "reason": "Procurement policy compliance and commercial review"})
        elif 10000.00 < cost_val <= 25000.00:
            approvals.append({"role": "Department Head", "reason": f"Spend tier $10,000.01 - $25,000 (cost: ${cost_val:,.2f})"})
            approvals.append({"role": "Finance", "reason": "Budget verification and spend threshold sign-off"})
            approvals.append({"role": "Procurement", "reason": "Procurement vendor contract review"})
        else:  # Above 25,000
            approvals.append({"role": "Department Head", "reason": f"High-spend tier above $25,000 (cost: ${cost_val:,.2f})"})
            approvals.append({"role": "Finance", "reason": "Department budget allocation sign-off"})
            approvals.append({"role": "CFO", "reason": "Executive authorization for spend > $25,000"})
            approvals.append({"role": "Procurement", "reason": "Enterprise vendor negotiation and procurement review"})

    # 3. Budget Check
    if cost is not None and available_budget is not None:
        cost_val = float(cost)
        avail_val = float(available_budget)
        if cost_val > avail_val:
            shortfall = cost_val - avail_val
            risk_flags.append({
                "flag": "budget_insufficient",
                "severity": "HIGH",
                "reason": f"Requested cost (${cost_val:,.2f}) exceeds available department budget (${avail_val:,.2f}) by ${shortfall:,.2f}",
            })
            hard_blocks.append(f"Budget exceeded by ${shortfall:,.2f}")
            if not any(a["role"] == "Finance" for a in approvals):
                approvals.append({"role": "Finance", "reason": "Budget exception approval required due to insufficient funds"})

    # 4. Security Review
    data_sens_norm = str(data_sensitivity).strip().lower() if data_sensitivity else ""
    vendor_stat_norm = str(vendor_status).strip().lower() if vendor_status else ""

    security_needed = False
    security_reasons: list[str] = []

    if data_sens_norm in SENSITIVE_DATA_LEVELS:
        security_needed = True
        security_reasons.append(f"Sensitive data access level: '{data_sensitivity}'")

    if vendor_review_expired or vendor_stat_norm == "expired":
        security_needed = True
        security_reasons.append("Vendor security assessment is expired (>365 days)")
        risk_flags.append({
            "flag": "vendor_review_expired",
            "severity": "HIGH",
            "reason": "Vendor security assessment has expired",
        })
        hard_blocks.append("Vendor security assessment expired")

    if vendor_stat_norm in ("not_completed", "pending", "unknown", "none"):
        security_needed = True
        security_reasons.append(f"Vendor security status is unverified: '{vendor_status}'")
        risk_flags.append({
            "flag": "security_review_required",
            "severity": "MEDIUM",
            "reason": f"Vendor security onboarding incomplete ({vendor_status})",
        })

    if has_vendor_conflict:
        security_needed = True
        security_reasons.append("Registry and risk service contain conflicting security information")
        risk_flags.append({
            "flag": "conflicting_vendor_evidence",
            "severity": "HIGH",
            "reason": "Conflict detected between internal registry and vendor risk service",
        })
        hard_blocks.append("Conflicting vendor security evidence")

    if vendor_api_unavailable:
        security_needed = True
        security_reasons.append("Vendor risk service is unavailable / timed out")
        risk_flags.append({
            "flag": "vendor_risk_unavailable",
            "severity": "HIGH",
            "reason": "Mock vendor risk service is unavailable",
        })
        hard_blocks.append("Vendor risk service unavailable")

    if security_needed:
        if not any(a["role"] == "Security" for a in approvals):
            approvals.append({"role": "Security", "reason": "; ".join(security_reasons)})
        if not any(rf["flag"] == "security_review_required" for rf in risk_flags):
            risk_flags.append({
                "flag": "security_review_required",
                "severity": "HIGH" if any(rf.get("severity") == "HIGH" for rf in risk_flags) else "MEDIUM",
                "reason": "; ".join(security_reasons),
            })

    # 5. Privacy Review
    privacy_needed = False
    privacy_reasons: list[str] = []

    if data_sens_norm in PII_DATA_LEVELS or processes_personal_data:
        privacy_needed = True
        privacy_reasons.append(f"Tool processes employee/customer PII ({data_sensitivity or 'personal data'})")

    if stores_data_outside_region:
        privacy_needed = True
        privacy_reasons.append("Tool stores/transfers data outside operating region")

    if privacy_needed:
        if not any(a["role"] == "Privacy" for a in approvals):
            approvals.append({"role": "Privacy", "reason": "; ".join(privacy_reasons)})
        risk_flags.append({
            "flag": "privacy_review_required",
            "severity": "MEDIUM",
            "reason": "; ".join(privacy_reasons),
        })

    # 6. Legal Review
    legal_needed = False
    legal_reasons: list[str] = []

    terms_norm = str(legal_terms_status).strip().lower() if legal_terms_status else ""
    is_terms_unapproved = terms_norm not in ("approved", "standard")

    if is_new_vendor and (cost is None or cost >= 10000.0):
        legal_needed = True
        legal_reasons.append(f"New vendor with annual spend >= $10,000 (${cost:,.2f})" if cost else "New vendor with unquantified spend")

    if is_terms_unapproved and terms_norm != "":
        legal_needed = True
        legal_reasons.append(f"Legal terms status is non-standard/unapproved: '{legal_terms_status}'")

    if stores_data_outside_region:
        legal_needed = True
        legal_reasons.append("Cross-region data processing requires legal terms/DPA review")

    if legal_needed:
        if not any(a["role"] == "Legal" for a in approvals):
            approvals.append({"role": "Legal", "reason": "; ".join(legal_reasons)})
        risk_flags.append({
            "flag": "legal_review_required",
            "severity": "MEDIUM",
            "reason": "; ".join(legal_reasons),
        })

    # 7. Existing Tool Overlap Flag
    if has_tool_overlap:
        risk_flags.append({
            "flag": "existing_tool_overlap",
            "severity": "MEDIUM",
            "reason": "Existing alternative software or enterprise capacity detected in catalog",
        })

    # 8. Prompt Injection Flag
    if has_prompt_injection:
        risk_flags.append({
            "flag": "prompt_injection_detected",
            "severity": "HIGH",
            "reason": "Adversarial prompt injection pattern detected in input request text",
        })
        hard_blocks.append("Adversarial prompt injection detected")

    # Deduplicate roles while preserving order
    unique_approvals: list[dict[str, str]] = []
    seen_roles: set[str] = set()
    for item in approvals:
        if item["role"] not in seen_roles:
            unique_approvals.append(item)
            seen_roles.add(item["role"])

    requires_human_review = True
    human_reasons: list[str] = []
    if hard_blocks:
        human_reasons.append(f"Hard blocks present: {', '.join(hard_blocks)}")
    if len(unique_approvals) > 0:
        human_reasons.append(f"Requires human sign-off from: {', '.join(a['role'] for a in unique_approvals)}")

    human_review_reason = " | ".join(human_reasons) if human_reasons else "Mandatory human procurement oversight per Section 11 policy"

    data = {
        "approvals_required": unique_approvals,
        "roles_list": [a["role"] for a in unique_approvals],
        "risk_flags": risk_flags,
        "hard_blocks": hard_blocks,
        "has_hard_blocks": len(hard_blocks) > 0,
        "missing_fields": missing_fields,
        "requires_human_review": requires_human_review,
        "human_review_reason": human_review_reason,
    }

    return make_tool_response(
        source=source,
        ok=True,
        data=data,
        tool_call_id=tool_call_id,
    )
