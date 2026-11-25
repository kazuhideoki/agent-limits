import contextlib
import io
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
import time
import unittest
from unittest.mock import patch

import agent_limits as limits


class ProviderTests(unittest.TestCase):
  def test_claude_roundtrip_keeps_only_quota_and_hides_expired(self):
    with TemporaryDirectory() as directory:
      path = Path(directory) / "claude.json"
      payload = {"private": "transcript", "rate_limits": {
        "five_hour": {"used_percentage": 0, "resets_at": time.time() + 500},
        "seven_day": {"used_percentage": 90, "resets_at": time.time() - 1}}}
      limits.capture_claude(payload, path)
      limits.capture_claude({}, path)
      self.assertNotIn("private", path.read_text())
      self.assertEqual(path.stat().st_mode & 0o777, 0o600)
      with patch.object(limits, "cache_path", return_value=path), contextlib.redirect_stdout(io.StringIO()) as out:
        self.assertEqual(limits.main(["claude"]), 0)
      self.assertIn("100%", out.getvalue())
      self.assertNotIn("週間利用上限", out.getvalue())

  def test_agy_and_gemini_alias_read_usage(self):
    output = "Gemini Models\tWeekly Limit Remaining\t0%\t2026-11-30T04:45:19Z\n"
    for name in ("agy", "gemini"):
      with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output)) as run, \
          contextlib.redirect_stdout(io.StringIO()) as out:
        self.assertEqual(limits.main([name]), 0)
        self.assertEqual(run.call_args.args[0][-2:], ["-p", "/usage"])
        self.assertEqual(run.call_args.kwargs["cwd"], gettempdir())
        self.assertIn("Gemini Models · Weekly Limit Remaining", out.getvalue())
        self.assertIn("0%", out.getvalue())

  def test_overview_continues_after_provider_error(self):
    with patch.object(limits.ui, "show_codex", side_effect=SystemExit("offline")), \
        patch.object(limits, "show_claude", return_value=0) as claude, \
        patch.object(limits, "show_agy", return_value=0) as gemini, \
        contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
      self.assertEqual(limits.main([]), 1)
      claude.assert_called_once()
      gemini.assert_called_once()
