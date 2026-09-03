"""
scheduler.py
------------
Layer 2 of NeighbourGrid: the priority-order scheduling heuristic described
in Section 3.2 of the report. Runs hour-by-hour over the dataset from
data_gen.py and decides, for every hour, how much of the neighbourhood's
demand is met by direct solar, the shared battery, or the grid.

Priority order each hour:
  1. Match solar directly to concurrent household demand (zero loss, zero cost)
  2. Charge the battery with any solar surplus (up to power/SoC limits)
  3. Discharge the battery to cover any remaining deficit
  4. Draw the residual from the grid

This is intentionally a greedy heuristic, not a full MILP — see Section 3.2
of the report for why that trade-off is the right one for a pilot-stage
system (explainable, fast, and re-run every hour so forecast errors don't
compound).
"""

from dataclasses import dataclass, field
import pandas as pd


@dataclass
class Battery:
    """A single shared community battery serving the whole cluster."""
    capacity_kwh: float = 25.0          # usable capacity (report default: 20-30 kWh)
    max_charge_kw: float = 10.0         # power limit, charging
    max_discharge_kw: float = 10.0      # power limit, discharging
    round_trip_efficiency: float = 0.92  # typical LFP round-trip efficiency
    soc_kwh: float = field(default=None)  # current state of charge
    min_soc_frac: float = 0.10          # don't discharge below 10% (cycle-life protection)

    def __post_init__(self):
        if self.soc_kwh is None:
            self.soc_kwh = 0.5 * self.capacity_kwh  # start at 50%

    def charge(self, surplus_kw, hours=1.0):
        """Charge with available surplus power for `hours`. Returns kW actually absorbed."""
        room_kwh = self.capacity_kwh - self.soc_kwh
        max_by_power = self.max_charge_kw * hours
        max_by_room = room_kwh / self.round_trip_efficiency
        charge_kw = min(surplus_kw, max_by_power / hours, max_by_room / hours)
        charge_kw = max(charge_kw, 0)
        self.soc_kwh += charge_kw * hours * self.round_trip_efficiency
        return charge_kw

    def discharge(self, deficit_kw, hours=1.0, floor_frac=None):
        """
        Discharge to cover a deficit for `hours`. Returns kW actually delivered.

        floor_frac : SoC fraction the battery won't discharge below for THIS
                     call. Defaults to `min_soc_frac`. The scheduler uses this
                     to implement peak-reserve logic — see `reserve_soc_frac`
                     in run_priority_schedule().
        """
        floor = self.min_soc_frac if floor_frac is None else max(floor_frac, self.min_soc_frac)
        usable_kwh = self.soc_kwh - floor * self.capacity_kwh
        max_by_power = self.max_discharge_kw * hours
        max_by_soc = max(usable_kwh, 0)
        discharge_kw = min(deficit_kw, max_by_power / hours, max_by_soc / hours)
        discharge_kw = max(discharge_kw, 0)
        self.soc_kwh -= discharge_kw * hours
        return discharge_kw

    def soc_fraction(self):
        return self.soc_kwh / self.capacity_kwh


def run_priority_schedule(solar_df, load_df, battery: Battery, tod_peak_hours=(18, 22),
                           reserve_soc_frac=0.0):
    """
    Runs the hour-by-hour priority-order allocation described above.

    tod_peak_hours    : (start_hour, end_hour) treated as the DISCOM's declared
                         peak window.
    reserve_soc_frac  : PEAK-RESERVE RULE. Outside the peak window, the battery
                         will not discharge below this SoC fraction, holding
                         capacity back specifically for the peak window (where
                         it's still allowed to discharge down to min_soc_frac).
                         0.0 (default) = old behaviour, no reserve.
                         Try 0.4-0.5 to see real peak-shaving improve at the
                         cost of some energy-side savings — this is the fix
                         for the "battery is empty before the peak" finding.

    Returns a DataFrame, one row per hour, with the full energy breakdown —
    this is what run_simulation.py uses to compute the Section 4.2 metrics.
    """
    total_load = (
        load_df.groupby("timestamp")["load_kw"].sum().reset_index().rename(columns={"load_kw": "total_load_kw"})
    )
    df = solar_df.merge(total_load, on="timestamp").sort_values("timestamp").reset_index(drop=True)

    records = []
    for _, row in df.iterrows():
        solar_kw, load_kw = row["solar_kw"], row["total_load_kw"]
        hour = row["timestamp"].hour

        # Step 1: direct solar-to-load match
        direct_solar_kw = min(solar_kw, load_kw)
        remaining_load_kw = load_kw - direct_solar_kw
        surplus_solar_kw = solar_kw - direct_solar_kw

        # Step 2: charge battery with surplus solar
        battery_charge_kw = battery.charge(surplus_solar_kw) if surplus_solar_kw > 0 else 0.0
        curtailed_solar_kw = surplus_solar_kw - battery_charge_kw  # unused if battery full

        # Step 3: discharge battery to cover remaining load — respecting the
        # peak-reserve floor when we're outside the declared peak window
        in_peak_window = tod_peak_hours[0] <= hour < tod_peak_hours[1]
        floor_frac = battery.min_soc_frac if in_peak_window else reserve_soc_frac
        battery_discharge_kw = (
            battery.discharge(remaining_load_kw, floor_frac=floor_frac) if remaining_load_kw > 0 else 0.0
        )
        remaining_load_kw -= battery_discharge_kw

        # Step 4: whatever's left comes from the grid
        grid_kw = max(remaining_load_kw, 0)

        dr_signal_fired = in_peak_window and grid_kw > 0.3 * load_kw  # simple trigger rule

        records.append({
            "timestamp": row["timestamp"],
            "solar_kw": solar_kw,
            "total_load_kw": load_kw,
            "direct_solar_kw": direct_solar_kw,
            "battery_charge_kw": battery_charge_kw,
            "battery_discharge_kw": battery_discharge_kw,
            "curtailed_solar_kw": curtailed_solar_kw,
            "grid_kw": grid_kw,
            "battery_soc_frac": battery.soc_fraction(),
            "in_peak_window": in_peak_window,
            "dr_signal_fired": dr_signal_fired,
        })

    return pd.DataFrame(records)


def run_baseline_no_battery(solar_df, load_df):
    """
    'Without NeighbourGrid' comparison case: only direct solar-to-load
    matching happens (as if every home just had its own uncoordinated solar
    panel and nothing else) — no shared battery, no scheduling. Everything
    else is drawn straight from the grid. This is the baseline the report's
    Section 4.2 metrics are measured against.
    """
    total_load = (
        load_df.groupby("timestamp")["load_kw"].sum().reset_index().rename(columns={"load_kw": "total_load_kw"})
    )
    df = solar_df.merge(total_load, on="timestamp").sort_values("timestamp").reset_index(drop=True)

    df["direct_solar_kw"] = df[["solar_kw", "total_load_kw"]].min(axis=1)
    df["grid_kw"] = (df["total_load_kw"] - df["direct_solar_kw"]).clip(lower=0)
    df["curtailed_solar_kw"] = (df["solar_kw"] - df["direct_solar_kw"]).clip(lower=0)
    return df
