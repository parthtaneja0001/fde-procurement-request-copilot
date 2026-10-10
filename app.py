from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from src.agents.single_agent import run_single_agent_pipeline
from src.agents.staged_agents import run_staged_agents_pipeline
from src.human_review import get_human_decisions, record_human_decision
from src.solution import handle_request

ROOT = Path(__file__).resolve().parent
REQUESTS = json.loads((ROOT / "data" / "requests.json").read_text(encoding="utf-8"))
BY_ID = {r["request_id"]: r for r in REQUESTS}

st.set_page_config(
    page_title="AI Procurement Request Copilot",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for modern UI design and color-coded badges
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 10px;
    }
    .badge-approve {
        background-color: #d4edda;
        color: #155724;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        display: inline-block;
    }
    .badge-escalate {
        background-color: #fff3cd;
        color: #856404;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        display: inline-block;
    }
    .badge-reject {
        background-color: #f8d7da;
        color: #721c24;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        display: inline-block;
    }
    .badge-existing {
        background-color: #cce5ff;
        color: #004085;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        display: inline-block;
    }
    .badge-info {
        background-color: #e2e3e5;
        color: #383d41;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        display: inline-block;
    }
    .severity-CRITICAL {
        background-color: #721c24;
        color: white;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: bold;
    }
    .severity-HIGH {
        background-color: #dc3545;
        color: white;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: bold;
    }
    .severity-MEDIUM {
        background-color: #ffc107;
        color: #212529;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: bold;
    }
    .severity-LOW {
        background-color: #17a2b8;
        color: white;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

st.title("🛡️ AI Procurement Request Copilot")
st.caption("Evidence-grounded internal procurement decision support with deterministic policy controls.")

# Sidebar Configuration
st.sidebar.header("⚙️ Configuration")
mode = st.sidebar.radio(
    "Request Source",
    ["Select Pre-Loaded Request", "Enter Custom Request"],
)

arch_choice = st.sidebar.radio(
    "Agent Architecture",
    ["Architecture A (Single Agent Baseline)", "Architecture B (Staged Two-Agent Variant)"],
    index=0,
)
arch_key = "staged" if "Staged" in arch_choice else "single"

mock_llm_active = os.getenv("MOCK_LLM", "0") in ("1", "true")
st.sidebar.info(f"**LLM Mode:** {'Offline Deterministic Mock' if mock_llm_active or not (os.getenv('GEMINI_API_KEY') or os.getenv('OPENAI_API_KEY')) else 'Active LLM API'}")

active_request = None

if mode == "Select Pre-Loaded Request":
    req_keys = list(BY_ID.keys())
    selected_id = st.sidebar.selectbox(
        "Select Sample Request",
        req_keys,
        format_func=lambda rid: f"{rid} - {BY_ID[rid]['product_name']} (${BY_ID[rid]['annual_cost_usd'] if BY_ID[rid]['annual_cost_usd'] is not None else 'N/A'})",
    )
    active_request = BY_ID[selected_id]
else:
    st.sidebar.subheader("New Custom Request Form")
    custom_req_id = st.sidebar.text_input("Request ID", value="REQ-CUSTOM-01")
    custom_emp = st.sidebar.text_input("Requester ID", value="E001")
    custom_prod = st.sidebar.text_input("Product Name", value="Figma Enterprise")
    custom_vendor = st.sidebar.text_input("Vendor Name", value="PixelCraft")
    custom_cat = st.sidebar.selectbox("Category", ["Design & Creative", "Developer AI", "General AI", "Observability", "Project Management", "E-signature", "Other"])
    custom_cost = st.sidebar.number_input("Annual Cost (USD)", value=12000.0, step=500.0)
    custom_seats = st.sidebar.number_input("User Count", value=10, step=1)
    custom_data = st.sidebar.selectbox("Data Access Level", ["none", "internal_documents", "internal_marketing", "source_code", "customer_pii", "employee_pii", "confidential_documents", "production_telemetry"])
    custom_just = st.sidebar.text_area("Business Justification", value="Required for cross-functional product design collaboration.")
    
    active_request = {
        "request_id": custom_req_id,
        "requester_id": custom_emp,
        "product_name": custom_prod,
        "vendor_name": custom_vendor,
        "category": custom_cat,
        "annual_cost_usd": custom_cost,
        "user_count": custom_seats,
        "business_justification": custom_just,
        "data_access_level": custom_data,
        "requested_integrations": ["SSO"],
        "urgency": "normal",
    }

# Main Layout: 2 Columns
col_left, col_right = st.columns([1, 1.3], gap="large")

with col_left:
    st.subheader("📋 Request Details")
    st.markdown(f"**Request ID:** `{active_request['request_id']}`")
    st.markdown(f"**Requester ID:** `{active_request['requester_id']}` | **Product:** `{active_request['product_name']}`")
    st.markdown(f"**Vendor:** `{active_request['vendor_name']}` | **Category:** `{active_request['category']}`")
    cost_disp = f"${active_request['annual_cost_usd']:,.2f}" if active_request['annual_cost_usd'] is not None else "⚠️ *Not Specified*"
    st.markdown(f"**Annual Cost:** {cost_disp} | **Seats:** `{active_request['user_count'] if active_request['user_count'] is not None else 'N/A'}`")
    st.markdown(f"**Data Access Scope:** `{active_request['data_access_level']}`")
    st.info(f"**Business Justification:**\n\n{active_request['business_justification']}")

    with st.expander("🔍 View Raw Request JSON", expanded=False):
        st.json(active_request)

with col_right:
    st.subheader("⚡ Copilot Analysis")
    run_clicked = st.button("Analyze Procurement Request", type="primary", use_container_width=True)

    if run_clicked or "last_result" in st.session_state and st.session_state.get("last_req_id") == active_request["request_id"]:
        if run_clicked:
            with st.spinner("Executing agent pipeline and deterministic policy checks..."):
                if active_request["request_id"] in BY_ID:
                    decision = handle_request(active_request["request_id"], architecture=arch_key)
                else:
                    decision = run_single_agent_pipeline(active_request) if arch_key == "single" else run_staged_agents_pipeline(active_request)
                st.session_state["last_result"] = decision
                st.session_state["last_req_id"] = active_request["request_id"]
        else:
            decision = st.session_state["last_result"]

        # Telemetry KPI Strip
        tel = decision.telemetry
        if tel:
            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            kpi1.metric("Latency", f"{tel.latency_ms:.0f} ms")
            kpi2.metric("LLM Calls", tel.llm_calls)
            kpi3.metric("Tool Calls", tel.tool_calls)
            kpi4.metric("Architecture", arch_key.upper())

        # Escalation / Outage Banners
        rec_str = str(decision.recommendation)
        is_tool_unavailable = any("vendor_risk_unavailable" in str(rf.flag) for rf in decision.risk_flags)

        if is_tool_unavailable:
            st.error("🚨 **CRITICAL ALERT:** Mock Vendor Risk Service is currently unavailable or returned 503. Automated favorable status is blocked; routing for manual security verification.")

        if "ESCALATE_TO_HUMAN" in rec_str:
            st.warning(f"⚠️ **MANDATORY HUMAN ESCALATION:** {decision.human_review_reason}")
        elif "REJECT_BLOCKED" in rec_str:
            st.error("⛔ **HARD POLICY BLOCK:** Request cannot proceed under current policy.")
        elif "NEEDS_MORE_INFO" in rec_str:
            st.info("ℹ️ **ADDITIONAL INFORMATION REQUIRED:** Critical request parameters are missing.")
        elif "USE_EXISTING_TOOL" in rec_str:
            st.success("🔄 **EXISTING TOOL AVAILABLE:** Enterprise capacity or direct alternatives already exist in company catalog.")
        else:
            st.success("✅ **ELIGIBLE TO PROCEED:** All initial evidence checks pass within policy parameters.")

        # Recommendation Card
        st.markdown(f"### Recommendation: `{rec_str}`")
        st.write(decision.rationale)
        st.markdown(f"**Next Action:** {decision.next_step}")

        # Approvals Required Panel
        st.markdown("#### ✍️ Required Approvals (Deterministic)")
        if decision.approvals_required:
            app_data = [{"Role": a.role, "Policy Reason": a.why} for a in decision.approvals_required]
            st.table(pd.DataFrame(app_data))
        else:
            st.write("No special approvals required.")

        # Risk Flags Panel
        st.markdown("#### 🚩 Identified Risk Flags")
        if decision.risk_flags:
            for rf in decision.risk_flags:
                sev = str(rf.severity).replace("SeverityEnum.", "")
                st.markdown(
                    f"<span class='severity-{sev}'>{sev}</span> **{rf.flag}** - *{rf.evidence_ref or 'Policy check'}*",
                    unsafe_allow_html=True,
                )
        else:
            st.write("No active risk flags identified.")

        # Missing Information Panel
        if decision.missing_information:
            st.markdown("#### ❓ Missing Required Information")
            for mi in decision.missing_information:
                st.markdown(f"- ⚠️ {mi}")

        # Grounded Evidence Panel
        st.markdown("#### 🔎 Grounded Evidence")
        for i, ev in enumerate(decision.evidence):
            with st.expander(f"📌 [{ev.source_tool}] {ev.claim} (`{ev.tool_call_id}`)", expanded=(i == 0)):
                st.json(ev.value if isinstance(ev.value, (dict, list)) else {"value": str(ev.value)})

        # Human Review Action Section
        st.divider()
        st.markdown("### 🧑‍⚖️ Human Decision Action Center")
        st.caption("All purchasing and budget allocations require explicit human review and authorization.")
        
        reviewer_name = st.text_input("Reviewer Name", value="Senior Procurement Manager")
        reviewer_notes = st.text_area("Reviewer Notes & Action Justification", placeholder="Add notes regarding approval conditions or exception approvals...")

        btn_c1, btn_c2, btn_c3 = st.columns(3)
        if btn_c1.button("✅ Approve Spend", use_container_width=True):
            rec = record_human_decision(
                request_id=active_request["request_id"],
                action="APPROVED",
                notes=reviewer_notes,
                reviewer=reviewer_name,
                architecture=arch_key,
                recommendation=rec_str,
            )
            st.success(f"Action recorded: APPROVED at {rec['timestamp']}")

        if btn_c2.button("⛔ Reject Request", use_container_width=True):
            rec = record_human_decision(
                request_id=active_request["request_id"],
                action="REJECTED",
                notes=reviewer_notes,
                reviewer=reviewer_name,
                architecture=arch_key,
                recommendation=rec_str,
            )
            st.error(f"Action recorded: REJECTED at {rec['timestamp']}")

        if btn_c3.button("📩 Request Info from Employee", use_container_width=True):
            rec = record_human_decision(
                request_id=active_request["request_id"],
                action="REQUEST_INFO",
                notes=reviewer_notes,
                reviewer=reviewer_name,
                architecture=arch_key,
                recommendation=rec_str,
            )
            st.warning(f"Action recorded: REQUEST_INFO at {rec['timestamp']}")

        # Decision Audit Trail
        st.markdown("#### 📜 Recent Human Review Audit Trail")
        history = get_human_decisions(active_request["request_id"])
        if history:
            st.dataframe(pd.DataFrame(history)[["id", "request_id", "reviewer", "action", "notes", "timestamp"]])
        else:
            st.caption("No human decisions logged for this request yet.")
    else:
        st.info("Click **Analyze Procurement Request** to evaluate evidence and policy rules.")

st.divider()
st.caption("AI Procurement Request Copilot | Built for FDE Assessment 3 | Policy Snapshot Date: 2026-09-30")
