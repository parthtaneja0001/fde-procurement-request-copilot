from __future__ import annotations

from src.contracts import Architecture, ProcurementDecision
from src.data_access import get_request
from src.agents.single_agent import run_single_agent_pipeline
from src.agents.staged_agents import run_staged_agents_pipeline


def handle_request(request_id: str, architecture: Architecture = "single") -> ProcurementDecision:
    """Assessment adapter.
    Dispatches request to either Architecture A ('single') or Architecture B ('staged').
    """
    request_data = get_request(request_id)
    if architecture == "staged":
        return run_staged_agents_pipeline(request_data)
    return run_single_agent_pipeline(request_data)
