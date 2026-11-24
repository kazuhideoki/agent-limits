from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import agent_limits
import limits_dashboard as dashboard


class DashboardTests(unittest.TestCase):
  def test_agy_group_and_unscheduled_reset(self):
    record = {"window": "Five Hour Limit Remaining", "group": "<group>",
              "remaining_percent": 0, "reset_at": "1970-01-01T00:00:00Z"}
    row, other = dashboard.model_rows("Antigravity", "", [record], datetime.now().astimezone())
    self.assertFalse(other)
    self.assertIn("&lt;group&gt;", row)
    self.assertIn("リセット時刻不明", row)
    self.assertIn("0<span>%", row)

  def test_partial_failure_still_writes_credits(self):
    credits = [{"status": "available", "expires_at": "2099-01-01T00:00:00Z"}, {"status": "used"}]
    with TemporaryDirectory() as directory, patch.object(
        dashboard, "codex_records", side_effect=[SystemExit("offline"), credits]):
      target = Path(directory) / "snapshot.html"
      self.assertEqual(agent_limits.main(["codex", "--html", str(target)]), 1)
      html = target.read_text()
      self.assertIn("取得失敗", html)
      self.assertIn("利用可能 1枚", html)
      self.assertIn("使用済み", html)
      self.assertNotIn("サンプルデータ", html)
