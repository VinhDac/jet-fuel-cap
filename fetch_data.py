"""Download the public data this study runs on, and write it as plain CSV.

Sources (all free, no key):
  EIA   U.S. Gulf Coast kerosene-type jet fuel spot price, daily, $/gal
  EIA   NYMEX No. 2 heating oil / ULSD futures, contracts 1 to 4, daily, $/gal (to April 2024)
  EIA   New York Harbor ULSD and Brent spot prices, daily
  US Treasury   1-year par yield, daily, percent
  Yahoo Finance chart data, into data/market/ and not redistributed here:
        front heating oil, Brent and WTI futures, the listed heating oil and Brent contract
        months, and the OVX crude oil volatility index

Run: python fetch_data.py
"""
import calendar
import csv
import datetime as dt
import json
import os
import re
import time
import urllib.parse
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MARKET = os.path.join(DATA, "market")
UA = {"User-Agent": "Mozilla/5.0 (compatible; research-script/1.0)"}
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
SPOT = {"ulsd_nyh": "EER_EPD2DXL0_PF4_Y35NY_DPG", "brent": "RBRTE"}
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}?period1={}&period2={}&interval=1d"
FRONT = {"ho_front": "HO=F", "brent_front": "BZ=F", "wti_front": "CL=F", "ovx": "^OVX"}
MONTH_CODES = "FGHJKMNQUVXZ"
EIA = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s={}&f=D"
JET = "EER_EPJK_PF4_RGC_DPG"
FUTURES = {f"c{k}": f"EER_EPD2F_PE{k}_Y35NY_DPG" for k in (1, 2, 3, 4)}
TREASURY = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve"
    "&field_tdr_date_value={y}&page&_format=csv"
)
FIRST_YEAR, LAST_YEAR = 2004, dt.date.today().year
MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}

ROW = re.compile(
    r"<td class='B6'>(?:&nbsp;)*\s*(\d{4}) (\w{3})-\s*(\d+) to .*?</td>((?:\s*<td class='B3'>[^<]*</td>){5})"
)
CELL = re.compile(r"<td class='B3'>([^<]*)</td>")


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("utf-8", "replace")


def eia_daily(series):
    """EIA's history page is one table: a row a week, a cell for each weekday."""
    out = {}
    for y, mon, day, cells in ROW.findall(get(EIA.format(series))):
        monday = dt.date(int(y), MONTHS[mon], int(day))
        for i, v in enumerate(CELL.findall(cells)):
            v = v.strip()
            if v:
                out[monday + dt.timedelta(days=i)] = float(v)
    if not out:
        raise SystemExit(f"nothing read for {series}: the page has changed")
    return out


def treasury_1y():
    out = {}
    for y in range(FIRST_YEAR, LAST_YEAR + 1):
        rows = csv.DictReader(get(TREASURY.format(y=y)).splitlines())
        for r in rows:
            v = (r.get("1 Yr") or "").strip()
            if v:
                m, d, yy = r["Date"].split("/")
                out[dt.date(int(yy), int(m), int(d))] = float(v)
        time.sleep(0.4)
    return out


def yahoo(symbol, start="2000-01-01"):
    """Daily closes of one symbol. A contract that has expired is no longer served."""
    a = calendar.timegm(dt.date.fromisoformat(start).timetuple())
    b = calendar.timegm((dt.date.today() + dt.timedelta(days=1)).timetuple())
    url = CHART.format(urllib.parse.quote(symbol), a, b)
    with urllib.request.urlopen(urllib.request.Request(url, headers=BROWSER), timeout=60) as r:
        res = json.load(r)["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    return {dt.datetime.fromtimestamp(t, dt.timezone.utc).date(): c for t, c in zip(res["timestamp"], closes) if c is not None}


def listed_months(first=(2026, 12), count=19):
    y, m = first
    for _ in range(count):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def write_market():
    os.makedirs(MARKET, exist_ok=True)
    for name, symbol in FRONT.items():
        s = yahoo(symbol)
        write(os.path.join("market", name + ".csv"), ["date", name], [[d.isoformat(), f"{s[d]:.4f}"] for d in sorted(s)])
        time.sleep(0.3)
    for root in ("HO", "BZ"):
        rows = []
        for y, m in listed_months():
            symbol = f"{root}{MONTH_CODES[m - 1]}{y % 100}.NYM"
            try:
                s = yahoo(symbol, "2024-01-01")
            except urllib.error.HTTPError:
                continue
            rows += [[d.isoformat(), f"{y}-{m:02d}", f"{s[d]:.4f}"] for d in sorted(s)]
            time.sleep(0.2)
        rows.sort()
        write(os.path.join("market", root.lower() + "_contracts.csv"), ["date", "delivery", "close"], rows)


def write(name, header, rows):
    path = os.path.join(DATA, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows, {rows[0][0]} to {rows[-1][0]}")


def main():
    os.makedirs(DATA, exist_ok=True)
    jet = eia_daily(JET)
    write("jet_usgc.csv", ["date", "jet"], [[d.isoformat(), f"{jet[d]:.3f}"] for d in sorted(jet)])
    curves = {}
    for name, series in FUTURES.items():
        curves[name] = eia_daily(series)
        time.sleep(0.4)
    days = sorted(set.intersection(*(set(c) for c in curves.values())))
    write(
        "heating_oil_futures.csv",
        ["date", "c1", "c2", "c3", "c4"],
        [[d.isoformat()] + [f"{curves[c][d]:.3f}" for c in ("c1", "c2", "c3", "c4")] for d in days],
    )
    y1 = treasury_1y()
    write("treasury_1y.csv", ["date", "y1"], [[d.isoformat(), f"{y1[d]:.2f}"] for d in sorted(y1)])
    for name, series in SPOT.items():
        s = eia_daily(series)
        write(name + ".csv", ["date", name], [[d.isoformat(), f"{s[d]:.3f}"] for d in sorted(s)])
        time.sleep(0.4)
    write_market()


if __name__ == "__main__":
    main()
