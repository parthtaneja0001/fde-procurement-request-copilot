# System Architecture and Workflow Design (docs/architecture.md)

## 1. End-to-End Procurement Workflow

The AI Procurement Request Copilot enforces a strict separation of concerns across AI interpretation, deterministic code verification, and human authority.

```mermaid
flowchart TD
    A[1. Employee Request] --> B[2. Understand Need & Extract Parameters]
    B --> C[3. Gather Evidence via Typed Core Tools]
    
    subgraph Core Tools [Core Deterministic & API Tools]
        C1[Employee & Department Budget]
        C2[Software Catalog & Overlap Search]
        C3[Vendor Security Status & 365d Expiry]
        C4[Purchase History & Duplicate Orders]
        C5[Deterministic Policy & Approvals Engine]
    end
    
    C --> C1
    C --> C2
    C --> C3
    C --> C4
    C --> C5
    
    C1 --> D[4. Formulate Structured Recommendation]
    C2 --> D
    C3 --> D
    C4 --> D
    C5 --> D
    
    D --> E[5. Post-LLM Deterministic Guardrails]
    E --> F[6. Human Review & Decision Center]
    
    subgraph Human Oversight [Human Review Actions]
        F1[Approve Spend]
        F2[Reject Request]
        F3[Request More Info]
    end
    
    F --> F1
    F --> F2
    F --> F3
```

---

## 2. Architecture Comparison: Single Agent vs. Staged Two-Agent

### Architecture A: Single-Agent Baseline
In Architecture A, a single **Procurement Agent** receives the untrusted user request, orchestrates tool calling across budget, catalog, vendor security, and history sources, and produces a candidate decision that is passed through the deterministic guardrail layer.

```mermaid
flowchart LR
    UI[Product UI / Streamlit] --> PA[Procurement Agent]
    PA --> Tools[5 Core Tools]
    Tools --> PA
    PA --> CD[Candidate Decision]
    CD --> Guard[Deterministic Guardrail Layer]
    Guard --> Out[Final Verified Decision]
    Out --> UI
```

### Architecture B: Staged Two-Agent Variant
In Architecture B, responsibility is split into two specialized stages:
1. **Agent 1 (Procurement Analyst)**: Interprets user request, executes core tools, and compiles an isolated **Structured Evidence Pack**.
2. **Deterministic Policy Engine**: Computes exact financial tiers, required reviewer roles, and hard blocks.
3. **Agent 2 (Policy & Risk Reviewer)**: Receives *only* the structured evidence pack and deterministic policy outputs (isolated from raw prompt text), reasons over trade-offs and catalog overlaps, and emits the candidate decision.

```mermaid
flowchart LR
    UI[Product UI / Streamlit] --> A1[Agent 1: Procurement Analyst]
    A1 --> Tools[Core Tools]
    Tools --> A1
    A1 --> Pack[Structured Evidence Pack]
    Pack --> Pol[Deterministic Policy Tool]
    Pack --> A2[Agent 2: Risk Reviewer]
    Pol --> A2
    A2 --> CD[Candidate Decision]
    CD --> Guard[Deterministic Guardrail Layer]
    Guard --> Out[Final Verified Decision]
    Out --> UI
```

---

## 3. Responsibility Matrix: AI vs. Code vs. Human

| Domain | AI Responsibility | Code Responsibility (Deterministic) | Human Authority |
|---|---|---|---|
| **Request Interpretation** | Understands user context, extracts implicit requirements, evaluates business justifications | Validates presence of mandatory schema fields (cost, seats, data level) | Resolves ambiguity and provides clarifying details |
| **Tool Execution & Grounding** | Selects and invokes appropriate evidence tools | Generates `tool_call_id`, enforces network retries, handles 503 outages | Inspects raw tool payloads and evidence citations |
| **Financial & Policy Thresholds** | Summarizes budgetary context | Computes exact spend tiers ($1k, $10k, $25k), budget arithmetic, and overrides hallucinated roles | Approves expenditure, signs off on budget overages |
| **Security & Privacy Risk** | Synthesizes complex vendor risk notes | Calculates 365-day certificate expiry, detects registry conflicts, enforces PII/cross-region rules | Grants security exceptions and accepts residual vendor risks |
| **Prompt Injection Defense** | Follows XML untrusted boundary guidelines | Heuristic/regex pattern scanner flags injection and forces human escalation | Audits suspicious requests flagged by the system |
| **Final Authority** | Provides structured advisory recommendations only | Hard-blocks autonomous approval and guarantees `requires_human_review=True` | Executes final purchasing, contracts, and vendor commitments |
