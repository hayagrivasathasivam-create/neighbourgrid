"""
run_simulation.py
------------------
Ties data_gen.py and scheduler.py together, runs a full simulated week
"with NeighbourGrid" vs "without" (baseline), and prints/saves exactly the
comparison metrics listed in Section 4.2 of the report:

  - Peak grid draw (kW), with vs without
  - Renewable self-consumption rate (%)
  - Estimated feeder-level technical loss reduction
  - DR responsiveness (% of hours a DR signal fired where the system helped)

Run:  python3 run_simulation.py
Outputs: results.csv, summary.png in the same folder.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from data_gen import build_week_dataset
from scheduler import Battery, run_priority_schedule, run_baseline_no_battery


# ---------------------------------------------------------------------------
# 1. Build the dataset (swap n_households / panel_kwp to match your pitch)
# ---------------------------------------------------------------------------
N_HOUSEHOLDS = 15
PANEL_KWP = 5.0
BATTERY_CAPACITY_KWH = 25.0

solar_df, load_df = build_week_dataset(n_households=N_HOUSEHOLDS, panel_kwp=PANEL_KWP)

# ---------------------------------------------------------------------------
# 2. Run both scenarios
# ---------------------------------------------------------------------------
battery = Battery(capacity_kwh=BATTERY_CAPACITY_KWH, max_charge_kw=8.0, max_discharge_kw=8.0)
with_system = run_priority_schedule(solar_df, load_df, battery)
baseline = run_baseline_no_battery(solar_df, load_df)

# ---------------------------------------------------------------------------
# 3. Compute Section 4.2 metrics
# ---------------------------------------------------------------------------
peak_grid_with = with_system["grid_kw"].max()
peak_grid_baseline = baseline["grid_kw"].max()
peak_reduction_pct = 100 * (peak_grid_baseline - peak_grid_with) / peak_grid_baseline

total_solar = solar_df["solar_kw"].sum()
self_consumed_with = (with_system["direct_solar_kw"] + with_system["battery_charge_kw"]).sum()
self_consumed_baseline = baseline["direct_solar_kw"].sum()
self_consumption_with_pct = 100 * self_consumed_with / total_solar
self_consumption_baseline_pct = 100 * self_consumed_baseline / total_solar

# Simple I^2R-style proxy: technical losses scale roughly with the square of
# feeder current, and current scales with grid draw at fixed voltage — so we
# approximate loss reduction as the drop in sum-of-squares of hourly grid draw.
# This is a defensible order-of-magnitude proxy for a pitch, not a load-flow study.
loss_proxy_with = (with_system["grid_kw"] ** 2).sum()
loss_proxy_baseline = (baseline["grid_kw"] ** 2).sum()
loss_reduction_pct = 100 * (loss_proxy_baseline - loss_proxy_with) / loss_proxy_baseline

dr_hours_fired = with_system["dr_signal_fired"].sum()
total_peak_hours = with_system["in_peak_window"].sum()
dr_trigger_rate_pct = 100 * dr_hours_fired / total_peak_hours if total_peak_hours else 0

total_grid_kwh_with = with_system["grid_kw"].sum()
total_grid_kwh_baseline = baseline["grid_kw"].sum()
grid_energy_reduction_pct = 100 * (total_grid_kwh_baseline - total_grid_kwh_with) / total_grid_kwh_baseline

print("=" * 70)
print("NEIGHBOURGRID — SIMULATED WEEK RESULTS")
print(f"({N_HOUSEHOLDS} households, {PANEL_KWP} kWp community solar, "
      f"{BATTERY_CAPACITY_KWH} kWh shared battery)")
print("=" * 70)
print(f"{'Metric':45s} {'Baseline':>10s} {'With system':>13s}")
print("-" * 70)
print(f"{'Peak grid draw (kW)':45s} {peak_grid_baseline:>10.2f} {peak_grid_with:>13.2f}")
print(f"{'  -> peak reduction':45s} {'':>10s} {peak_reduction_pct:>12.1f}%")
print(f"{'Renewable self-consumption rate':45s} {self_consumption_baseline_pct:>9.1f}% {self_consumption_with_pct:>12.1f}%")
print(f"{'Total weekly grid energy (kWh)':45s} {total_grid_kwh_baseline:>10.1f} {total_grid_kwh_with:>13.1f}")
print(f"{'  -> grid energy reduction':45s} {'':>10s} {grid_energy_reduction_pct:>12.1f}%")
print(f"{'Estimated technical loss reduction*':45s} {'':>10s} {loss_reduction_pct:>12.1f}%")
print(f"{'DR signal trigger rate (of peak hrs)':45s} {'':>10s} {dr_trigger_rate_pct:>12.1f}%")
print("-" * 70)
print("* Loss reduction is an I^2R-proportional proxy (see code comments),")
print("  intended as an order-of-magnitude pitch figure, not a load-flow result.")
print("=" * 70)

# ---------------------------------------------------------------------------
# 4. Save results + a plot for the deck/dashboard
# ---------------------------------------------------------------------------
with_system.to_csv("results_with_system.csv", index=False)
baseline.to_csv("results_baseline.csv", index=False)

fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

axes[0].plot(with_system["timestamp"], baseline["grid_kw"], label="Grid draw — baseline (no battery)", color="#B71C1C")
axes[0].plot(with_system["timestamp"], with_system["grid_kw"], label="Grid draw — with NeighbourGrid", color="#2E7D32")
axes[0].set_ylabel("Grid draw (kW)")
axes[0].set_title(f"Grid Draw: Baseline vs NeighbourGrid ({N_HOUSEHOLDS} households, one simulated week)")
axes[0].legend()
axes[0].grid(alpha=0.3)

axes[1].plot(with_system["timestamp"], with_system["solar_kw"], label="Solar generation", color="#F9A825")
axes[1].plot(with_system["timestamp"], with_system["battery_soc_frac"] * 100, label="Battery SoC (%)", color="#1565C0")
axes[1].set_ylabel("Solar (kW) / SoC (%)")
axes[1].set_xlabel("Time")
axes[1].legend()
axes[1].grid(alpha=0.3)

plt.tight_layout()
plt.savefig("summary.png", dpi=150)
print("\nSaved: results_with_system.csv, results_baseline.csv, summary.png")
