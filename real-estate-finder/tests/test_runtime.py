from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from real_estate_finder import cli
from real_estate_finder.runtime import ensure_edge_debugging, find_edge_executable


class EdgeRuntimeTests(unittest.TestCase):
    @patch("real_estate_finder.runtime.debug_endpoint_ready")
    def test_empty_endpoint_uses_collectors_persistent_profile(self, ready) -> None:
        ensure_edge_debugging("")
        ready.assert_not_called()

    @patch("real_estate_finder.runtime.debug_endpoint_ready", return_value=True)
    @patch("real_estate_finder.runtime.subprocess.Popen")
    def test_ready_endpoint_does_not_start_edge(self, popen, _ready) -> None:
        ensure_edge_debugging()
        popen.assert_not_called()

    @patch("real_estate_finder.runtime.debug_endpoint_ready", return_value=False)
    def test_custom_endpoint_is_not_replaced_with_local_edge(self, _ready) -> None:
        with self.assertRaisesRegex(RuntimeError, "응답하지 않습니다"):
            ensure_edge_debugging("http://example.test:9222")

    @patch.dict(os.environ, {"ProgramFiles(x86)": r"C:\Program Files (x86)"}, clear=True)
    @patch("real_estate_finder.runtime.Path.is_file", return_value=True)
    def test_finds_edge_in_program_files(self, _is_file) -> None:
        self.assertEqual(
            find_edge_executable(),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        )


class ScanWorkflowTests(unittest.TestCase):
    @patch("real_estate_finder.cli._collect_and_post", return_value=True)
    @patch("real_estate_finder.cli.NaverBrowserCollector")
    @patch("real_estate_finder.cli.ensure_edge_debugging")
    @patch("real_estate_finder.cli._check_api")
    @patch("real_estate_finder.cli.ReportSiteClient")
    def test_workflow_prepares_dependencies_and_collects(
        self, client_class, check_api, ensure_edge, collector_class, collect
    ) -> None:
        result = cli.run_scan_workflow()

        self.assertTrue(result)
        check_api.assert_called_once_with(client_class.return_value)
        ensure_edge.assert_called_once_with("http://127.0.0.1:9222")
        collector_class.return_value.open_login.assert_called_once_with()
        collect.assert_called_once_with(
            collector_class.return_value, client_class.return_value, smoke=False
        )


if __name__ == "__main__":
    unittest.main()
