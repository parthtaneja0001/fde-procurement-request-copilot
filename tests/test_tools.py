from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from src.tools.employee_budget_tool import get_employee_and_budget
from src.tools.policy_tool import check_policy_and_approvals
from src.tools.purchase_history_tool import get_purchase_history
from src.tools.software_catalog_tool import search_software_catalog
from src.tools.vendor_tool import get_vendor_security_status


class CoreToolsTests(unittest.TestCase):
    def test_employee_and_budget_existing(self):
        res = get_employee_and_budget("E001")
        self.assertTrue(res["ok"])
        self.assertEqual(res["source"], "get_employee_and_budget")
        self.assertIn("tool_call_id", res)
        self.assertIn("timestamp", res)
        self.assertEqual(res["data"]["employee"]["name"], "Sarah Lee")
        self.assertEqual(res["data"]["employee"]["department"], "Marketing")
        self.assertEqual(res["data"]["department_budget"]["available_usd"], 15000.0)

    def test_employee_and_budget_missing(self):
        res = get_employee_and_budget("E999_UNKNOWN")
        self.assertFalse(res["ok"])
        self.assertIn("not found", res["error"])

    def test_software_catalog_exact_and_fuzzy(self):
        res = search_software_catalog(query="PixelCraft", category="Design & Creative")
        self.assertTrue(res["ok"])
        self.assertGreater(res["data"]["match_count"], 0)
        self.assertEqual(res["data"]["exact_matches"][0]["vendor_name"], "PixelCraft")

    def test_software_catalog_category_overlap(self):
        res = search_software_catalog(query="SomethingNew", category="Observability")
        self.assertTrue(res["ok"])
        matches = [m["product_name"] for m in res["data"]["potential_alternatives"]]
        self.assertIn("SignalWatch", matches)

    def test_purchase_history_duplicate(self):
        res = get_purchase_history(vendor_or_tool="TaskFlow", team="Operations")
        self.assertTrue(res["ok"])
        self.assertTrue(res["data"]["is_existing_purchase"])
        self.assertGreater(res["data"]["purchase_count"], 0)

    def test_policy_threshold_boundary_1000_exact(self):
        res = check_policy_and_approvals(cost=1000.00, data_sensitivity="internal_documents")
        roles = res["data"]["roles_list"]
        self.assertEqual(roles, ["Manager"])

    def test_policy_threshold_boundary_1000_01(self):
        res = check_policy_and_approvals(cost=1000.01, data_sensitivity="internal_documents")
        roles = res["data"]["roles_list"]
        self.assertIn("Department Head", roles)
        self.assertIn("Procurement", roles)
        self.assertNotIn("Finance", roles)
        self.assertNotIn("CFO", roles)

    def test_policy_threshold_boundary_10000_exact(self):
        res = check_policy_and_approvals(cost=10000.00, data_sensitivity="internal_documents")
        roles = res["data"]["roles_list"]
        self.assertEqual(roles, ["Department Head", "Procurement"])

    def test_policy_threshold_boundary_10000_01(self):
        res = check_policy_and_approvals(cost=10000.01, data_sensitivity="internal_documents")
        roles = res["data"]["roles_list"]
        self.assertIn("Department Head", roles)
        self.assertIn("Finance", roles)
        self.assertIn("Procurement", roles)
        self.assertNotIn("CFO", roles)

    def test_policy_threshold_boundary_25000_exact(self):
        res = check_policy_and_approvals(cost=25000.00, data_sensitivity="internal_documents")
        roles = res["data"]["roles_list"]
        self.assertEqual(roles, ["Department Head", "Finance", "Procurement"])

    def test_policy_threshold_boundary_25000_01(self):
        res = check_policy_and_approvals(cost=25000.01, data_sensitivity="internal_documents")
        roles = res["data"]["roles_list"]
        self.assertEqual(roles, ["Department Head", "Finance", "CFO", "Procurement"])

    def test_policy_budget_exceeded(self):
        res = check_policy_and_approvals(cost=22000.00, available_budget=18000.00)
        flags = [rf["flag"] for rf in res["data"]["risk_flags"]]
        self.assertIn("budget_insufficient", flags)
        self.assertTrue(res["data"]["has_hard_blocks"])
        self.assertIn("Finance", res["data"]["roles_list"])

    def test_policy_sensitive_data_triggers_security(self):
        res = check_policy_and_approvals(cost=500.0, data_sensitivity="source_code")
        roles = res["data"]["roles_list"]
        self.assertIn("Security", roles)
        flags = [rf["flag"] for rf in res["data"]["risk_flags"]]
        self.assertIn("security_review_required", flags)

    def test_policy_pii_triggers_privacy(self):
        res = check_policy_and_approvals(cost=500.0, data_sensitivity="customer_pii")
        roles = res["data"]["roles_list"]
        self.assertIn("Privacy", roles)
        self.assertIn("Security", roles)

    def test_policy_new_vendor_high_cost_triggers_legal(self):
        res = check_policy_and_approvals(cost=15000.0, is_new_vendor=True)
        roles = res["data"]["roles_list"]
        self.assertIn("Legal", roles)

    def test_vendor_security_tool_outage(self):
        # NimbusAI is configured to return 503 in mock api
        # When mock API is called or with mocked error:
        with patch("src.tools.vendor_tool._call_vendor_risk_api_with_retry") as mock_call:
            mock_call.return_value = (False, None, "HTTP 503 Service Unavailable")
            res = get_vendor_security_status("NimbusAI")
            self.assertFalse(res["ok"])
            self.assertIn("unavailable", res["error"].lower())
            self.assertFalse(res["data"]["api_available"])

    def test_vendor_security_tool_expired(self):
        with patch("src.tools.vendor_tool._call_vendor_risk_api_with_retry") as mock_call:
            mock_call.return_value = (
                True,
                {
                    "vendor_name": "SignalWatch",
                    "risk_level": "medium",
                    "security_review_status": "expired",
                    "last_review_date": "2025-07-01",
                    "processes_personal_data": False,
                    "stores_data_outside_region": False,
                },
                None,
            )
            res = get_vendor_security_status("SignalWatch")
            self.assertTrue(res["ok"])
            self.assertTrue(res["data"]["is_review_expired"])
            self.assertTrue(res["data"]["has_conflict"])


if __name__ == "__main__":
    unittest.main()
