"""
app.py
------
Layer: live demo dashboard (Step 8 of the build plan).

Interactive Streamlit app wrapping data_gen.py + scheduler.py so you can:
  - Adjust household count, solar panel size, battery size, and the
    peak-reserve rule live, in front of judges
  - See the grid-draw comparison plot and Section 4.2 metrics update instantly
  - Directly demonstrate the "battery drains before the peak" finding, and
    show how the peak-reserve rule fixes it (with the energy-savings trade-off)

Run:
    pip install streamlit
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

from data_gen import build_week_dataset
from scheduler import Battery, run_priority_schedule, run_baseline_no_battery


st.set_page_config(page_title="NeighbourGrid — Live Demo", layout="wide")

st.title("NeighbourGrid — Neighbourhood-Scale Flexibility Dashboard")
st.caption(
    "Forecast-driven shared-battery scheduling for grid reliability | "
    "Schneider Electric Hackathon 2026 — Challenge 03"
)

# ---------------------------------------------------------------------------
# Sidebar — all the levers you can pull live during the demo
# ---------------------------------------------------------------------------
st.sidebar.header("Cluster configuration")
n_households = st.sidebar.slider("Number of households", 5, 30, 15)
panel_kwp = st.sidebar.slider("Community solar array size (kWp)", 2.0, 15.0, 5.0, step=0.5)

st.sidebar.header("Shared battery configuration")
battery_kwh = st.sidebar.slider("Battery capacity (kWh)", 10.0, 80.0, 25.0, step=5.0)
battery_power_kw = st.sidebar.slider("Battery max charge/discharge power (kW)", 2.0, 20.0, 8.0, step=1.0)

st.sidebar.header("Peak-reserve rule")
st.sidebar.markdown(
    "Holds battery charge back outside the peak window so it's available "
    "*during* the peak, instead of draining early. Trades some energy "
    "savings for peak-shaving."
)
reserve_enabled = st.sidebar.checkbox("Enable peak-reserve rule", value=False)
reserve_frac = st.sidebar.slider(
    "Reserve floor (% SoC held back outside peak window)",
    0, 70, 40, step=5, disabled=not reserve_enabled,
) / 100.0 if reserve_enabled else 0.0

st.sidebar.header("DISCOM peak window")
peak_start, peak_end = st.sidebar.slider("Declared peak window (hour of day)", 0, 23, (18, 22))

seed = st.sidebar.number_input("Random seed (change for a different simulated week)", value=42, step=1)

# ---------------------------------------------------------------------------
# Run the simulation with current settings
# ---------------------------------------------------------------------------
solar_df, load_df = build_week_dataset(n_households=n_households, panel_kwp=panel_kwp, seed=int(seed))

battery = Battery(capacity_kwh=battery_kwh, max_charge_kw=battery_power_kw, max_discharge_kw=battery_power_kw)
with_system = run_priority_schedule(
    solar_df, load_df, battery,
    tod_peak_hours=(peak_start, peak_end),
    reserve_soc_frac=reserve_frac,
)
baseline = run_baseline_no_battery(solar_df, load_df)

# ---------------------------------------------------------------------------
# Metrics (Section 4.2 of the report)
# ---------------------------------------------------------------------------
peak_grid_with = with_system["grid_kw"].max()
peak_grid_baseline = baseline["grid_kw"].max()
peak_reduction_pct = 100 * (peak_grid_baseline - peak_grid_with) / peak_grid_baseline

total_solar = solar_df["solar_kw"].sum()
self_consumed_with = (with_system["direct_solar_kw"] + with_system["battery_charge_kw"]).sum()
self_consumption_with_pct = 100 * self_consumed_with / total_solar

total_grid_kwh_with = with_system["grid_kw"].sum()
total_grid_kwh_baseline = baseline["grid_kw"].sum()
grid_energy_reduction_pct = 100 * (total_grid_kwh_baseline - total_grid_kwh_with) / total_grid_kwh_baseline

loss_proxy_with = (with_system["grid_kw"] ** 2).sum()
loss_proxy_baseline = (baseline["grid_kw"] ** 2).sum()
loss_reduction_pct = 100 * (loss_proxy_baseline - loss_proxy_with) / loss_proxy_baseline

# ---------------------------------------------------------------------------
# Layout: metric cards
# ---------------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Peak grid draw", f"{peak_grid_with:.2f} kW", f"-{peak_reduction_pct:.1f}% vs baseline")
c2.metric("Weekly grid energy", f"{total_grid_kwh_with:.0f} kWh", f"-{grid_energy_reduction_pct:.1f}% vs baseline")
c3.metric("Renewable self-consumption", f"{self_consumption_with_pct:.1f}%")
c4.metric("Est. technical loss reduction*", f"{loss_reduction_pct:.1f}%")

st.caption("*I²R-proportional proxy — order-of-magnitude pitch figure, not a load-flow study.")

# ---------------------------------------------------------------------------
# Main plot
# ---------------------------------------------------------------------------
fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)

axes[0].plot(with_system["timestamp"], baseline["grid_kw"], label="Grid draw — baseline (no battery)", color="#B71C1C")
axes[0].plot(with_system["timestamp"], with_system["grid_kw"], label="Grid draw — with NeighbourGrid", color="#2E7D32")
axes[0].axhspan(0, 1, alpha=0)  # keep axis stable
axes[0].set_ylabel("Grid draw (kW)")
axes[0].set_title(f"Grid Draw: Baseline vs NeighbourGrid — {n_households} households, one simulated week")
axes[0].legend(loc="upper right")
axes[0].grid(alpha=0.3)

axes[1].plot(with_system["timestamp"], with_system["solar_kw"], label="Solar generation (kW)", color="#F9A825")
axes[1].plot(with_system["timestamp"], with_system["battery_soc_frac"] * 100, label="Battery SoC (%)", color="#1565C0")
if reserve_enabled:
    axes[1].axhline(reserve_frac * 100, color="#1565C0", linestyle="--", alpha=0.5, label="Reserve floor (outside peak)")
axes[1].set_ylabel("Solar (kW) / SoC (%)")
axes[1].set_xlabel("Time")
axes[1].legend(loc="upper right")
axes[1].grid(alpha=0.3)

plt.tight_layout()
st.pyplot(fig)

# ---------------------------------------------------------------------------
# Raw data (collapsed by default — useful if a judge asks to see it)
# ---------------------------------------------------------------------------
with st.expander("Show hourly data table"):
    st.dataframe(with_system, use_container_width=True)

with st.expander("What the peak-reserve rule is doing (for Q&A)"):
    st.markdown(
        """
        By default, the battery discharges greedily to cover any deficit,
        which often drains it **before** the evening peak hits — especially
        on lower-solar days. The peak-reserve rule holds the battery above a
        chosen SoC floor *outside* the declared peak window, so there's
        capacity specifically saved for the peak itself.

        This is a real trade-off, not a free win: holding charge back means
        slightly less solar is captured/used on some hours, so weekly energy
        savings can dip slightly even as peak-shaving improves. Try toggling
        the rule on/off with the sidebar to see both numbers move.
        """
    )
