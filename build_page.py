"""Build the note from results.json: every number on the sheet is read from it.

Run: python build_page.py [output.html]
"""
import datetime as dt
import json
import os
import statistics as st
import sys
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "https://github.com/VinhDac/jet-fuel-cap"
MONTH = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
CHECKS, FAULTS = 11, 14  # checks.py, mutations.py
MINUS = "−"


def m0(x):
    return f"${x:,.0f}m"


def m0_1(x):
    return f"${x:,.1f}m"


def signed_m0(x):
    return (MINUS if x < 0 else "+") + f"${abs(x):,.0f}m"


def cents(x):
    return f"{x * 100:.0f} cents"


def short_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {MONTH[d.month - 1]} {d.year % 100}"


def years_block(res):
    out = {}
    plain = {y["year"]: y for y in res["no_limit"]}
    lim = {y["year"]: y for y in res["with_limit"]}
    for year in (2020, 2022, 2026):
        row = {"swap": plain[year]["swap_call_back"]}
        for lim_name, table in (("none", plain), ("one", lim)):
            y = table[year]
            for inst in ("ho", "brent"):
                s = y[inst]
                row[f"{inst}_{lim_name}"] = {
                    "premium": y["premium_m"],
                    "worst": s["worst_hedge"]["m"],
                    "im": s["peak_im"],
                    "low": s["low_cash"]["m"],
                }
        out[year] = row
    return out


def main(out):
    res = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
    f = res["front"]
    P = f["prices"]
    plain = {y["year"]: y for y in res["no_limit"]}
    lim = {y["year"]: y for y in res["with_limit"]}
    rows = res["no_limit"]
    to25 = [y for y in rows if y["year"] <= 2025]
    H = res["hindsight"]
    two = {round(x["otm"], 2): x for x in res["two_prices"]}[0.1]
    regret = f["worst_regret"]
    S, spot = f["swap"], f["jet"]

    assert f["swap_pre_war"] < S < spot, "the words have the curve falling below today's price"
    assert regret["hindsight"] < min(regret[k] for k in ("none", "swap", "cap", "layer")), "the note says hindsight regrets least"
    assert plain[2020]["swap_call_back"]["m"] == max(y["swap_call_back"]["m"] for y in rows), "2020 is the worst swap call"
    assert two["replication"] < two["burn_low"], "the trader's price sits below the claims' range"

    swap20 = sum(1 for y in rows if y["swap_call_back"]["m"] > 20)
    low = min(y["ho"]["low_cash"]["m"] for y in rows)
    top_p = 1 - lim[2026]["premium_m"] / plain[2026]["premium_m"]
    top_c = 1 - lim[2026]["claims_m"] / plain[2026]["claims_m"]
    alts = [
        {"name": "NO HEDGE", "v": [sum(y["unhedged_net_m"] for y in to25), plain[2022]["unhedged_net_m"], plain[2026]["unhedged_net_m"]]},
        {"name": "HEATING OIL", "v": [sum(y["ho"]["net_m"] for y in to25), plain[2022]["ho"]["net_m"], plain[2026]["ho"]["net_m"]]},
        {"name": "BRENT", "v": [sum(y["brent"]["net_m"] for y in to25), plain[2022]["brent"]["net_m"], plain[2026]["brent"]["net_m"]]},
    ]
    assert plain[2022]["ho"]["net_m"] > 0.5 * alts[1]["v"][0], "the note says most of heating oil's gain came in 2022"
    tp = sum(x["premium_m"] for x in res["layers"])
    tc = sum(x["claims_m"] for x in res["layers"])
    names = {0.0: "0 TO 50¢", 0.5: "50¢ TO $1", 1.0: "$1 TO $2", 2.0: "OVER $2"}
    layers = [{"name": names[x["from"]], "p": round(100 * x["premium_m"] / tp), "c": round(100 * x["claims_m"] / tc)} for x in res["layers"]]

    duck = open(os.path.join(HERE, "page", "duck.txt"), encoding="utf-8").read().strip()
    today = dt.date.today()
    T = {
        "date": f"{today.day} {MONTH[today.month - 1]} {today.year % 100}",
        "asof": dt.date.fromisoformat(res["as_of"]).strftime("%-d %B %Y") if os.name != "nt" else dt.date.fromisoformat(res["as_of"]).strftime("%#d %B %Y"),
        "asof_s": short_date(res["as_of"]),
        "spot": f"${spot:.2f}",
        "jet_pre": f"${f['jet_pre_war']:.2f}",
        "swap": f"${S:.2f}",
        "swap_pre": f"${f['swap_pre_war']:.2f}",
        "fee": f"${P['market']['hindsight']:.2f}",
        "fee_c": cents(P["market"]["hindsight"]),
        "fee_lo": cents(P["low"]["hindsight"]),
        "fee_hi": cents(P["high"]["hindsight"]),
        "fee_hist": cents(P["history"]["hindsight"]),
        "bill": f"${f['fuel_bill_m']:.0f}M",
        "call": f"${f['call_if_peace_m']:.0f}M",
        "call_lc": m0(f["call_if_peace_m"]),
        "swap_regret": f"${regret['swap']:.2f}",
        "first": rows[0]["year"],
        "h_cap": f"${st.mean(h['cap'] for h in H):.2f}",
        "h_swap": f"${st.mean(h['swap'] for h in H):.2f}",
        "h_none": f"${st.mean(h['none'] for h in H):.2f}",
        "h_rc": cents(max(h["regret_cap"] for h in H)),
        "h_rs": cents(max(h["regret_swap"] for h in H)),
        "h_rn": f"${max(h['regret_none'] for h in H):.2f}",
        "otm": f"{res['otm'] * 100:.0f}%-out-of-the-money".replace("%-out-of-the-money", "%-above-swap"),
        "nyears": len(rows),
        "low_cash": m0(abs(low)),
        "swap20": swap20,
        "call20": m0(plain[2020]["swap_call_back"]["m"]),
        "trader": f"{two['replication'] * 100:.1f}¢",
        "burn": f"{two['burn'] * 100:.1f}¢",
        "burn_lo": f"{two['burn_low'] * 100:.1f}¢",
        "burn_hi": f"{two['burn_high'] * 100:.1f}¢",
        "ratio": f"{two['ratio']:.1f}",
        "ratio25": f"{two['ratio_to_2025']:.1f}",
        "top_p": f"{top_p * 100:.0f}%",
        "top_c": f"{top_c * 100:.0f}%",
        "r2h": f"{res['fit']['2026']['ho'] * 100:.0f}%",
        "r2b": f"{res['fit']['2026']['brent'] * 100:.0f}%",
        "y22": m0(plain[2022]["ho"]["net_m"]),
        "ho_total": m0(alts[1]["v"][0]),
        "checks": CHECKS,
        "faults": FAULTS,
        "REPO": REPO,
        "REPO_SHORT": REPO.replace("https://", ""),
        "DUCK_PATH": duck,
        "DUCK_URI": quote(duck, safe=",.-"),
    }
    T["otm"] = f"{res['otm'] * 100:.0f}%"
    names_c = [("A", "WAR ENDS"), ("B", "MARKET RIGHT"), ("C", "STAYS HERE"), ("D", "GETS WORSE")]
    data = {
        "cover": res["charts"]["cover"],
        "climb": res["charts"]["climb"],
        "runways": res["charts"]["runways"],
        "years": years_block(res),
        "swap_pre": f["swap_pre_war"],
        "limit": res["limit"],
        "cats": [{"id": i, "name": n, "x": s["jet"]} for (i, n), s in zip(names_c, f["scenarios"])],
        "scales": [
            {"v": 0.8, "name": "LOWER"},
            {"v": 1, "name": "MARKET"},
            {"v": 1.25, "name": "HIGHER"},
            {"v": P["history"]["vol_scale"], "name": "HISTORY"},
        ],
        "two": res["two_prices"],
        "layers": layers,
        "alts": alts,
        "log": [
            {
                "y": y["year"],
                "swap": y["swap_call_back"]["m"],
                "ho_none": y["ho"]["low_cash"]["m"],
                "brent_none": y["brent"]["low_cash"]["m"],
                "ho_one": lim[y["year"]]["ho"]["low_cash"]["m"],
                "brent_one": lim[y["year"]]["brent"]["low_cash"]["m"],
            }
            for y in rows
        ],
    }
    html = open(os.path.join(HERE, "page", "note.tpl.html"), encoding="utf-8").read()
    for k, v in T.items():
        html = html.replace("{{" + k + "}}", str(v))
    html = html.replace("{{DATA}}", json.dumps(data, separators=(",", ":")))
    labels = (("none", "No hedge"), ("swap", "Swap"), ("hindsight", "**Cap at the swap rate**"), ("cap", "Cap at today's price"), ("layer", f"Layer ${spot:.2f} to ${spot + res['limit']:.2f}"))
    lines = ["| " + name + " | " + " | ".join(f"{sc[k]:.2f}" for sc in f["scenarios"]) + f" | {regret[k]:.2f} |" for k, name in labels]
    extra = {
        "table": chr(10).join(lines),
        "h20": m0_1(abs(plain[2020]["ho"]["worst_hedge"]["m"])),
        "p20": m0_1(plain[2020]["premium_m"]),
        "im22": m0(plain[2022]["ho"]["peak_im"]["m"]),
        "im26": m0(plain[2026]["ho"]["peak_im"]["m"]),
        "a_none": signed_m0(alts[0]["v"][0]),
        "a_ho": signed_m0(alts[1]["v"][0]),
        "a_br": signed_m0(alts[2]["v"][0]),
        "iv": "1.07",
    }
    readme = open(os.path.join(HERE, "page", "README.tpl.md"), encoding="utf-8").read()
    for k, v in {**T, **extra}.items():
        readme = readme.replace("{{" + k + "}}", str(v))
    long_dashes = (chr(0x2014), chr(0x2013))
    assert "{{" not in readme and not any(c in readme for c in long_dashes), "the README"
    with open(os.path.join(HERE, "README.md"), "w", encoding="utf-8", newline=chr(10)) as fh:
        fh.write(readme)
    assert "{{" not in html, "a placeholder was left: " + html[html.index("{{"):][:40]
    assert not any(c in html for c in long_dashes), "a long dash"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    print("wrote", out, len(html.encode("utf-8")), "bytes")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "site", "index.html"))
