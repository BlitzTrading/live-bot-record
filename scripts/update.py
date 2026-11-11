"""Add one daily snapshot of a live Blitz bot and re-render README.md and chart.svg.

Usage:
    python scripts/update.py add <row.json>              # SKHY bot: add or replace the row for that date, then render
    python scripts/update.py add-btc <row.json>          # BTC bot: same, into data/btc-daily.csv
    python scripts/update.py add-btc-capture <cap.json>  # BTC bot: take the row from a capture_btc_record.py json
    python scripts/update.py render                      # only re-render

row.json holds the numbers read from the live stream overlay, for example:
    {"date": "2026-10-11", "checked_at": "13:05", "exchange": "Gate", "symbol": "SKHY",
     "side": "long", "leverage": 5, "step": "7/10", "avg_entry": 180.83, "price": 170.1,
     "unrealized_usdt": -222.0, "unrealized_pct": -28.5, "liq_price": 36.2,
     "tp_7d": 7, "realized_7d_usdt": 5.75, "note": ""}

A BTC row.json uses BTC_FIELDS, for example:
    {"date": "2026-11-10", "checked_at": "13:44", "exchange": "Gate", "symbol": "BTCUSDT", "side": "long",
     "leverage": 5, "step": "8/18", "avg_entry": 75683.25, "size_btc": 0.0068, "cycles_closed": 5,
     "tps_all": 5, "sl_all": 0, "realized_all_usdt": 0.9, "note": ""}

Only standard library. Wallet balances are never recorded.
"""
import csv
import datetime as dt
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "daily.csv"
README = ROOT / "README.md"
CHART = ROOT / "chart.svg"
START = dt.date(2026, 8, 3)  # bot went live; 2026-08-03 is Day 1
BTC_CSV = ROOT / "data" / "btc-daily.csv"
BTC_START = dt.date(2026, 11, 6)  # BTC bot went live; 2026-11-06 is Day 1

FIELDS = ["date", "day", "checked_at", "exchange", "symbol", "side", "leverage", "step",
          "avg_entry", "price", "unrealized_usdt", "unrealized_pct", "liq_price",
          "tp_7d", "realized_7d_usdt", "note"]
NUMERIC = ["leverage", "avg_entry", "price", "unrealized_usdt", "unrealized_pct", "liq_price",
           "tp_7d", "realized_7d_usdt"]
BTC_FIELDS = ["date", "day", "checked_at", "exchange", "symbol", "side", "leverage", "step",
              "avg_entry", "size_btc", "cycles_closed", "tps_all", "sl_all", "realized_all_usdt", "note"]
BTC_NUMERIC = ["leverage", "avg_entry", "size_btc", "cycles_closed", "tps_all", "sl_all", "realized_all_usdt"]
FORBIDDEN = ["balance", "wallet", "equity", "email", "uid", "principal"]
TEXT = ["checked_at", "exchange", "symbol", "side", "step"]
NUMBER_RE = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
KST = dt.timezone(dt.timedelta(hours=9))


def plain_number(v):
    """Turns what the stream shows ("+12.5%", "5x", "1,234.5 USDT", 5e-05) into "12.5", "5", "1234.5", "0.00005"."""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "?"
    if isinstance(v, (int, float)):
        return format(Decimal(repr(v)), "f")
    t = str(v).strip().replace(",", "").replace(" ", "")
    t = re.sub(r"(?i)(usdt|x|%)$", "", t)
    if t.startswith("+"):
        t = t[1:]
    try:
        return format(Decimal(t), "f") if NUMBER_RE.match(t) or re.match(r"^-?[0-9.]+[eE][-+]?[0-9]+$", t) else t
    except ArithmeticError:
        return t
TEXT_RE = re.compile(r"^[A-Za-z0-9 ./:_-]*$")

UTM = "utm_source=github&utm_medium=repo&utm_campaign=gh_live_record"


def load_rows(path=CSV_PATH):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_rows(rows, path=CSV_PATH, fields=FIELDS):
    rows.sort(key=lambda r: r["date"])
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def clean_row(raw, fields=FIELDS, numeric=NUMERIC, start=START):
    bad = [k for k in raw if any(word in k.lower() for word in FORBIDDEN)]
    if bad:
        sys.exit(f"refused: fields {bad} must never be recorded")
    unknown = [k for k in raw if k not in fields]
    if unknown:
        sys.exit(f"unknown fields {unknown}; allowed: {fields}")
    try:
        day = dt.date.fromisoformat(str(raw["date"]))
    except (KeyError, ValueError):
        sys.exit("date is required as YYYY-MM-DD (KST)")
    row = {k: "" for k in fields}
    row.update({k: ("" if v is None else str(v)) for k, v in raw.items() if k not in numeric})
    row.update({k: plain_number(v) for k, v in raw.items() if k in numeric})
    if day > dt.datetime.now(KST).date():
        sys.exit(f"date {day} is in the future (KST)")
    if day < start:
        sys.exit(f"date must be on or after {start} (the bot's first live day)")
    row["date"] = day.isoformat()
    row["day"] = str((day - start).days + 1)
    for k in TEXT:
        row[k] = row[k].strip()
        if not TEXT_RE.match(row[k]):
            sys.exit(f"{k} may only use letters, digits, space and . / : _ -, got {row[k]!r}")
    # The note is free text: keep it to one CSV cell and one table cell.
    row["note"] = re.sub(r"\s+", " ", re.sub(r"[,|<>]", " ", row["note"])).strip()
    row["side"] = row["side"].lower()
    if row["checked_at"] and not TIME_RE.match(row["checked_at"]):
        sys.exit(f"checked_at must be HH:MM (KST), got {row['checked_at']!r}")
    for k in numeric:
        if row[k] != "" and not NUMBER_RE.match(row[k]):
            sys.exit(f"{k} must be a plain number like -12.5, got {row[k]!r}")
    if row["side"] and row["side"] not in ("long", "short", "flat"):
        sys.exit("side must be long, short or flat")
    return row


def f(v, digits=2, sign=False):
    """Formats like the web page: half-up rounding, fixed decimals when signed, trimmed otherwise."""
    if v in ("", None):
        return "—"
    x = Decimal(str(v)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    if x == 0:
        x = abs(x)  # no "-0.00" and no "+0.00"
        return f"{x:,.{digits}f}" if sign else "0"
    s = f"{x:+,.{digits}f}" if sign else f"{x:,.{digits}f}"
    return s.rstrip("0").rstrip(".") if "." in s and not sign else s


def chart(rows):
    """Unrealized P&L (% of margin, as the stream shows it) per day."""
    pts = [(r["date"], float(r["unrealized_pct"])) for r in rows if r.get("unrealized_pct") not in ("", None)]
    W, H, L, R, T, B = 760, 260, 52, 16, 34, 34
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           f'font-family="Helvetica, Arial, sans-serif" font-size="12">',
           f'<rect width="{W}" height="{H}" rx="10" fill="#0A0A0F"/>',
           f'<text x="{L}" y="14" fill="#9A9890">Unrealized P&amp;L, % of margin (daily snapshot from the live stream)</text>']
    if not pts:
        out.append(f'<text x="{W/2}" y="{H/2}" fill="#9A9890" text-anchor="middle">First snapshot coming soon</text></svg>')
        return "\n".join(out)
    vals = [v for _, v in pts] + [0.0]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.1 or 5
    lo, hi = lo - pad, hi + pad
    n = len(pts)
    x = lambda i: L + (W - L - R) * (i / (n - 1) if n > 1 else 0.5)
    y = lambda v: T + (H - T - B) * (hi - v) / (hi - lo)
    for frac in (0, 0.25, 0.5, 0.75, 1):
        v = lo + (hi - lo) * frac
        out.append(f'<line x1="{L}" x2="{W-R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#1E1E28"/>')
        out.append(f'<text x="{L-6}" y="{y(v)+4:.1f}" fill="#9A9890" text-anchor="end">{v:.0f}%</text>')
    out.append(f'<line x1="{L}" x2="{W-R}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#55545E" stroke-dasharray="4 4"/>')
    path = " ".join(f'{"M" if i == 0 else "L"}{x(i):.1f},{y(v):.1f}' for i, (_, v) in enumerate(pts))
    out.append(f'<path d="{path}" fill="none" stroke="#F5C842" stroke-width="2.2"/>')
    for i, (_, v) in enumerate(pts):
        color = "#22c55e" if v >= 0 else "#f05252"
        out.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3.2" fill="{color}"/>')
    out.append(f'<text x="{L}" y="{H-10}" fill="#9A9890">{pts[0][0]}</text>')
    if n > 1:
        out.append(f'<text x="{W-R}" y="{H-10}" fill="#9A9890" text-anchor="end">{pts[-1][0]}</text>')
    out.append("</svg>")
    return "\n".join(out)


def fp(v):
    """Price: more decimals for cheap coins, same rule as the web page."""
    if v in ("", None):
        return "—"
    a = abs(Decimal(str(v)))
    return f(v, 2 if a >= 1000 else 4 if a >= 1 else 8)


def table(rows):
    head = ("| Date (KST) | Day | Position | Step | Avg entry | Price | Unrealized | Liquidation | TPs (7d) | Realized (7d) |\n"
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    lines = [head]
    for r in sorted(rows, key=lambda r: r["date"], reverse=True):
        pos = " ".join(p for p in [r["symbol"], r["side"], (f(r["leverage"], 2) + "x") if r["leverage"] else ""] if p)
        parts = []
        if r["unrealized_usdt"]:
            parts.append(f'{f(r["unrealized_usdt"], 2, sign=True)} USDT')
        if r["unrealized_pct"]:
            pct = f'{f(r["unrealized_pct"], 1, sign=True)}%'
            parts.append(f"({pct})" if parts else pct)
        unreal = " ".join(parts) or "—"
        realized = f'{f(r["realized_7d_usdt"], 2, sign=True)} USDT' if r["realized_7d_usdt"] else "—"
        lines.append(f'| {r["date"]} | {r["day"]} | {pos or "—"} | {r["step"] or "—"} | {fp(r["avg_entry"])} | '
                     f'{fp(r["price"])} | {unreal} | {fp(r["liq_price"])} | {f(r["tp_7d"], 0) if r["tp_7d"] else "—"} | {realized} |')
    if len(lines) == 1:
        lines.append("| — | | First snapshot coming soon | | | | | | | |")
    return "\n".join(lines)


def btc_row_from_capture(cap):
    """Row for data/btc-daily.csv from a capture_btc_record.py json. Only the listed fields are copied:
    the capture also holds the wallet and the principal, which are never recorded."""
    strategy = str(cap.get("strategy") or "")
    if "BTC" not in strategy:
        sys.exit(f"refused: capture is not the BTC bot (strategy {strategy!r})")
    lev = re.search(r"(\d+(?:\.\d+)?)\s*[xX]\b", strategy)
    side = re.match(r"\s*\[(Long|Short)\]", strategy)
    read = str(cap.get("read_kst") or "")
    step = ""
    if cap.get("step") not in (None, "") and cap.get("steps") not in (None, ""):
        step = f'{cap["step"]}/{cap["steps"]}'
    return {"date": cap.get("kst_date"), "checked_at": read[11:16] if len(read) >= 16 else "",
            "exchange": "Gate", "symbol": "BTCUSDT", "side": side.group(1).lower() if side else "",
            "leverage": lev.group(1) if lev else "", "step": step,
            "avg_entry": cap.get("avg_entry"), "size_btc": cap.get("size_btc"),
            "cycles_closed": cap.get("cycles"), "tps_all": cap.get("tps"), "sl_all": cap.get("sl"),
            "realized_all_usdt": cap.get("realized_all"), "note": ""}


def btc_table(rows):
    head = ("| Date (KST) | Day | Position | Step | Avg entry | Size (BTC) | Cycles closed | TPs | SLs | Realized (all time) |\n"
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    lines = [head]
    for r in sorted(rows, key=lambda r: r["date"], reverse=True):
        pos = " ".join(p for p in [r["symbol"], r["side"], (f(r["leverage"], 2) + "x") if r["leverage"] else ""] if p)
        realized = f'{f(r["realized_all_usdt"], 2, sign=True)} USDT' if r["realized_all_usdt"] else "—"
        cnt = lambda k: f(r[k], 0) if r[k] else "—"
        lines.append(f'| {r["date"]} | {r["day"]} | {pos or "—"} | {r["step"] or "—"} | {fp(r["avg_entry"])} | '
                     f'{f(r["size_btc"], 8) if r["size_btc"] else "—"} | {cnt("cycles_closed")} | {cnt("tps_all")} | '
                     f'{cnt("sl_all")} | {realized} |')
    if len(lines) == 1:
        lines.append("| — | | First snapshot coming soon | | | | | | | |")
    return "\n".join(lines)


def replace_block(text, start, end, block):
    if start not in text or end not in text:
        sys.exit(f"README markers missing: {start} {end}")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return head + start + "\n" + block + "\n" + end + tail


def status_line(latest):
    if not latest:
        return "**Waiting for the first snapshot**"
    when = " ".join(p for p in [latest["date"], latest["checked_at"]] if p)
    return f'**Day {latest["day"]}** · last snapshot {when} KST'


def render():
    rows = load_rows()
    CHART.write_text(chart(rows), encoding="utf-8")
    text = README.read_text(encoding="utf-8")
    text = replace_block(text, "<!-- RECORD:START -->", "<!-- RECORD:END -->",
                         f"{status_line(rows[-1] if rows else None)}\n\n![Unrealized P&L chart](chart.svg)\n\n{table(rows)}")
    btc = load_rows(BTC_CSV)
    text = replace_block(text, "<!-- BTC:START -->", "<!-- BTC:END -->",
                         f"{status_line(btc[-1] if btc else None)}\n\n{btc_table(btc)}")
    README.write_text(text, encoding="utf-8")
    print(f"rendered {len(rows)} SKHY rows, {len(btc)} BTC rows")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "render":
        render()
        return
    if len(sys.argv) == 3 and sys.argv[1] == "add":
        raw = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
        row = clean_row(raw)
        rows = [r for r in load_rows() if r["date"] != row["date"]] + [row]
        save_rows(rows)
        print(f'saved Day {row["day"]} ({row["date"]})')
        render()
        return
    if len(sys.argv) == 3 and sys.argv[1] in ("add-btc", "add-btc-capture"):
        raw = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
        if sys.argv[1] == "add-btc-capture":
            raw = btc_row_from_capture(raw)
        row = clean_row(raw, BTC_FIELDS, BTC_NUMERIC, BTC_START)
        rows = [r for r in load_rows(BTC_CSV) if r["date"] != row["date"]] + [row]
        save_rows(rows, BTC_CSV, BTC_FIELDS)
        print(f'saved BTC Day {row["day"]} ({row["date"]})')
        render()
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
