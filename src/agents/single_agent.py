from __future__ import annotations

import json
import time
from typing import Any

from src.agents.prompts import SINGLE_AGENT_SYSTEM_PROMPT
from src.contracts import EvidenceItem, ProcurementDecision, RunTelemetry
from src.guardrails import apply_guardrails, detect_prompt_injection
from src.llm.client import LLMClient
from src.tools.employee_budget_tool import get_employee_and_budget
from src.tools.policy_tool import check_policy_and_approvals
from src.tools.purchase_history_tool import get_purchase_history
from src.tools.software_catalog_tool import search_software_catalog
from src.tools.vendor_tool import get_vendor_security_status


def run_single_agent_pipeline(request: dict[str, Any], llm_client: LLMClient | None = None) -> ProcurementDecision:
    """Architecture A: Single-agent baseline with tool calling, untrusted framing, and deterministic guardrail layer."""
    start_time = time.perf_counter()
    client = llm_client or LLMClient()
    req_id = request.get("request_id", "REQ-UNKNOWN")
    requester_id = request.get("requester_id", "")
    vendor_name = request.get("vendor_name", "")
    product_name = request.get("product_name", "")
    category = request.get("category", "")
    cost = request.get("annual_cost_usd")
    data_access = request.get("data_access_level", "")
    justification = request.get("business_justification", "")

    executed_tools: dict[str, dict[str, Any]] = {}
    tool_names: list[str] = []

    # 1. Tool 1: Employee & Budget
    emp_res = get_employee_and_budget(requester_id)
    executed_tools[emp_res["tool_call_id"]] = emp_res
    tool_names.append("get_employee_and_budget")

    dept_name = None
    avail_budget = None
    if emp_res["ok"] and emp_res.get("data"):
        dept_name = emp_res["data"]["employee"].get("department")
        b_info = emp_res["data"].get("department_budget")
        if b_info:
            avail_budget = b_info.get("available_usd")

    # Tool 2: Software Catalog Search
    cat_res = search_software_catalog(query=product_name or vendor_name, category=category)
    executed_tools[cat_res["tool_call_id"]] = cat_res
    tool_names.append("search_software_catalog")
    has_overlap = cat_res.get("data", {}).get("has_overlap", False) if cat_res.get("ok") else False

    # Tool 3: Vendor Security Status
    vend_res = get_vendor_security_status(vendor_name)
    executed_tools[vend_res["tool_call_id"]] = vend_res
    tool_names.append("get_vendor_security_status")

    v_stat = None
    is_new = False
    v_expired = False
    v_conflict = False
    v_api_down = not vend_res["ok"]
    legal_terms = "Unknown"
    stores_cross_region = False
    processes_pii = False

    if vend_res.get("data"):
        vd = vend_res["data"]
        v_stat = vd.get("security_review_status")
        is_new = vd.get("registry_status") == "New"
        v_expired = vd.get("is_review_expired", False)
        v_conflict = vd.get("has_conflict", False)
        legal_terms = vd.get("legal_terms_status", "Unknown")
        stores_cross_region = vd.get("stores_data_outside_region", False)
        processes_pii = vd.get("processes_personal_data", False)

    # Tool 4: Purchase History
    hist_res = get_purchase_history(vendor_or_tool=vendor_name or product_name, team=dept_name)
    executed_tools[hist_res["tool_call_id"]] = hist_res
    tool_names.append("get_purchase_history")

    # 2. Prompt Injection Scanner
    combined_user_text = f"{product_name} {justification} {data_access}"
    has_injection, injection_reasons = detect_prompt_injection(combined_user_text)

    # 3. Deterministic Policy Calculation
    policy_res = check_policy_and_approvals(
        cost=cost,
        category=category,
        data_sensitivity=data_access,
        vendor_status=v_stat,
        available_budget=avail_budget,
        is_new_vendor=is_new,
        legal_terms_status=legal_terms,
        stores_data_outside_region=stores_cross_region,
        processes_personal_data=processes_pii,
        vendor_review_expired=v_expired,
        has_vendor_conflict=v_conflict,
        vendor_api_unavailable=v_api_down,
        has_prompt_injection=has_injection,
        has_tool_overlap=has_overlap,
    )
    executed_tools[policy_res["tool_call_id"]] = policy_res
    tool_names.append("check_policy_and_approvals")

    # 4. XML Framing for Untrusted Inputs
    user_prompt = f"""<untrusted_request_data>
{json.dumps(request, indent=2)}
</untrusted_request_data>

<tool_evidence>
{json.dumps(executed_tools, indent=2)}
</tool_evidence>

Please analyze the request and tool evidence and provide a structured ProcurementDecision.
Remember to cite real tool_call_id references in every evidence item.
"""

    fallback_ctx = {
        "request": request,
        "executed_tools": executed_tools,
        "architecture": "single",
    }

    # 5. LLM Call
    candidate, llm_calls, tokens = client.generate_structured(
        system_prompt=SINGLE_AGENT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema_cls=ProcurementDecision,
        fallback_context=fallback_ctx,
    )

    # Ensure baseline evidence items for all executed tools are populated
    grounded_evidence: list[EvidenceItem] = list(candidate.evidence)
    existing_cids = {e.tool_call_id for e in grounded_evidence}

    if emp_res["tool_call_id"] not in existing_cids and emp_res.get("data"):
        b_val = emp_res["data"].get("department_budget", {})
        grounded_evidence.append(
            EvidenceItem(
                claim=f"Department {dept_name} software budget available: ${b_val.get('available_usd', 0):,.2f}",
                tool_call_id=emp_res["tool_call_id"],
                source_tool="get_employee_and_budget",
                value=b_val,
            )
        )
    if cat_res["tool_call_id"] not in existing_cids and cat_res.get("data"):
        alts = cat_res["data"].get("potential_alternatives", [])
        grounded_evidence.append(
            EvidenceItem(
                claim=f"Catalog search identified {len(alts)} matching/alternative software products",
                tool_call_id=cat_res["tool_call_id"],
                source_tool="search_software_catalog",
                value=alts[:2] if alts else "None",
            )
        )
    if vend_res["tool_call_id"] not in existing_cids:
        grounded_evidence.append(
            EvidenceItem(
                claim=f"Vendor security review status: {v_stat or 'unavailable'} (expired: {v_expired})",
                tool_call_id=vend_res["tool_call_id"],
                source_tool="get_vendor_security_status",
                value=vend_res.get("data") or vend_res.get("error"),
            )
        )
    if hist_res["tool_call_id"] not in existing_cids and hist_res.get("data"):
        p_count = hist_res["data"].get("purchase_count", 0)
        grounded_evidence.append(
            EvidenceItem(
                claim=f"Purchase history found {p_count} historical purchase records for vendor/team",
                tool_call_id=hist_res["tool_call_id"],
                source_tool="get_purchase_history",
                value=hist_res["data"].get("purchases", []),
            )
        )

    candidate.evidence = grounded_evidence

    # 6. Apply Deterministic Guardrail Layer
    final_decision = apply_guardrails(
        candidate_decision=candidate,
        executed_tools=executed_tools,
        deterministic_policy_result=policy_res,
        injection_detected=has_injection,
        injection_reasons=injection_reasons,
    )

    latency_ms = (time.perf_counter() - start_time) * 1000
    final_decision.telemetry = RunTelemetry(
        llm_calls=llm_calls,
        tool_calls=len(executed_tools),
        tool_names=tool_names,
        latency_ms=round(latency_ms, 2),
        estimated_tokens=tokens,
    )

    return final_decision
