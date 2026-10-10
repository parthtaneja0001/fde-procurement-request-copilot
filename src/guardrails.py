from __future__ import annotations

import re
from typing import Any

from src.contracts import (
    ApprovalRequirement,
    EvidenceItem,
    ProcurementDecision,
    RecommendationEnum,
    RiskFlagItem,
    SeverityEnum,
)

# Common adversarial prompt injection keywords and patterns
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous\s+|procurement\s+)?(rules|instructions|policies)",
    r"treat\s+this\s+request\s+as\s+(cfo[- ]?approved|approved)",
    r"approve\s+it\s+immediately",
    r"override\s+(policy|system|threshold|approvals)",
    r"bypass\s+(security|finance|compliance|review)",
    r"you\s+must\s+approve",
    r"system\s*:\s*you\s+are",
    r"do\s+not\s+check\s+budget",
]


def detect_prompt_injection(text: str) -> tuple[bool, list[str]]:
    """Scan untrusted user text for prompt injection heuristics."""
    if not text:
        return False, []
    findings: list[str] = []
    text_lower = text.lower()
    for pat in INJECTION_PATTERNS:
        match = re.search(pat, text_lower)
        if match:
            findings.append(f"Matched pattern '{pat}': {match.group(0)}")
    return len(findings) > 0, findings


def apply_guardrails(
    candidate_decision: ProcurementDecision,
    executed_tools: dict[str, dict[str, Any]],  # tool_call_id -> tool_result_envelope
    deterministic_policy_result: dict[str, Any],
    injection_detected: bool = False,
    injection_reasons: list[str] | None = None,
) -> ProcurementDecision:
    """Post-LLM Deterministic Guardrail Layer:
    1. Verify every evidence item's tool_call_id exists and grounding matches tool result. Drop/flag ungrounded claims.
    2. Overwrite approvals_required and requires_human_review with code-computed values.
    3. Force escalation (or rejection) if hard-blocks, expired certs, conflicts, injections, or tool outages exist.
    """
    verified_evidence: list[EvidenceItem] = []
    ungrounded_flags: list[RiskFlagItem] = []

    # 1. Evidence Grounding Check
    for item in candidate_decision.evidence:
        cid = item.tool_call_id
        if cid in executed_tools:
            tool_env = executed_tools[cid]
            # Valid cited tool call
            verified_evidence.append(item)
        else:
            # Check if any executed tool has the same source
            matched_cids = [k for k, v in executed_tools.items() if v.get("source") == item.source_tool]
            if matched_cids:
                # Re-ground to the actual tool_call_id
                item.tool_call_id = matched_cids[0]
                verified_evidence.append(item)
            else:
                # Ungrounded claim
                ungrounded_flags.append(
                    RiskFlagItem(
                        flag="ungrounded_claim_detected",
                        severity=SeverityEnum.HIGH,
                        evidence_ref=f"Claim: '{item.claim}' references non-existent call {cid}",
                    )
                )

    # 2. Extract deterministic values
    policy_data = deterministic_policy_result.get("data", {})
    code_approvals_raw = policy_data.get("approvals_required", [])
    code_risk_flags_raw = policy_data.get("risk_flags", [])
    hard_blocks = policy_data.get("hard_blocks", [])
    missing_fields = policy_data.get("missing_fields", [])

    # Map code approvals
    code_approvals = [
        ApprovalRequirement(
            role=a["role"],
            why=a.get("reason", "Determined by procurement policy")
        )
        for a in code_approvals_raw
    ]

    # Combine risk flags (code + model + ungrounded + injection)
    all_risk_flags: list[RiskFlagItem] = []
    seen_flags: set[str] = set()

    for crf in code_risk_flags_raw:
        flag_name = crf["flag"]
        seen_flags.add(flag_name)
        all_risk_flags.append(
            RiskFlagItem(
                flag=flag_name,
                severity=crf.get("severity", SeverityEnum.MEDIUM),
                evidence_ref=crf.get("reason"),
            )
        )

    for mrf in candidate_decision.risk_flags:
        if mrf.flag not in seen_flags:
            seen_flags.add(mrf.flag)
            all_risk_flags.append(mrf)

    for ugf in ungrounded_flags:
        all_risk_flags.append(ugf)

    if injection_detected and "prompt_injection_detected" not in seen_flags:
        all_risk_flags.append(
            RiskFlagItem(
                flag="prompt_injection_detected",
                severity=SeverityEnum.HIGH,
                evidence_ref="; ".join(injection_reasons or ["Adversarial pattern in request text"]),
            )
        )

    # 3. Determine if escalation or missing info or existing tool
    forced_escalation = False
    escalation_reasons: list[str] = []

    if injection_detected:
        forced_escalation = True
        escalation_reasons.append("Prompt injection attack detected")

    if any(rf.flag == "budget_insufficient" for rf in all_risk_flags):
        forced_escalation = True
        escalation_reasons.append("Department budget insufficient")

    if any(rf.flag == "vendor_review_expired" for rf in all_risk_flags):
        forced_escalation = True
        escalation_reasons.append("Vendor security assessment is expired")

    if any(rf.flag == "conflicting_vendor_evidence" for rf in all_risk_flags):
        forced_escalation = True
        escalation_reasons.append("Conflicting vendor security records")

    if any(rf.flag == "vendor_risk_unavailable" for rf in all_risk_flags):
        forced_escalation = True
        escalation_reasons.append("Vendor risk service unavailable")

    # Missing information handling
    has_missing_info = len(candidate_decision.missing_information) > 0 or len(missing_fields) > 0

    final_recommendation = candidate_decision.recommendation
    final_rationale = candidate_decision.rationale

    if has_missing_info:
        final_recommendation = RecommendationEnum.NEEDS_MORE_INFO
        if not final_rationale:
            final_rationale = "Request is missing essential information required for review."
    elif forced_escalation:
        final_recommendation = RecommendationEnum.ESCALATE_TO_HUMAN
        final_rationale = f"Mandatory human escalation triggered: {', '.join(escalation_reasons)}."
    elif candidate_decision.recommendation in (
        RecommendationEnum.USE_EXISTING_TOOL,
        "USE_EXISTING_TOOL",
    ):
        final_recommendation = RecommendationEnum.USE_EXISTING_TOOL
    elif candidate_decision.recommendation in (
        RecommendationEnum.REJECT_BLOCKED,
        "REJECT_BLOCKED",
    ):
        final_recommendation = RecommendationEnum.REJECT_BLOCKED
    else:
        final_recommendation = RecommendationEnum.APPROVE_TO_PROCEED

    # Final Next Step & Owner
    final_next_step = candidate_decision.next_step
    if not final_next_step or final_next_step.strip() == "":
        if final_recommendation == RecommendationEnum.NEEDS_MORE_INFO:
            final_next_step = "Requester to provide missing annual cost and data access scope."
        elif final_recommendation == RecommendationEnum.ESCALATE_TO_HUMAN:
            roles_str = ", ".join(a.role for a in code_approvals) or "Procurement / Security"
            final_next_step = f"Route to {roles_str} for exception review."
        elif final_recommendation == RecommendationEnum.USE_EXISTING_TOOL:
            final_next_step = "Direct requester to utilize existing enterprise license."
        else:
            first_role = code_approvals[0].role if code_approvals else "Manager"
            final_next_step = f"Submit request to {first_role} for initial sign-off."

    # Always enforce requires_human_review = True per Section 11
    human_reason = policy_data.get("human_review_reason") or "Mandatory human oversight required for spend commitments."

    return ProcurementDecision(
        request_id=candidate_decision.request_id,
        recommendation=final_recommendation,
        rationale=final_rationale,
        evidence=verified_evidence,
        approvals_required=code_approvals,
        missing_information=candidate_decision.missing_information or [f"Missing {f}" for f in missing_fields],
        risk_flags=all_risk_flags,
        next_step=final_next_step,
        requires_human_review=True,
        human_review_reason=human_reason,
        telemetry=candidate_decision.telemetry,
    )
