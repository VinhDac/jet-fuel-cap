# Cap or swap, runway 27

Jet fuel hedging after the war began, on public data. One sheet, two sides, drawn as an approach chart.

**The note:** [vinhdac.github.io/notes/cap-or-swap](https://vinhdac.github.io/notes/cap-or-swap/). Figures below are for an airline hedging 10 million US gallons a month, on prices to {{asof}}.

## The front: the price of deciding after you know

Jet fuel is {{spot}} a gallon, against {{jet_pre}} before the war. The swap rate for 2027 is {{swap}}. If the war ends and the 2027 curve falls back to its pre-war {{swap_pre}}, that swap sits {{swap_regret}} above the market and calls about {{call_lc}} of margin. If it does not end, an airline with no hedge carries the next spike alone.

A cap struck at the swap rate pays anything above it, so each month costs the lower of the market and the swap rate, plus one fixed fee: about {{fee_c}} a gallon at fair value ({{fee_lo}} to {{fee_hi}} with volatility 20% lower or 25% higher).

| 2027, $ a gallon, fee included | War ends | Market is right | Stays here | Gets worse | Most you can regret |
|---|---|---|---|---|---|
{{table}}

Regret is what you paid above the better of the swap and no hedge.

## The back: what the policy does to the other side

- **The margin call shrinks and turns around.** In 2020 the swap called {{call20}}. A seller hedging the same year's cap in futures lost {{h20}} on the hedge, against {{p20}} of premium. Its largest margin came in the spikes: {{im22}} of initial margin in 2022, {{im26}} in 2026. Over {{nyears}} years its cash never fell more than {{low_cash}} below zero.
- **The policy has two prices.** For a cap {{otm}} above the swap, replicating it cost {{trader}} per $1 of swap rate. Such cover actually paid {{burn}} (90% range {{burn_lo}} to {{burn_hi}}).
- **The hedge decides which price is right.** Premium minus claims, plus the hedge, 2008 to 2025: {{a_none}} with no hedge, {{a_ho}} in heating oil, {{a_br}} in Brent. {{y22}} of the heating oil figure came in 2022.

## How it works

- **Forward curve.** Gulf Coast jet trades as a differential to the NYMEX heating oil future. A delivery month is today's jet price plus the slope of the futures curve: EIA's four contracts to April 2024, then the front contract and every later listed month.
- **Volatility.** No public option quote exists for jet or heating oil. The level is heating oil's 252-day realised volatility, moved by how far crude's OVX stands from its own 252-day mean, times the {{iv}} that crude options have cost over what crude then did. The term structure is fitted in `calibrate.py`.
- **Pricing.** Each month is an Asian call, valued in closed form and checked against simulation, including months already under way.
- **The seller.** `desk.py` sells the policy, hedges its delta daily in the front contract, pays claims monthly and holds initial margin by a rule: a 99% two-day move on a slow average of volatility.

## What it leaves out

Gulf Coast prices stand in for the airline's own. Fees are fair values on public proxies, before any seller's margin. Initial margin is a rule, not the exchange's schedule. The back assumes the risk is hedged in listed futures; if it is laid off, its numbers are the reinsurer's. 2026 runs to {{asof}}, with open months at model value.

## Run it

Python 3.10 or later and NumPy.

```
python fetch_data.py    # public data; the futures and OVX go to data/market/, which is not in this repo
python calibrate.py     # where the fixed numbers in model.py come from
python backtest.py      # results.json
python checks.py        # {{checks}} checks that must hold before any number is used
python mutations.py     # breaks {{faults}} rules on copies, and sees a check fail each time
python build_page.py    # the note, into site/, and this README
```

Data: [EIA](https://www.eia.gov/petroleum/data.php), [US Treasury](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve), Yahoo Finance for NYMEX futures and Cboe's OVX. Hedging reports: Reuters, 28 October 2026.

Not for navigation, and not an offer of insurance. If any number here is wrong, I would like to be the first to know.

Dac Vinh Nguyen
