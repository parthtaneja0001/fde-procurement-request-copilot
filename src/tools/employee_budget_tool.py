from __future__ import annotations

from typing import Any
from src.data_access import load_budgets, load_employees
from src.tools.base import make_tool_response


def get_employee_and_budget(employee_id: str, tool_call_id: str | None = None) -> dict[str, Any]:
    """Retrieve employee details, department, manager, and department budget snapshot (annual, committed, available)."""
    source = "get_employee_and_budget"
    try:
        employees_df = load_employees()
        budgets_df = load_budgets()

        emp_matches = employees_df[employees_df["employee_id"] == employee_id]
        if emp_matches.empty:
            return make_tool_response(
                source=source,
                ok=False,
                error=f"Employee '{employee_id}' not found in employee directory",
                tool_call_id=tool_call_id,
            )

        emp_row = emp_matches.iloc[0].to_dict()
        dept_name = emp_row["department"]

        # Lookup manager if exists
        manager_info = None
        manager_id = emp_row.get("manager_id")
        if manager_id and str(manager_id).strip() and str(manager_id) != "nan":
            mgr_matches = employees_df[employees_df["employee_id"] == manager_id]
            if not mgr_matches.empty:
                mgr_row = mgr_matches.iloc[0].to_dict()
                manager_info = {
                    "employee_id": mgr_row["employee_id"],
                    "name": mgr_row["name"],
                    "level": mgr_row["level"],
                }

        # Lookup department budget
        budget_matches = budgets_df[budgets_df["department"] == dept_name]
        if budget_matches.empty:
            budget_info = None
        else:
            b_row = budget_matches.iloc[0]
            annual = float(b_row["annual_software_budget_usd"])
            committed = float(b_row["committed_usd"])
            available = float(b_row["available_usd"])
            budget_info = {
                "department": dept_name,
                "annual_budget_usd": annual,
                "committed_usd": committed,
                "available_usd": available,
                "is_consistent": (annual - committed) == available,
            }

        data = {
            "employee": {
                "employee_id": emp_row["employee_id"],
                "name": emp_row["name"],
                "department": dept_name,
                "level": emp_row["level"],
                "country": emp_row["country"],
                "manager": manager_info,
            },
            "department_budget": budget_info,
        }

        return make_tool_response(
            source=source,
            ok=True,
            data=data,
            tool_call_id=tool_call_id,
        )
    except Exception as exc:
        return make_tool_response(
            source=source,
            ok=False,
            error=f"Error looking up employee/budget: {str(exc)}",
            tool_call_id=tool_call_id,
        )
