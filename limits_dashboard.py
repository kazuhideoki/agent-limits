"""Render a local snapshot of the providers' current limits."""
from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
import math
import re
from string import Template
import sys
from tempfile import NamedTemporaryFile

import codex_limits as ui

PERIODS = {"short": ("5時間枠", 18000), "week": ("週間枠", 604800)}
ERRORS = (OSError, ValueError, SystemExit, KeyError, TypeError, OverflowError)


def duration(end, now):
  minutes = math.ceil((end - now).total_seconds() / 60)
  if minutes <= 0:
    return "期限到達"
  days, hours = divmod(minutes // 60, 24)
  if days:
    return f"あと{days}日" + (f"{hours}時間" if hours else "")
  return "あと" + (f"{hours}時間" if hours else "") + (f"{minutes % 60}分" if minutes % 60 else "")


def date_label(value):
  return value.astimezone(ui.ACTIVE_TIMEZONE).strftime("%m/%d %H:%M")


def period_for(record):
  seconds = ui.first_number(record, ("window_seconds", "windowSeconds", "limit_window_seconds", "limitWindowSeconds"))
  for period, (_, length) in PERIODS.items():
    if seconds == length:
      return period
  window = record.get("window", "").lower()
  if re.search(r"weekly|7[ -]?days?|週間", window):
    return "week"
  if re.search(r"(?:5|five)[ -]?(?:hours?|hrs?|h\b|時間)", window):
    return "short"
  return None


def quota(record, seconds, now):
  remaining = ui.percent_number_from_display(ui.usage_remaining(record))
  reset_value = ui.first_present(record, ("reset_at", "resetAt", "resets_at", "resetsAt", "next_reset_at", "nextResetAt", "refresh_at", "refreshAt"))
  reset = ui.parse_datetime_value(reset_value)
  if reset and reset.timestamp() <= 0:
    reset = None
  time_left = ui.window_remaining_percent(reset_value, seconds, now) if reset else None
  amount = "不明"
  fill = ""
  if remaining is not None and 0 <= remaining <= 100:
    amount = f'{remaining:g}<span>%</span>'
    fill = f'<i style="width:{remaining}%"></i>'
  period_label = "不明"
  background = ""
  if time_left is not None:
    period_label = f"{time_left:.0f}%"
    background = f'<span class="period-fill" style="width:{time_left}%"></span>'
  color = " low" if fill and time_left is not None and remaining < time_left else ""
  reset_label = f"{date_label(reset)} リセット" if reset else "リセット時刻不明"
  return (f'<div class="meter-label"><span>利用枠残り <strong class="value">{amount}</strong></span>'
          f'<span>期間残り <strong>{period_label}</strong></span></div>'
          f'<div class="bar overlay{color}" aria-hidden="true">{background}{fill}</div><div class="labels">'
          f'<strong>{duration(reset, now) if reset else ""}</strong>{reset_label}</div>')



def model_rows(name, subtitle, records, now, empty="該当枠なし"):
  groups = defaultdict(lambda: defaultdict(list))
  others = []
  for record in records:
    group = record.get("group") or subtitle
    period = period_for(record)
    if period:
      groups[group][period].append(quota(record, PERIODS[period][1], now))
    else:
      others.append(f'<li>{escape(name)} · {escape(ui.usage_name(record))}{quota(record, None, now)}</li>')
  rows = []
  for group, cells in (groups or {subtitle: {}}).items():
    rows.append(f'<div class="model"><strong>{escape(name)}</strong><small>{escape(group)}</small></div>')
    for period, (label, _) in PERIODS.items():
      content = '<hr>'.join(cells.get(period, [])) or escape(empty)
      rows.append(f'<div class="cell" data-period="{period}"><span class="mobile">{label}</span>{content}</div>')
  return ''.join(rows), ''.join(others)


def ticket_section(records, now):
  tickets = []
  count = 0
  for record in records:
    expiry = ui.parse_datetime_value(ui.first_present(record, ("expires_at", "expiresAt", "expiration", "expiration_at", "expirationAt")))
    status = ui.display_value(ui.first_present(record, ("status", "state"))).lower()
    redeemed = ui.display_reset_redeemed(record)
    if redeemed == "yes" or status in ("used", "redeemed"):
      label = "使用済み"
    elif status == "expired" or (expiry and expiry <= now):
      label = "失効"
    elif redeemed == "no" and status in ("available", "active", "unused", "unknown"):
      label = "利用可能"
      count += 1
    else:
      label = "状態不明"
    valid = label == "利用可能"
    remaining = duration(expiry, now) if valid and expiry else label
    expires = f'{date_label(expiry)} 失効' if expiry else '失効日時不明'
    bar = ""
    urgency = ""
    if valid and expiry:
      days = (expiry - now).total_seconds() / 86400
      percent = min(100, 100 * days / ui.DEFAULT_RESET_FULL_DAYS)
      urgency = ui.reset_urgency(days)
      bar = f'<div class="bar credit-bar"><i style="width:{percent:.2f}%"></i></div>'
    row = (f'<li class="credit {urgency}"><strong>{remaining}</strong>'
           f'<div>{bar}</div><span>{expires}</span></li>')
    tickets.append((not valid, expiry.timestamp() if expiry else math.inf, row))
  listing = ''.join(row for _, _, row in sorted(tickets))
  return (f'<section class="tickets"><h2>Codex リセットチケット <small>利用可能 {count}枚</small></h2>'
          f'<small>失効までの残り時間（満幅＝{ui.DEFAULT_RESET_FULL_DAYS:g}日）</small><ul>{listing}</ul></section>')


def codex_records(url, label, extract):
  payload = ui.fetch_response(ui.DEFAULT_AUTH_PATH, url, ui.DEFAULT_TIMEOUT_SECONDS, label)
  return extract(payload)


def collect_dashboard(service, read_claude, read_agy):
  now = datetime.now(ui.ACTIVE_TIMEZONE)
  rows, others = [], []
  tickets = ""
  status = 0
  providers = {"codex": "Codex", "claude": "Claude Code", "agy": "Antigravity"}
  selected = ["agy" if service == "gemini" else service] if service else providers
  for key in selected:
    name = providers[key]
    subtitle = "共通枠"
    empty = "該当枠なし"
    try:
      if key == "codex":
        records = codex_records(ui.DEFAULT_USAGE_URL, "usage limits", ui.find_usage_records)
      elif key == "claude":
        age, records = read_claude()
        age_label = f"{age // 60}時間{age % 60}分" if age >= 60 else f"{age}分"
        subtitle += f" · {age_label}前に取得"
        empty = "有効な記録なし"
      else:
        records = read_agy()
      row, other = model_rows(name, subtitle, records, now, empty)
    except ERRORS as error:
      print(f"{name}: {error}", file=sys.stderr)
      status = 1
      row, other = model_rows(name, "", [], now, "取得失敗")
    rows.append(row)
    others.append(other)
    if key == "codex":
      try:
        credits = codex_records(ui.DEFAULT_RESETS_URL, "reset credits", ui.find_reset_credit_records)
        tickets = ticket_section(credits, now)
      except ERRORS as error:
        print(f"リセットチケット: {error}", file=sys.stderr)
        status = 1
        tickets = '<section class="tickets"><h2>Codex リセットチケット</h2>取得失敗</section>'
  other = ''.join(others)
  return {
    "snapshot": now.strftime("%Y/%m/%d %H:%M:%S JST 時点"),
    "rows": ''.join(rows),
    "other": f'<section class="tickets"><h2>その他の枠</h2><ul>{other}</ul></section>' if other else "",
    "tickets": tickets,
  }, status


def render_dashboard(data, live=False):
  template = Template(Path(__file__).with_name("limits-dashboard.html").read_text(encoding="utf-8"))
  return template.substitute(data, live="true" if live else "false")


def write_dashboard(path, service, read_claude, read_agy):
  data, status = collect_dashboard(service, read_claude, read_agy)
  html = render_dashboard(data)
  path = path.expanduser()
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
      temporary = Path(tmp.name)
    try:
      temporary.write_text(html, encoding="utf-8")
      temporary.replace(path)
    finally:
      temporary.unlink(missing_ok=True)
  except OSError as error:
    print(error, file=sys.stderr)
    return 1
  print(path.absolute())
  return status
