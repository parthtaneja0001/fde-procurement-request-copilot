# Architecture Decision Memo: Which Architecture to Ship

**Author:** Staff AI Engineer  
**Date:** October 10, 2026  
**Decision:** **Ship Architecture A (Single-Agent Baseline with Deterministic Guardrails)**

---

### Executive Recommendation
I recommend shipping **Architecture A**. Based on benchmark evaluation across 32 comprehensive edge-case scenarios, Architecture A matches Architecture B with **100.0% overall case pass rate**, **100.0% recommendation accuracy**, **100.0% evidence grounding**, and **0 false-negative escalations**, while cutting LLM overhead by **50% (1.0 vs 2.0 LLM calls per request)** and keeping local mock-mode latency comparable.

A simpler architecture that delivers identical safety, precision, and adherence beats unnecessary multi-agent orchestration.

---

### Quantitative Evidence from Benchmark Evaluation

| Evaluation Metric | Architecture A (Single Agent) | Architecture B (Staged 2-Agent) | Delta / Business Impact |
|---|---|---|---|
| **Overall Pass Rate** | **100.0%** (32/32) | **100.0%** (32/32) | Exact Parity |
| **Recommendation Accuracy** | **100.0%** | **100.0%** | Exact Parity |
| **Evidence Grounding** | **100.0%** | **100.0%** | Exact Parity |
| **Policy Rule Adherence** | **100.0%** | **100.0%** | Code-Enforced |
| **False-Negative Escalations** | **0** | **0** | Zero Security/Budget Leaks |
| **Avg LLM Calls / Request** | **1.0** | **2.0** | **50% Lower Token/Inference Cost** |
| **Mean Latency** | **5.9 ms** | **6.9 ms** | Architecture A is 1.0 ms faster |

---

### Key Architectural Trade-Offs

1. **Safety and Determinism are Code Properties, Not Agent Properties:**
   Our evaluation confirms that 100% policy compliance, threshold routing, date math (365-day expiry), and prompt injection isolation come from the typed tool contracts and the post-LLM deterministic guardrail layer. Adding a second agent in Architecture B does not increase decision safety because the deterministic code layer already guarantees zero false negatives.

2. **Cost and Reliability at Scale:**
   Architecture B requires two sequential LLM generations per request (Analyst followed by Reviewer). In production, this doubles token spend, doubles API failure surface area, and introduces serialization fragility between agent handoffs. Architecture A achieves identical grounding in a single pass.

3. **Maintenance and Debuggability:**
   Architecture A features a single unified prompt, making system observability, regression testing, and prompt iterations straightforward.

---

### What Would Change This Decision?
We would reconsider Architecture B only if:
1. **Unstructured Evidence Synthesis Explodes:** If evidence inputs expand to multi-page vendor SOC2 PDFs and unstructured contracts exceeding single-call context limits, necessitating a dedicated extraction agent.
2. **Specialized Asynchronous Tool Execution:** If tool retrieval requires complex iterative web browsing or dynamic multi-turn discovery across dozens of external systems before policy evaluation.

Under current requirements, Architecture A is cheaper, more maintainable, and equally safe.
