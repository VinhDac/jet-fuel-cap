# Cap or swap, runway 27

Jet fuel hedging after the war began, on public data. One sheet, two sides, drawn as an approach chart.

**The note:** [vinhdac.github.io/notes/cap-or-swap](https://vinhdac.github.io/notes/cap-or-swap/). Figures below are for an airline hedging 10 million US gallons a month, on prices to 11 November 2026.

## The front: the price of deciding after you know

Jet fuel is $4.04 a gallon, against $2.43 before the war. The swap rate for 2027 is $3.51. If the war ends and the 2027 curve falls back to its pre-war $2.07, that swap sits $1.44 above the market and calls about $167m of margin. If it does not end, an airline with no hedge carries the next spike alone.

A cap struck at the swap rate pays anything above it, so each month costs the lower of the market and the swap rate, plus one fixed fee: about 52 cents a gallon at fair value (42 cents to 64 cents with volatility 20% lower or 25% higher).

| 2027, $ a gallon, fee included | War ends | Market is right | Stays here | Gets worse | Most you can regret |
|---|---|---|---|---|---|
| No hedge | 2.07 | 3.51 | 4.04 | 5.50 | 1.99 |
| Swap | 3.51 | 3.51 | 3.51 | 3.51 | 1.44 |
| **Cap at the swap rate** | 2.59 | 4.02 | 4.02 | 4.02 | 0.52 |
| Cap at today's price | 2.39 | 3.83 | 4.36 | 4.36 | 0.85 |
| Layer $4.04 to $5.04 | 2.27 | 3.70 | 4.23 | 4.70 | 1.19 |

Regret is what you paid above the better of the swap and no hedge.

## The back: what the policy does to the other side

- **The margin call shrinks and turns around.** In 2020 the swap called $111m. A seller hedging the same year's cap in futures lost $4.2m on the hedge, against $4.6m of premium. Its largest margin came in the spikes: $52m of initial margin in 2022, $48m in 2026. Over 19 years its cash never fell more than $16m below zero.
- **The policy has two prices.** For a cap 10% above the swap, replicating it cost 4.5¢ per $1 of swap rate. Such cover actually paid 11.4¢ (90% range 4.8¢ to 19.1¢).
- **The hedge decides which price is right.** Premium minus claims, plus the hedge, 2008 to 2025: −$122m with no hedge, +$76m in heating oil, +$20m in Brent. $66m of the heating oil figure came in 2022.

## How it works

- **Forward curve.** Gulf Coast jet trades as a differential to the NYMEX heating oil future. A delivery month is today's jet price plus the slope of the futures curve: EIA's four contracts to April 2024, then the front contract and every later listed month.
- **Volatility.** No public option quote exists for jet or heating oil. The level is heating oil's 252-day realised volatility, moved by how far crude's OVX stands from its own 252-day mean, times the 1.07 that crude options have cost over what crude then did. The term structure is fitted in `calibrate.py`.
- **Pricing.** Each month is an Asian call, valued in closed form and checked against simulation, including months already under way.
- **The seller.** `desk.py` sells the policy, hedges its delta daily in the front contract, pays claims monthly and holds initial margin by a rule: a 99% two-day move on a slow average of volatility.

## What it leaves out

Gulf Coast prices stand in for the airline's own. Fees are fair values on public proxies, before any seller's margin. Initial margin is a rule, not the exchange's schedule. The back assumes the risk is hedged in listed futures; if it is laid off, its numbers are the reinsurer's. 2026 runs to 11 November 2026, with open months at model value.

## Run it

Python 3.10 or later and NumPy.

```
python fetch_data.py    # public data; the futures and OVX go to data/market/, which is not in this repo
python calibrate.py     # where the fixed numbers in model.py come from
python backtest.py      # results.json
python checks.py        # 11 checks that must hold before any number is used
python mutations.py     # breaks 14 rules on copies, and sees a check fail each time
python build_page.py    # the note, into site/, and this README
```

Data: [EIA](https://www.eia.gov/petroleum/data.php), [US Treasury](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve), Yahoo Finance for NYMEX futures and Cboe's OVX. Hedging reports: Reuters, 28 October 2026.

Not for navigation, and not an offer of insurance. If any number here is wrong, I would like to be the first to know.

Dac Vinh Nguyen
