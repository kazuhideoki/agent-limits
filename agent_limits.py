"""Terminal usage overview for Codex, Claude Code and Antigravity CLI."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import NamedTemporaryFile, gettempdir
import time

import codex_limits as ui


WINDOWS = {
  "five_hour": ("5時間の使用制限", 18000),
  "seven_day": ("週間利用上限", 604800),
}


def cache_path():
  return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "agent-limits" / "claude.json"


def number(value, limit):
  return type(value) in (int, float) and 0 <= value <= limit


def capture_claude(payload, path):
  limits = payload.get("rate_limits") if isinstance(payload, dict) else None
  if not isinstance(limits, dict):
    return
  windows = {}
  for key in WINDOWS:
    window = limits.get(key)
    if not isinstance(window, dict):
      continue
    used, reset = window.get("used_percentage"), window.get("resets_at")
    if number(used, 100) and number(reset, 253402214400):
      windows[key] = {"used_percentage": used, "resets_at": reset}
  path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
  with NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as tmp:
    try:
      json.dump({"observed": time.time(), "windows": windows}, tmp)
      tmp.flush()
      os.replace(tmp.name, path)
    finally:
      Path(tmp.name).unlink(missing_ok=True)


def read_claude():
  path = cache_path()
  if not path.exists():
    raise ValueError("利用枠の記録待ちです。Claude Code のステータスライン連携を確認してください。")
  data = ui.load_json(path)
  now = time.time()
  age_minutes = int(max(0, now - data["observed"]) // 60)
  records = []
  for key, window in data["windows"].items():
    if window["resets_at"] > now:
      label, seconds = WINDOWS[key]
      records.append({"title": label, "window_seconds": seconds, "reset_at": window["resets_at"],
                      "remaining_percent": 100 - window["used_percentage"]})
  return age_minutes, records


def live_claude_records():
  request = {"type": "control_request", "request_id": "limits",
             "request": {"subtype": "get_usage", "skip_behaviors": True}}
  result = subprocess.run(
    ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json",
     "--verbose", "--no-session-persistence", "--strict-mcp-config", "--tools", "",
     "--settings", '{"disableAllHooks":true}'],
    input=json.dumps(request) + "\n", cwd=gettempdir(), capture_output=True, text=True, timeout=20,
  )
  if result.returncode:
    raise ValueError("Claude Code の照会に失敗しました")
  for line in result.stdout.splitlines():
    message = json.loads(line)
    if message.get("type") != "control_response":
      continue
    reply = message["response"]
    if reply.get("request_id") != "limits" or reply.get("subtype") != "success":
      continue
    data = reply["response"]
    if not data.get("rate_limits_available"):
      break
    records = []
    for key, (label, seconds) in WINDOWS.items():
      window = data["rate_limits"].get(key)
      if not isinstance(window, dict) or not number(window.get("utilization"), 100):
        continue
      reset = window.get("resets_at")
      records.append({"title": label, "window_seconds": seconds, "reset_at": reset,
                      "awaiting_start": key == "five_hour" and window["utilization"] == 0 and reset is None,
                      "remaining_percent": 100 - window["utilization"]})
    if records:
      return records
  raise ValueError("Claude Code から利用枠を取得できませんでした")


def refresh_claude():
  try:
    return None, live_claude_records()
  except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
    return read_claude()


def show_claude():
  age_minutes, records = read_claude()
  print(f"Claude Code（{age_minutes} 分前に取得）")
  if records:
    print("\n".join(ui.render_current_usage_tables(ui.normalize_usage_records(records))))
  else:
    print("有効な使用枠の記録がありません。次の Claude Code 応答後に更新されます。")
  return 0


def read_agy():
  try:
    result = subprocess.run(
      ["agy", "--print-timeout", "20s", "-p", "/usage"],
      stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
    )
  except FileNotFoundError as error:
    raise ValueError("Antigravity CLI (agy) が PATH に見つかりません。") from error
  except subprocess.TimeoutExpired as error:
    raise ValueError("agy の利用枠照会がタイムアウトしました。") from error
  if result.returncode:
    raise ValueError(f"agy /usage の取得に失敗しました（終了コード {result.returncode}）。agy のログイン状態を確認してください。")

  records = []
  for line in result.stdout.splitlines():
    if not line.strip():
      continue
    fields = line.split("\t")
    if len(fields) != 4:
      raise ValueError("agy /usage の出力形式を読み取れません。")
    group, window, percent, reset = fields
    if not percent.endswith("%") or not number(ui.number_from_value(percent[:-1]), 100):
      raise ValueError("agy /usage の残量を読み取れません。")
    title = window if window.startswith(group + " ") else f"{group} · {window}"
    records.append({"title": title, "group": group, "window": window, "remaining_percent": percent[:-1], "reset_at": reset})
  if not records:
    raise ValueError("agy /usage から利用枠が返りませんでした。")
  return records


def show_agy():
  records = read_agy()
  print("Antigravity CLI (agy)")
  print("\n".join(ui.render_current_usage_tables(ui.normalize_usage_records(records))))
  return 0


def main(argv=None):
  parser = argparse.ArgumentParser(prog="agent-limits", description="各サービスの使用枠を表示")
  parser.add_argument("service", nargs="?", choices=("codex", "claude", "agy", "gemini", "capture-claude"))
  parser.add_argument("--history", action="store_true", help="Codex の履歴を追加")
  parser.add_argument("--html", metavar="FILE", type=Path, help="現在の利用枠を単体HTMLに保存")
  parser.add_argument("--serve", action="store_true", help="再読み込みで更新するローカル画面を起動")
  args = parser.parse_args(argv)
  if args.serve:
    if args.history or args.html or args.service == "capture-claude":
      parser.error("--serve は --html、--history、capture-claude と併用できません")
    from limits_server import serve
    return serve(args.service, refresh_claude, read_agy)
  if args.html:
    if args.history or args.service == "capture-claude":
      parser.error("--html は現在の利用枠の表示に指定してください")
    from limits_dashboard import write_dashboard
    return write_dashboard(args.html, args.service, read_claude, read_agy)
  if args.history and args.service not in (None, "codex"):
    parser.error("--history は一覧または codex で指定してください")
  if args.service == "capture-claude":
    capture_claude(json.load(sys.stdin), cache_path())
    return 0
  providers = {"codex": lambda: ui.show_codex(args.history), "claude": show_claude, "agy": show_agy}
  if args.service == "gemini":
    args.service = "agy"
  status = 0
  for index, name in enumerate([args.service] if args.service else providers):
    if index:
      print()
    try:
      status |= providers[name]()
    except (OSError, ValueError, SystemExit, KeyError, TypeError) as error:
      print(f"{name}: {error}", file=sys.stderr)
      status = 1
  return status
