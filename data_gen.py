"""
data_gen.py
-----------
Layer 1 of NeighbourGrid: produces the hourly solar generation and
household demand data the scheduler runs against.

IMPORTANT — network note:
This sandbox cannot reach the NASA POWER API (power.larc.nasa.gov) from
here, so this script uses a physically-reasonable SYNTHETIC clear-sky solar
model instead of live irradiance data. The function `fetch_nasa_power_irradiance()`
below shows exactly how to swap in the real API call — run that version on
your own laptop (which has normal internet access) before your final demo,
so your numbers come from real data for the pitch.

Everything downstream (scheduler.py, run_simulation.py) only cares about
getting a DataFrame with columns [timestamp, solar_kw, household_id, load_kw] —
so swapping the data source here doesn't require touching any other file.
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1. SOLAR GENERATION
# ---------------------------------------------------------------------------

def fetch_nasa_power_irradiance(lat, lon, start_date, end_date):
    """
    Real-data version — run this on a machine with internet access.

    NASA POWER API is free and needs no API key. Example endpoint:

        https://power.larc.nasa.gov/api/temporal/hourly/point?
            parameters=ALLSKY_SFC_SW_DWN&community=RE&
            longitude={lon}&latitude={lat}&
            start={start_date}&end={end_date}&format=JSON

    Uncomment and use this on your laptop:

        import requests
        url = (
            "https://power.larc.nasa.gov/api/temporal/hourly/point"
            f"?parameters=ALLSKY_SFC_SW_DWN&community=RE"
            f"&longitude={lon}&latitude={lat}"
            f"&start={start_date}&end={end_date}&format=JSON"
        )
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
        # data is {"YYYYMMDDHH": irradiance_wm2, ...} — convert to a DataFrame
        # and feed irradiance_to_generation_kw() below.
    """
    raise NotImplementedError(
        "No internet access in this environment — run this function on your "
        "own machine, then feed its output into irradiance_to_generation_kw()."
    )


def irradiance_to_generation_kw(irradiance_wm2, panel_kwp=5.0, derate=0.80):
    """
    Converts solar irradiance (W/m^2) into an estimated array output (kW).

    panel_kwp : installed peak capacity of the community solar array (kWp).
                5 kWp is a reasonable size to pair with a 15-household,
                25 kWh battery cluster — adjust to match your pitch.
    derate    : accounts for panel temperature losses, inverter efficiency,
                soiling, wiring losses. 0.75-0.85 is a realistic real-world
                range; 0.80 is a defensible default to quote to a panel.

    Standard test conditions define panel_kwp at 1000 W/m^2, so scale linearly.
    """
    return panel_kwp * (np.asarray(irradiance_wm2) / 1000.0) * derate


def synthetic_clear_sky_irradiance(hours, cloud_seed=0, cloudiness=0.15):
    """
    Physically-shaped synthetic irradiance for a mid-latitude Indian city:
    zero at night, a smooth bell curve peaking near solar noon, with random
    cloud-driven dips layered on top so the data isn't unrealistically clean.

    hours       : array of hour-of-day values (0-23), can span multiple days
    cloudiness  : 0 = perfectly clear every day, higher = more cloud noise
    """
    rng = np.random.default_rng(cloud_seed)
    hour_of_day = np.asarray(hours) % 24

    # Bell curve: sunrise ~6:00, sunset ~18:30, peak ~12:15, peak ~950 W/m^2
    daylight = np.clip(np.sin(np.pi * (hour_of_day - 6) / 12.5), 0, None)
    base_irradiance = 950 * daylight

    # Cloud noise: multiplicative dips, correlated hour-to-hour (not pure noise)
    n = len(hour_of_day)
    cloud_walk = np.cumsum(rng.normal(0, cloudiness, size=n))
    cloud_factor = np.clip(1 - 0.5 * np.abs(np.sin(cloud_walk)), 0.3, 1.0)

    return base_irradiance * cloud_factor


# ---------------------------------------------------------------------------
# 2. HOUSEHOLD DEMAND
# ---------------------------------------------------------------------------

def synthetic_household_load_kw(hours, household_id, daily_kwh=3.5, seed=0):
    """
    Builds an hourly load curve (kW) for one household, shaped around the
    two peaks typical of Indian residential consumption (CEA/DISCOM
    published patterns): a morning peak ~06:00-09:00 and a larger evening
    peak ~18:00-22:00, with a low daytime base load.

    daily_kwh : target average daily consumption for this household
                (3-4 kWh/day matches the report's residential benchmark)
    """
    rng = np.random.default_rng(seed + household_id)
    hour_of_day = np.asarray(hours) % 24

    morning_peak = 1.3 * np.exp(-0.5 * ((hour_of_day - 7.5) / 1.3) ** 2)
    evening_peak = 1.8 * np.exp(-0.5 * ((hour_of_day - 19.5) / 1.8) ** 2)
    base_load = 0.15  # always-on fridge/standby load

    shape = base_load + morning_peak + evening_peak

    # Scale so the average day matches daily_kwh, then add household-specific
    # random variation so 15 households don't look identical.
    scale = daily_kwh / (shape[:24].sum() if len(shape) >= 24 else shape.sum() / (len(shape) / 24))
    load = shape * scale
    noise = rng.normal(1.0, 0.12, size=len(load))
    return np.clip(load * noise, 0.05, None)


# ---------------------------------------------------------------------------
# 3. TOP-LEVEL BUILDER — what run_simulation.py actually calls
# ---------------------------------------------------------------------------

def build_week_dataset(n_households=15, panel_kwp=5.0, start="2026-01-01", seed=42):
    """
    Returns two tidy DataFrames for one simulated week (168 hours):

      solar_df : [timestamp, solar_kw]                — one shared array
      load_df  : [timestamp, household_id, load_kw]    — long format, all homes

    Everything is hourly. Change n_households / panel_kwp to match the
    cluster size you're pitching (report default: 15 homes, 25 kWh battery).
    """
    timestamps = pd.date_range(start=start, periods=24 * 7, freq="h")
    hours = timestamps.hour + 24 * (timestamps - timestamps[0]).days

    irradiance = synthetic_clear_sky_irradiance(hours, cloud_seed=seed)
    solar_kw = irradiance_to_generation_kw(irradiance, panel_kwp=panel_kwp)
    solar_df = pd.DataFrame({"timestamp": timestamps, "solar_kw": solar_kw})

    rows = []
    for hh in range(n_households):
        load_kw = synthetic_household_load_kw(hours, household_id=hh, seed=seed)
        for ts, lk in zip(timestamps, load_kw):
            rows.append({"timestamp": ts, "household_id": hh, "load_kw": lk})
    load_df = pd.DataFrame(rows)

    return solar_df, load_df


if __name__ == "__main__":
    solar_df, load_df = build_week_dataset()
    print(solar_df.head(10))
    print(load_df.head(10))
    print(f"\nTotal solar generation over the week: {solar_df['solar_kw'].sum():.1f} kWh")
    total_load = load_df.groupby("timestamp")["load_kw"].sum()
    print(f"Total household demand over the week: {total_load.sum():.1f} kWh")
