from __future__ import annotations

import json
import time
from typing import Any
from pydantic import BaseModel, Field

from src.agents.prompts import ANALYST_SYSTEM_PROMPT, REVIEWER_SYSTEM_PROMPT
from src.contracts import EvidenceItem, ProcurementDecision, RunTelemetry
from src.guardrails import apply_guardrails, detect_prompt_injection
from src.llm.client import LLMClient
from src.tools.employee_budget_tool import get_employee_and_budget
from src.tools.policy_tool import check_policy_and_approvals
from src.tools.purchase_history_tool import get_purchase_history
from src.tools.software_catalog_tool import search_software_catalog
from src.tools.vendor_tool import get_vendor_security_status


class StructuredEvidencePack(BaseModel):
    request_id: str
    requester_summary: dict[str, Any] = Field(default_factory=dict)
    budget_summary: dict[str, Any] = Field(default_factory=dict)
    catalog_overlap_summary: list[dict[str, Any]] = Field(default_factory=list)
    vendor_risk_summary: dict[str, Any] = Field(default_factory=dict)
    purchase_history_summary: list[dict[str, Any]] = Field(default_factory=list)
    identified_missing_fields: list[str] = Field(default_factory=list)
    grounded_evidence: list[EvidenceItem] = Field(default_factory=list)


def run_staged_agents_pipeline(request: dict[str, Any], llm_client: LLMClient | None = None) -> ProcurementDecision:
    """Architecture B: Staged Two-Agent Variant.
    Agent 1 (Procurement Analyst) gathers evidence and compiles a structured evidence pack.
    Agent 2 (Policy/Risk Reviewer) receives ONLY structured evidence + deterministic policy result to produce decision.
    Followed by the same guardrail layer.
    """
    start_time = time.perf_counter()
    client = llm_client or LLMClient()
    req_id = request.get("request_id", "REQ-UNKNOWN")
    requester_id = request.get("requester_id", "")
    vendor_name = request.get("vendor_name", "")
    product_name = request.get("product_name", "")
    category = request.get("category", "")
    cost = request.get("annual_cost_usd")
    user_count = request.get("user_count")
    data_access = request.get("data_access_level", "")
    justification = request.get("business_justification", "")

    executed_tools: dict[str, dict[str, Any]] = {}
    tool_names: list[str] = []
    total_llm_calls = 0
    total_tokens = 0

    # 1. Agent 1: Tool Execution & Evidence Gathering
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

    cat_res = search_software_catalog(query=product_name or vendor_name, category=category)
    executed_tools[cat_res["tool_call_id"]] = cat_res
    tool_names.append("search_software_catalog")
    has_overlap = cat_res.get("data", {}).get("has_overlap", False) if cat_res.get("ok") else False

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

    hist_res = get_purchase_history(vendor_or_tool=vendor_name or product_name, team=dept_name)
    executed_tools[hist_res["tool_call_id"]] = hist_res
    tool_names.append("get_purchase_history")

    # 2. Prompt Injection Heuristic Scanner
    combined_user_text = f"{product_name} {justification} {data_access}"
    has_injection, injection_reasons = detect_prompt_injection(combined_user_text)

    # 3. Deterministic Policy Calculation
    policy_res = check_policy_and_approvals(
        cost=cost,
        user_count=user_count,
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
        is_employee_missing=not emp_res["ok"],
    )
    executed_tools[policy_res["tool_call_id"]] = policy_res
    tool_names.append("check_policy_and_approvals")

    # Build Grounded Evidence Items for All Core Tools
    grounded_evidence: list[EvidenceItem] = []
    if emp_res["ok"] and (emp_res.get("data") or {}).get("department_budget"):
        grounded_evidence.append(
            EvidenceItem(
                claim=f"Department {dept_name} software budget available: ${avail_budget:,.2f}",
                tool_call_id=emp_res["tool_call_id"],
                source_tool="get_employee_and_budget",
                value=emp_res["data"]["department_budget"],
            )
        )
    else:
        grounded_evidence.append(
            EvidenceItem(
                claim=f"Employee lookup: {emp_res.get('error') or 'Employee valid'}",
                tool_call_id=emp_res["tool_call_id"],
                source_tool="get_employee_and_budget",
                value=emp_res.get("data") or emp_res.get("error"),
            )
        )

    if cat_res["ok"] and cat_res.get("data"):
        alts = cat_res["data"].get("potential_alternatives", [])
        grounded_evidence.append(
            EvidenceItem(
                claim=f"Catalog has {len(alts)} existing potential alternatives/matches",
                tool_call_id=cat_res["tool_call_id"],
                source_tool="search_software_catalog",
                value=alts[:2] if alts else "None",
            )
        )
    if vend_res.get("data") or not vend_res["ok"]:
        grounded_evidence.append(
            EvidenceItem(
                claim=f"Vendor security review status: {v_stat or 'unavailable'} (expired: {v_expired})",
                tool_call_id=vend_res["tool_call_id"],
                source_tool="get_vendor_security_status",
                value=vend_res.get("data") or vend_res.get("error"),
            )
        )
    if hist_res["ok"] and hist_res.get("data"):
        grounded_evidence.append(
            EvidenceItem(
                claim=f"Purchase history found {hist_res['data'].get('purchase_count', 0)} previous purchases",
                tool_call_id=hist_res["tool_call_id"],
                source_tool="get_purchase_history",
                value=hist_res["data"].get("purchases", []),
            )
        )

    # Assemble Structured Evidence Pack (Agent 1 Output)
    evidence_pack = StructuredEvidencePack(
        request_id=req_id,
        requester_summary=(emp_res.get("data") or {}).get("employee", {}),
        budget_summary=(emp_res.get("data") or {}).get("department_budget", {}),
        catalog_overlap_summary=(cat_res.get("data") or {}).get("potential_alternatives", []),
        vendor_risk_summary=vend_res.get("data") or {},
        purchase_history_summary=(hist_res.get("data") or {}).get("purchases", []),
        identified_missing_fields=(policy_res.get("data") or {}).get("missing_fields", []),
        grounded_evidence=grounded_evidence,
    )

    analyst_user_prompt = f"""<untrusted_request>
{json.dumps(request, indent=2)}
</untrusted_request>

<tool_results>
{json.dumps(executed_tools, indent=2)}
</tool_results>

Compile a structured evidence pack from the request and tool results. Do not make a final procurement recommendation.
"""

    evidence_pack, llm_calls, tokens = client.generate_structured(
        system_prompt=ANALYST_SYSTEM_PROMPT,
        user_prompt=analyst_user_prompt,
        schema_cls=StructuredEvidencePack,
        fallback_context={
            "request": request,
            "executed_tools": executed_tools,
            "architecture": "staged",
            "evidence_pack": evidence_pack.model_dump(),
        },
    )
    total_llm_calls += llm_calls
    total_tokens += tokens

    # 4. Agent 2: Policy & Risk Reviewer
    reviewer_user_prompt = f"""<structured_evidence_pack>
{evidence_pack.model_dump_json(indent=2)}
</structured_evidence_pack>

<deterministic_policy_result>
{json.dumps(policy_res, indent=2)}
</deterministic_policy_result>

Please evaluate this structured evidence pack against company policy rules and generate a final ProcurementDecision.
"""

    fallback_ctx = {
        "request": request,
        "executed_tools": executed_tools,
        "architecture": "staged",
    }

    # Call Reviewer LLM
    candidate, llm_calls, tokens = client.generate_structured(
        system_prompt=REVIEWER_SYSTEM_PROMPT,
        user_prompt=reviewer_user_prompt,
        schema_cls=ProcurementDecision,
        fallback_context=fallback_ctx,
    )
    total_llm_calls += llm_calls
    total_tokens += tokens

    # Ensure evidence includes grounded items
    candidate.evidence = grounded_evidence

    # 5. Apply Deterministic Guardrail Layer
    final_decision = apply_guardrails(
        candidate_decision=candidate,
        executed_tools=executed_tools,
        deterministic_policy_result=policy_res,
        injection_detected=has_injection,
        injection_reasons=injection_reasons,
    )

    latency_ms = (time.perf_counter() - start_time) * 1000
    final_decision.telemetry = RunTelemetry(
        llm_calls=total_llm_calls,
        tool_calls=len(executed_tools),
        tool_names=tool_names,
        latency_ms=round(latency_ms, 2),
        estimated_tokens=total_tokens,
    )

    return final_decision
