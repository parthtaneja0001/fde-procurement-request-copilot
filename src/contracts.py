from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


class RecommendationEnum(str, Enum):
    APPROVE_TO_PROCEED = "APPROVE_TO_PROCEED"
    USE_EXISTING_TOOL = "USE_EXISTING_TOOL"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    REJECT_BLOCKED = "REJECT_BLOCKED"


class SeverityEnum(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EvidenceItem(BaseModel):
    claim: str = Field(default="", description="Factual claim made in the evaluation")
    tool_call_id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:8]}", description="Exact tool_call_id from which this evidence originates")
    source_tool: str = Field(default="system", description="Name of the tool providing this evidence")
    value: Any = Field(default="", description="Factual value or data snippet returned by the tool")

    # Compatibility getters
    @property
    def source(self) -> str:
        return self.source_tool

    @property
    def finding(self) -> str:
        return self.claim

    @model_validator(mode="before")
    @classmethod
    def _normalize_evidence(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "claim" not in data and "finding" in data:
                data["claim"] = data["finding"]
            if "source_tool" not in data and "source" in data:
                data["source_tool"] = data["source"]
            if "tool_call_id" not in data:
                data["tool_call_id"] = data.get("reference") or f"call_{uuid.uuid4().hex[:8]}"
            if "value" not in data:
                data["value"] = data.get("finding", "")
        return data

    def __str__(self) -> str:
        return f"[{self.source_tool}:{self.tool_call_id}] {self.claim} -> {self.value}"


class ApprovalRequirement(BaseModel):
    role: str = Field(description="Role required to approve (e.g. Manager, Department Head, Finance, Procurement, Security, Privacy, Legal, CFO)")
    why: str = Field(description="Specific deterministic policy rule or threshold triggering this approval")

    def __str__(self) -> str:
        return f"{self.role}: {self.why}"


class RiskFlagItem(BaseModel):
    flag: str = Field(description="Standardized risk flag identifier")
    severity: SeverityEnum | str = Field(default=SeverityEnum.MEDIUM, description="Risk severity level: LOW, MEDIUM, HIGH, CRITICAL")
    evidence_ref: str | None = Field(default=None, description="Optional tool_call_id or evidence citation")

    def __str__(self) -> str:
        return f"{self.flag} ({self.severity}) - ref: {self.evidence_ref}"


class RunTelemetry(BaseModel):
    llm_calls: int = 0
    tool_calls: int = 0
    tool_names: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    estimated_tokens: int = 0


class ProcurementDecision(BaseModel):
    request_id: str
    recommendation: RecommendationEnum | str = Field(
        description="Decision enum: APPROVE_TO_PROCEED, USE_EXISTING_TOOL, NEEDS_MORE_INFO, ESCALATE_TO_HUMAN, REJECT_BLOCKED"
    )
    rationale: str = Field(default="", description="Short concise rationale explaining the recommendation")
    evidence: list[EvidenceItem] = Field(default_factory=list, description="Grounding evidence citing real tool calls")
    approvals_required: list[ApprovalRequirement] = Field(
        default_factory=list,
        description="Required approver roles + deterministic reasons computed by code"
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Specific clarifying questions if material info is missing"
    )
    risk_flags: list[RiskFlagItem] = Field(
        default_factory=list,
        description="Identified risk flags with severity and evidence references"
    )
    next_step: str = Field(default="", description="Concrete next action and assigned owner")
    requires_human_review: bool = Field(default=True, description="Always true for procurement actions")
    human_review_reason: str = Field(default="Human review required per procurement policy", description="Reason human action is needed")
    telemetry: RunTelemetry | None = None

    # Backwards compatibility properties and validators for eval harness
    @property
    def required_approvals(self) -> list[str]:
        return [a.role if isinstance(a, ApprovalRequirement) else str(a) for a in self.approvals_required]

    @property
    def human_review_required(self) -> bool:
        return self.requires_human_review

    @model_validator(mode="before")
    @classmethod
    def _normalize_input_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize required_approvals vs approvals_required
            if "required_approvals" in data and "approvals_required" not in data:
                raw_apps = data["required_approvals"]
                data["approvals_required"] = [
                    {"role": a, "why": "Policy threshold"} if isinstance(a, str) else a
                    for a in raw_apps
                ]
            # Normalize human_review_required vs requires_human_review
            if "human_review_required" in data and "requires_human_review" not in data:
                data["requires_human_review"] = data["human_review_required"]
            # Normalize risk_flags items
            if "risk_flags" in data and isinstance(data["risk_flags"], list):
                norm_rf = []
                for rf in data["risk_flags"]:
                    if isinstance(rf, str):
                        norm_rf.append({"flag": rf, "severity": "MEDIUM", "evidence_ref": None})
                    else:
                        norm_rf.append(rf)
                data["risk_flags"] = norm_rf
        return data


Architecture = Literal["single", "staged"]
