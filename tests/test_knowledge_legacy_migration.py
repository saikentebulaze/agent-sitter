from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from runtime.knowledge_tool import build_legacy_migration, safe_output


class LegacyKnowledgeMigrationTests(unittest.TestCase):
    def test_plan_maps_kind_and_requires_explicit_split_statuses(self) -> None:
        values = [{
            "id": "flow-1",
            "title": "Flow",
            "kind": "flow",
            "status": "current",
            "path": "knowledge/flow.md",
            "domains": [],
            "keywords": [],
            "related": [],
        }]
        candidate = build_legacy_migration(
            values,
            evidence_status="candidate",
            architecture_status="legacy",
        )
        entry = candidate["entries"][0]
        self.assertEqual(entry["type"], "flow")
        self.assertEqual(entry["evidence_status"], "candidate")
        self.assertEqual(entry["architecture_status"], "legacy")
        self.assertNotIn("kind", entry)
        self.assertNotIn("status", entry)

    def test_sparse_legacy_entry_gets_only_structural_defaults(self) -> None:
        candidate = build_legacy_migration(
            [{
                "id": "multi-case-analysis-update",
                "title": "Multi-case update",
                "kind": "flow",
                "status": "current",
                "path": "flows/multi-case-analysis-update.md",
            }],
            evidence_status="candidate",
            architecture_status="legacy",
        )
        entry = candidate["entries"][0]
        self.assertEqual(
            entry["path"],
            "knowledge/flows/multi-case-analysis-update.md",
        )
        self.assertEqual(entry["domains"], [])
        self.assertEqual(entry["keywords"], [])
        self.assertEqual(entry["related"], [])

    def test_unknown_legacy_kind_requires_manual_mapping(self) -> None:
        with self.assertRaisesRegex(ValueError, "manual mapping"):
            build_legacy_migration(
                [{
                    "id": "x",
                    "title": "X",
                    "kind": "module",
                    "status": "current",
                    "path": "knowledge/x.md",
                    "domains": [],
                    "keywords": [],
                    "related": [],
                }],
                evidence_status="candidate",
                architecture_status="legacy",
            )

    def test_unsafe_legacy_path_requires_manual_mapping(self) -> None:
        with self.assertRaisesRegex(ValueError, "manual mapping"):
            build_legacy_migration(
                [{
                    "id": "x",
                    "title": "X",
                    "kind": "flow",
                    "status": "current",
                    "path": "../outside.md",
                }],
                evidence_status="candidate",
                architecture_status="legacy",
            )

    def test_current_index_is_not_rewritten_as_a_migration(self) -> None:
        values = [{
            "id": "flow-1",
            "title": "Flow",
            "type": "flow",
            "evidence_status": "verified",
            "architecture_status": "current",
            "path": "knowledge/flow.md",
            "domains": [],
            "keywords": [],
            "related": [],
        }]
        with self.assertRaisesRegex(ValueError, "no legacy"):
            build_legacy_migration(
                values,
                evidence_status="candidate",
                architecture_status="legacy",
            )

    def test_migration_output_cannot_replace_source_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "knowledge" / "index.yaml"
            source.parent.mkdir(parents=True)
            source.write_text(yaml.safe_dump({"version": 1, "entries": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "never overwrites"):
                safe_output(project, Path("knowledge/index.yaml"))


if __name__ == "__main__":
    unittest.main()
