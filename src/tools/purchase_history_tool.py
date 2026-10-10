from __future__ import annotations

from typing import Any
from src.data_access import load_purchase_history
from src.tools.base import make_tool_response


def get_purchase_history(
    vendor_or_tool: str,
    team: str | None = None,
    tool_call_id: str | None = None,
) -> dict[str, Any]:
    """Retrieve historical purchases and renewals for a vendor or tool across departments."""
    source = "get_purchase_history"
    try:
        history_df = load_purchase_history()
        query_str = vendor_or_tool.strip().lower() if vendor_or_tool else ""
        team_str = team.strip().lower() if team else None

        records: list[dict[str, Any]] = []
        is_exact_duplicate = False
        duplicate_reason: str | None = None

        for _, row in history_df.iterrows():
            item = row.to_dict()
            p_vendor = str(item["vendor_name"]).lower()
            p_product = str(item["product_name"]).lower()
            p_dept = str(item["department"]).lower()

            vendor_match = query_str and (query_str in p_vendor or p_vendor in query_str)
            product_match = query_str and (query_str in p_product or p_product in query_str)
            dept_match = bool(team_str and (team_str in p_dept or p_dept in team_str))

            if vendor_match or product_match or (team_str and dept_match):
                rec = {
                    "purchase_id": item["purchase_id"],
                    "purchase_date": item["purchase_date"],
                    "department": item["department"],
                    "vendor_name": item["vendor_name"],
                    "product_name": item["product_name"],
                    "annual_amount_usd": float(item["annual_amount_usd"]),
                    "status": item["status"],
                    "notes": item.get("notes", ""),
                }
                records.append(rec)

                # Check for active duplicate purchase in same team or company-wide
                if (vendor_match or product_match) and (not team_str or dept_match or "company-wide" in str(item.get("notes", "")).lower()):
                    is_exact_duplicate = True
                    duplicate_reason = f"Active purchase found: {item['purchase_id']} ({item['product_name']} for {item['department']}, ${item['annual_amount_usd']}/yr)"

        data = {
            "query": vendor_or_tool,
            "department_filter": team,
            "purchase_count": len(records),
            "purchases": records,
            "is_existing_purchase": is_exact_duplicate,
            "existing_purchase_summary": duplicate_reason,
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
            error=f"Error querying purchase history: {str(exc)}",
            tool_call_id=tool_call_id,
        )
