#!/usr/bin/env python3
"""Unit tests for declarative CRAB config literal parsing."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("crab_config_literals.py")
MODULE_SPEC = importlib.util.spec_from_file_location("crab_config_literals", MODULE_PATH)
literals = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
sys.modules[MODULE_SPEC.name] = literals
MODULE_SPEC.loader.exec_module(literals)


class CrabConfigLiteralsTest(unittest.TestCase):
    def test_parse_literal_crab_config_supports_multiline_lists(self) -> None:
        source = (
            "from WMCore.Configuration import Configuration\n"
            "config = Configuration()\n"
            "config.section_('General')\n"
            "config.General.requestName = 'sample'\n"
            "config.section_('JobType')\n"
            "config.JobType.pyCfgParams = [\n"
            "    'runOnMC=False',\n"
            "    'era=Run2024H',\n"
            "    'outputFile=sample.root',\n"
            "]\n"
            "config.section_('Data')\n"
            "config.Data.unitsPerJob = 20\n"
            "config.Data.publication = False\n"
        )
        parsed = literals.parse_literal_crab_config(source, source_name="sample.py")
        self.assertEqual(parsed.section_order, ["General", "JobType", "Data"])
        self.assertEqual(parsed.get_field("General", "requestName"), "sample")
        self.assertEqual(
            parsed.get_field("JobType", "pyCfgParams"),
            ["runOnMC=False", "era=Run2024H", "outputFile=sample.root"],
        )
        self.assertEqual(parsed.get_field("Data", "unitsPerJob"), 20)

    def test_merge_literal_assignments_preserves_unrestated_fields(self) -> None:
        base = literals.parse_literal_crab_config(
            "from WMCore.Configuration import Configuration\n"
            "config = Configuration()\n"
            "config.section_('General')\n"
            "config.General.requestName = 'parent'\n"
            "config.section_('Site')\n"
            "config.Site.storageSite = 'T2_TEST_SITE'\n",
            source_name="base.py",
        )
        override = literals.parse_literal_crab_config(
            "from WMCore.Configuration import Configuration\n"
            "config = Configuration()\n"
            "config.section_('General')\n"
            "config.General.requestName = 'child'\n",
            source_name="override.py",
        )
        merged = literals.merge_literal_assignments(base, override)
        self.assertEqual(merged.get_field("General", "requestName"), "child")
        self.assertEqual(merged.get_field("Site", "storageSite"), "T2_TEST_SITE")

    def test_load_cfg_metadata_via_literals_reads_core_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "sample_cfg.py"
            cfg_path.write_text(
                "from WMCore.Configuration import Configuration\n"
                "config = Configuration()\n"
                "config.section_('General')\n"
                "config.General.requestName = 'sample_cfg'\n"
                "config.section_('Data')\n"
                "config.Data.unitsPerJob = 10\n"
                "config.Data.publication = True\n"
                "config.Data.outputDatasetTag = 'sample'\n"
                "config.Data.lumiMask = '/tmp/chiw/lumi.json'\n"
            )
            metadata = literals.load_cfg_metadata_via_literals(cfg_path)
            self.assertEqual(metadata["request_name"], "sample_cfg")
            self.assertEqual(metadata["units_per_job"], 10)
            self.assertTrue(metadata["publication_enabled"])
            self.assertEqual(metadata["output_dataset_tag"], "sample")
            self.assertEqual(metadata["lumi_mask"], "/tmp/chiw/lumi.json")

    def test_parse_literal_crab_config_rejects_non_literal_assignment(self) -> None:
        source = (
            "from WMCore.Configuration import Configuration\n"
            "config = Configuration()\n"
            "params = ['runOnMC=False']\n"
            "config.section_('JobType')\n"
            "config.JobType.pyCfgParams = params\n"
        )
        with self.assertRaisesRegex(ValueError, "Unsupported CRAB config syntax"):
            literals.parse_literal_crab_config(source, source_name="bad.py")


if __name__ == "__main__":
    unittest.main()
