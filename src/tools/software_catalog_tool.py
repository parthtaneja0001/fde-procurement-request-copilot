from __future__ import annotations

import difflib
import re
from typing import Any
from src.data_access import load_software_catalog
from src.tools.base import make_tool_response


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def search_software_catalog(
    query: str,
    category: str | None = None,
    tool_call_id: str | None = None,
) -> dict[str, Any]:
    """Search approved company software catalog for existing tools by name, category, vendor, or purpose."""
    source = "search_software_catalog"
    try:
        catalog_df = load_software_catalog()
        matches: list[dict[str, Any]] = []

        query_lower = query.strip().lower() if query else ""
        query_tokens = _tokenize(query_lower)
        category_lower = category.strip().lower() if category else None

        for _, row in catalog_df.iterrows():
            item = row.to_dict()
            prod_name = str(item["product_name"]).lower()
            cat_name = str(item["category"]).lower()
            vendor_name = str(item["vendor_name"]).lower()
            notes = str(item.get("notes", "")).lower()

            relevance_reasons: list[str] = []
            score = 0.0

            # Direct/fuzzy product name match
            if query_lower and (query_lower in prod_name or prod_name in query_lower):
                relevance_reasons.append("Exact/substring product name match")
                score += 1.0
            else:
                sim = difflib.SequenceMatcher(None, query_lower, prod_name).ratio()
                if sim >= 0.6:
                    relevance_reasons.append(f"Fuzzy product name similarity ({sim:.2f})")
                    score += sim

            # Vendor match
            if query_lower and (query_lower in vendor_name or vendor_name in query_lower):
                relevance_reasons.append("Vendor name match")
                score += 0.8

            # Category match
            if category_lower and (category_lower in cat_name or cat_name in category_lower):
                relevance_reasons.append("Category match")
                score += 0.7

            # Token overlap in description/notes
            item_tokens = _tokenize(f"{prod_name} {cat_name} {notes}")
            common_tokens = query_tokens.intersection(item_tokens) - {"the", "and", "a", "for", "to", "in", "with", "ai", "tool", "app"}
            if common_tokens:
                relevance_reasons.append(f"Keyword match: {', '.join(sorted(common_tokens))}")
                score += 0.3 * len(common_tokens)

            if score > 0.3 or (category_lower and category_lower in cat_name):
                matches.append({
                    "software_id": item["software_id"],
                    "product_name": item["product_name"],
                    "category": item["category"],
                    "vendor_name": item["vendor_name"],
                    "status": item["status"],
                    "annual_cost_usd": float(item["annual_cost_usd"]),
                    "licensed_seats": int(item["licensed_seats"]),
                    "scope": item["scope"],
                    "notes": item.get("notes", ""),
                    "relevance_score": round(score, 2),
                    "match_reasons": relevance_reasons,
                })

        matches.sort(key=lambda x: x["relevance_score"], reverse=True)

        # Determine overlap
        has_overlap = len(matches) > 0 and (
            any(m["relevance_score"] >= 0.7 for m in matches)
            or any(category_lower and category_lower in m["category"].lower() for m in matches)
        )

        data = {
            "query": query,
            "category_filter": category,
            "match_count": len(matches),
            "has_overlap": has_overlap,
            "exact_matches": [m for m in matches if m["relevance_score"] >= 0.8],
            "potential_alternatives": matches,
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
            error=f"Error searching software catalog: {str(exc)}",
            tool_call_id=tool_call_id,
        )
