# NeighbourGrid Simulation — Starter Code

## Files
- `data_gen.py` — Layer 1: synthetic solar + household load data (swap in real NASA POWER API on your own laptop before the final demo — see the docstring at the top).
- `scheduler.py` — Layer 2: the priority-order scheduling engine (solar→load, then battery charge, then battery discharge, then grid) plus the no-battery baseline for comparison.
- `run_simulation.py` — runs both scenarios over a simulated week and prints/saves the Section 4.2 report metrics.

## Run it
```
pip install numpy pandas matplotlib
python3 run_simulation.py
```
Outputs `results_with_system.csv`, `results_baseline.csv`, `summary.png`.

## What we found on the first run
- Renewable self-consumption: 51.8% -> 100%
- Weekly grid energy: down ~26%
- Peak grid draw: only down ~2.5% — the battery drains to its floor before
  the evening peak hits. This is a real sizing finding, not a bug — see the
  "Next steps" below.

## Next steps (try these before your pitch)
1. **Tune sizing** — increase `BATTERY_CAPACITY_KWH` or `PANEL_KWP` in
   `run_simulation.py` and re-run. Find the smallest/cheapest combination
   that gets meaningful peak reduction — that's a real sizing study you can
   present.
2. **Add a peak-reserve rule** — modify `scheduler.py` so the battery holds
   back some charge instead of fully discharging outside the declared peak
   window (`tod_peak_hours`), so it has capacity specifically for 18:00-22:00.
   This is a one-line-of-logic change with a big story payoff: "we found
   naive discharge doesn't peak-shave, so we added a reserve rule — here's
   the improvement."
3. **Swap in real solar data** — run `fetch_nasa_power_irradiance()` in
   `data_gen.py` on a machine with internet access, before finalizing your
   pitch numbers.
4. **Feed this into forecasting (Layer 3)** — once this loop is solid, have
   the scheduler run on *forecasted* solar/load instead of actual, and
   compare performance degradation — that's your third build block.
