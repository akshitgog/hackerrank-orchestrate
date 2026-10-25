"""Regression checks for evidence-bound worker-resource attribution."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from pathlib import Path

from code.src.audit_agent.attribution import AttributionIndex, resource_prefix
from code.src.audit_agent.scanner import AuditScanner
from code.src.logging_agent.tracker import IdentityTracker


class AttributionFixture:
    """Small synthetic dataset builder for attribution-only regressions."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.evidence_dir = root / "evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._resource_number = 1000

    def resource(self, prefix: str) -> str:
        self._resource_number += 1
        return f"{prefix}_{self._resource_number}"

    def write_csv(self, name: str, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
        with (self.root / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def write_common_files(
        self,
        *,
        users: list[tuple[str, str]],
        cases: list[dict[str, object]],
        evidence: list[dict[str, object]],
        activity: list[dict[str, object]],
    ) -> None:
        self.write_csv(
            "user_identities.csv",
            [
                {
                    "user_id": user_id,
                    "email": email,
                    "name": user_id.replace("_", " "),
                    "phone": "",
                    "email_hash": "",
                }
                for user_id, email in users
            ],
            ["user_id", "email", "name", "phone", "email_hash"],
        )
        self.write_csv(
            "user_audit_log.csv",
            [],
            ["user_id", "event_time", "field_name", "old_value", "new_value"],
        )
        self.write_csv(
            "deletion_requests.csv",
            cases,
            [
                "case_id",
                "email",
                "requested_at",
                "reported_at",
                "audit_at",
                "reported_status",
                "request_text",
            ],
        )
        self.write_csv(
            "evidence_files.csv",
            evidence,
            ["file_id", "file_path", "captured_at", "origin"],
        )
        self.write_csv(
            "system_activity.csv",
            activity,
            [
                "activity_id",
                "event_time",
                "source_system",
                "event_type",
                "target_system",
                "resource_id",
                "reported_result",
            ],
        )
        self.write_csv("deletion_rules.csv", [], ["data_category", "required_action"])

    def write_json(self, relative_path: str, payload: object) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


class TestAttributionRegressions(unittest.TestCase):
    """Protect evidence locality, bounded assignment, and inferred-target rules."""

    def _case(
        self,
        case_id: str,
        email: str,
        *,
        reported_at: str = "2026-01-02T12:00:00Z",
        reported_status: str = "COMPLETE",
        request_text: str = "Please delete my account and personal data.",
    ) -> dict[str, object]:
        return {
            "case_id": case_id,
            "email": email,
            "requested_at": "2026-01-01T00:00:00Z",
            "reported_at": reported_at,
            "audit_at": "2026-01-03T00:00:00Z",
            "reported_status": reported_status,
            "request_text": request_text,
        }

    def _activity(
        self,
        activity_id: str,
        event_time: str,
        resource_id: str,
        *,
        event_type: str = "DELETE_RECORD",
        result: str = "SUCCESS",
    ) -> dict[str, object]:
        return {
            "activity_id": activity_id,
            "event_time": event_time,
            "source_system": "deletion_worker",
            "event_type": event_type,
            "target_system": "account_service",
            "resource_id": resource_id,
            "reported_result": result,
        }

    def test_signal_is_local_to_the_matching_evidence_record(self) -> None:
        """A clean record must not inherit a violation marker from a sibling record."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = AttributionFixture(Path(temp_dir))
            case_alpha = "case_alpha"
            case_beta = "case_beta"
            account_alpha = fixture.resource("account")
            account_beta = fixture.resource("account")
            orphan_search = fixture.resource("search")
            evidence_id = "evidence_local"
            fixture.write_json(
                "evidence/local.json",
                {
                    "records": [
                        {
                            "resource_id": account_alpha,
                            "customer_reference": "user_alpha",
                            "account_status": "ACTIVE",
                        },
                        {
                            "resource_id": account_beta,
                            "customer_reference": "user_beta",
                            "account_status": "DELETED",
                        },
                    ]
                },
            )
            fixture.write_common_files(
                users=[
                    ("user_alpha", "alpha@example.test"),
                    ("user_beta", "beta@example.test"),
                ],
                cases=[
                    self._case(case_alpha, "alpha@example.test"),
                    self._case(case_beta, "beta@example.test"),
                ],
                evidence=[
                    {
                        "file_id": evidence_id,
                        "file_path": "evidence/local.json",
                        "captured_at": "2026-01-02T00:00:00Z",
                        "origin": "account_service",
                    }
                ],
                activity=[self._activity("activity_orphan", "2026-01-02T12:10:00Z", orphan_search)],
            )

            index = AttributionIndex(fixture.root)

            # The public assignment result is sensitive to the local signal:
            # the non-account orphan may go to the clean case, but not the case
            # whose own record is active.
            self.assertIn(orphan_search, index.resources_for(case_beta))
            self.assertNotIn(orphan_search, index.resources_for(case_alpha))
            self.assertEqual(index.source_for(case_beta, orphan_search).split(":", 1)[0], "batch")

    def test_orphan_worker_batches_are_bounded_and_disjoint(self) -> None:
        """At most one inferred resource of each type belongs to a case."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = AttributionFixture(Path(temp_dir))
            case_alpha = "case_alpha"
            case_beta = "case_beta"
            orphan_accounts = [fixture.resource("account"), fixture.resource("account")]
            orphan_search = fixture.resource("search")
            fixture.write_common_files(
                users=[
                    ("user_alpha", "alpha@example.test"),
                    ("user_beta", "beta@example.test"),
                ],
                cases=[
                    self._case(case_alpha, "alpha@example.test"),
                    self._case(case_beta, "beta@example.test"),
                ],
                evidence=[],
                activity=[
                    self._activity("activity_account_a", "2026-01-02T12:01:00Z", orphan_accounts[0]),
                    self._activity("activity_account_b", "2026-01-02T12:02:00Z", orphan_accounts[1]),
                    self._activity("activity_search", "2026-01-02T12:03:00Z", orphan_search),
                ],
            )

            index = AttributionIndex(fixture.root)
            assignments = {
                case_id: index.resources_for(case_id) for case_id in (case_alpha, case_beta)
            }
            all_assigned = assignments[case_alpha] | assignments[case_beta]

            self.assertEqual(all_assigned, set(orphan_accounts + [orphan_search]))
            self.assertTrue(assignments[case_alpha].isdisjoint(assignments[case_beta]))
            for resources in assignments.values():
                prefixes = [resource_prefix(resource_id) for resource_id in resources]
                self.assertEqual(len(prefixes), len(set(prefixes)))

    def test_explicit_owner_assignments_do_not_cross_cases(self) -> None:
        """Worker actions with evidence owners stay attached to that owner."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = AttributionFixture(Path(temp_dir))
            case_alpha = "case_alpha"
            case_beta = "case_beta"
            account_alpha = fixture.resource("account")
            account_beta = fixture.resource("account")
            fixture.write_json(
                "evidence/owned.json",
                {
                    "records": [
                        {"resource_id": account_alpha, "customer_reference": "user_alpha"},
                        {"resource_id": account_beta, "customer_reference": "user_beta"},
                    ]
                },
            )
            fixture.write_common_files(
                users=[
                    ("user_alpha", "alpha@example.test"),
                    ("user_beta", "beta@example.test"),
                ],
                cases=[
                    self._case(case_alpha, "alpha@example.test"),
                    self._case(case_beta, "beta@example.test"),
                ],
                evidence=[
                    {
                        "file_id": "evidence_owned",
                        "file_path": "evidence/owned.json",
                        "captured_at": "2026-01-02T00:00:00Z",
                        "origin": "account_service",
                    }
                ],
                activity=[
                    self._activity("activity_alpha", "2026-01-02T12:01:00Z", account_alpha),
                    self._activity("activity_beta", "2026-01-02T12:02:00Z", account_beta),
                ],
            )

            index = AttributionIndex(fixture.root)

            self.assertEqual(index.resources_for(case_alpha), {account_alpha})
            self.assertEqual(index.resources_for(case_beta), {account_beta})
            self.assertEqual(index.source_for(case_alpha, account_alpha), "owner_batch")
            self.assertEqual(index.source_for(case_beta, account_beta), "owner_batch")

    def test_inferred_worker_resource_is_verification_only(self) -> None:
        """An orphan worker target may add a proof, never a residual finding."""
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox = Path(temp_dir)
            dataset = sandbox / "dataset"
            dataset.mkdir()
            fixture = AttributionFixture(dataset)
            case_id = "case_alpha"
            direct_search = fixture.resource("search")
            inferred_account = fixture.resource("account")
            email = "alpha@example.test"
            audit_at = "2026-01-03T00:00:00Z"
            fixture.write_json(
                "evidence/direct.json",
                {
                    "service_exports": {
                        "search_service": {
                            "index_queries": [
                                {
                                    "resource_id": direct_search,
                                    "query": email,
                                    "hits": {
                                        "total_hits": 1,
                                        "documents": [
                                            {
                                                "resource_id": direct_search,
                                                "email": email,
                                                "customer_reference": "user_alpha",
                                            }
                                        ],
                                    },
                                }
                            ]
                        }
                    }
                },
            )
            fixture.write_common_files(
                users=[("user_alpha", email)],
                cases=[self._case(case_id, email)],
                evidence=[
                    {
                        "file_id": "evidence_direct",
                        "file_path": "evidence/direct.json",
                        "captured_at": "2026-01-02T00:00:00Z",
                        "origin": "search_service",
                    }
                ],
                activity=[
                    self._activity("activity_inferred", "2026-01-02T12:10:00Z", inferred_account),
                ],
            )

            original_cwd = Path.cwd()
            os.chdir(sandbox)
            try:
                tracker = IdentityTracker(
                    dataset / "user_identities.csv",
                    dataset / "user_audit_log.csv",
                )
                profile = tracker.get_identity_profile(email, audit_at)
                self.assertIsNotNone(profile)
                scanner = AuditScanner(
                    evidence_manifest_path=dataset / "evidence_files.csv",
                    system_activity_path=dataset / "system_activity.csv",
                    rules_path=dataset / "deletion_rules.csv",
                    cache_path=dataset / "cache.json",
                )
                result = scanner.audit_case(
                    case_id,
                    profile,
                    audit_at,
                    requested_at="2026-01-01T00:00:00Z",
                    reported_at="2026-01-02T12:00:00Z",
                )
            finally:
                os.chdir(original_cwd)

            finding_resources = {finding.resource_id for finding in result.findings}
            verification_resources = {proof.resource_id for proof in result.verifications}
            inferred_proofs = [
                proof for proof in result.verifications if proof.resource_id == inferred_account
            ]

            self.assertEqual(result.deletion_status, "INCOMPLETE")
            self.assertIn(direct_search, finding_resources)
            self.assertNotIn(inferred_account, finding_resources)
            self.assertEqual(len(inferred_proofs), 1)
            self.assertIn(inferred_account, verification_resources)
            self.assertEqual(inferred_proofs[0].evidence_id, "")


if __name__ == "__main__":
    unittest.main()
