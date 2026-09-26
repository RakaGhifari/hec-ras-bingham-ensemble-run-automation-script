"""
======================================================================
HEC-RAS BINGHAM ENSEMBLE — TRAVEL TIME ANALYSIS
======================================================================

Extract downstream travel time from archived Bingham HEC-RAS ensemble
HDF files.

Workflow
--------
For each ensemble run:

    1. Read water surface elevation.
    2. Read simulation time.
    3. Read cell minimum elevation.
    4. Calculate water depth.
    5. Evaluate the configured downstream bridge/profile cells.
    6. Detect arrival when depth exceeds the specified threshold.
    7. Define run-level arrival as the earliest bridge-cell arrival.
    8. Calculate bridge arrival statistics.
    9. Compare simulated arrival with the observed travel time.

The number of ensemble runs is determined automatically from
PARAMETER_CSV. No fixed number of runs is required.

Required parameter CSV columns
------------------------------
    Run
    Cv
    Yield_Stress_Pa
    Viscosity_Pa_s

Configuration
-------------
The following settings are read from config.py:

    RESULTS_DIR
    PARAMETER_CSV
    TRAVEL_TIME_CSV
    OBSERVED_TRAVEL_TIME_MIN
    BRIDGE_DEPTH_THRESHOLD_M
    BRIDGE_CELLS
    WSE_PATH
    TIME_PATH
    ELEVATION_PATH

Optional configuration
----------------------
    HDF_FILE_PATTERN

Default:

    run_{run_id:03d}.p31.hdf

Output
------
    TRAVEL_TIME_CSV

Output columns
--------------
    Run
    Cv
    Yield_Stress_Pa
    Viscosity_Pa_s
    Arrival_h01_min
    Bridge_Earliest_min
    Bridge_Latest_min
    Bridge_Mean_min
    Bridge_Median_min
    Bridge_Spread_min
    N_Bridge_Cells
    TT_Error_min
    Abs_TT_Error_min
    Relative_Error_pct
    Temporal_Score

Notes
-----
The temporal analysis reports the travel-time performance of the
ensemble relative to the observed travel time. It does not select
a single preferred rheological scenario.
======================================================================
"""

from pathlib import Path
import sys

import h5py
import numpy as np
import pandas as pd


# ======================================================================
# PROJECT ROOT
# ======================================================================

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ======================================================================
# CONFIGURATION
# ======================================================================

try:
    from config.config import (
        RESULTS_DIR,
        PARAMETER_CSV,
        TRAVEL_TIME_CSV,
        OBSERVED_TRAVEL_TIME_MIN,
        BRIDGE_DEPTH_THRESHOLD_M,
        BRIDGE_CELLS,
        WSE_PATH,
        TIME_PATH,
        ELEVATION_PATH,
    )
except ImportError as exc:
    raise SystemExit(
        "\nConfiguration file not found.\n\n"
        "Please create:\n"
        "    config/config.py\n\n"
        "from:\n"
        "    config/config_template.py\n"
    ) from exc


# ======================================================================
# OPTIONAL CONFIGURATION
# ======================================================================

try:
    from config.config import HDF_FILE_PATTERN
except ImportError:
    HDF_FILE_PATTERN = "run_{run_id:03d}.p31.hdf"


# ======================================================================
# REQUIRED PARAMETER COLUMNS
# ======================================================================

REQUIRED_PARAMETER_COLUMNS = [
    "Run",
    "Cv",
    "Yield_Stress_Pa",
    "Viscosity_Pa_s",
]


# ======================================================================
# HDF FILE PATH
# ======================================================================

def get_hdf_path(run_id: int) -> Path:
    """
    Construct the archived HDF path for a given ensemble run.
    """

    return RESULTS_DIR / HDF_FILE_PATTERN.format(
        run_id=run_id
    )


# ======================================================================
# LOAD PARAMETER TABLE
# ======================================================================

def load_parameter_table(
    parameter_csv: Path,
) -> pd.DataFrame:
    """
    Load and validate the ensemble parameter table.

    The number of ensemble runs is determined directly from the CSV.
    """

    if not parameter_csv.exists():
        raise FileNotFoundError(
            f"Parameter CSV not found:\n"
            f"{parameter_csv}"
        )

    params = pd.read_csv(parameter_csv)

    # ------------------------------------------------------------------
    # Check required columns
    # ------------------------------------------------------------------

    missing = [
        column
        for column in REQUIRED_PARAMETER_COLUMNS
        if column not in params.columns
    ]

    if missing:
        raise ValueError(
            "Missing required parameter columns:\n"
            f"{missing}"
        )

    params = params[
        REQUIRED_PARAMETER_COLUMNS
    ].copy()

    # ------------------------------------------------------------------
    # Validate Run IDs
    # ------------------------------------------------------------------

    try:
        params["Run"] = params["Run"].astype(int)
    except Exception as exc:
        raise ValueError(
            "The Run column contains invalid values."
        ) from exc

    duplicated = (
        params.loc[
            params["Run"].duplicated(),
            "Run",
        ]
        .tolist()
    )

    if duplicated:
        raise ValueError(
            "Duplicate Run IDs found:\n"
            f"{duplicated}"
        )

    params = (
        params
        .sort_values("Run")
        .reset_index(drop=True)
    )

    # ------------------------------------------------------------------
    # Validate sequential Run IDs
    #
    # The CSV itself defines the ensemble size.
    # ------------------------------------------------------------------

    n_runs = len(params)

    expected_runs = set(
        range(1, n_runs + 1)
    )

    actual_runs = set(
        params["Run"]
    )

    if actual_runs != expected_runs:
        raise ValueError(
            "Run numbers must be sequential "
            f"from 1 to {n_runs}.\n"
            f"Found: {sorted(actual_runs)}"
        )

    return params


# ======================================================================
# VALIDATE HDF STRUCTURE
# ======================================================================

def validate_hdf_structure(
    hdf: h5py.File,
) -> None:
    """
    Verify that the required HDF datasets exist.
    """

    required_paths = [
        WSE_PATH,
        TIME_PATH,
        ELEVATION_PATH,
    ]

    missing = [
        path
        for path in required_paths
        if path not in hdf
    ]

    if missing:
        raise KeyError(
            "Required HDF dataset(s) not found:\n"
            + "\n".join(
                f"    {path}"
                for path in missing
            )
        )


# ======================================================================
# VALIDATE BRIDGE CELLS
# ======================================================================

def validate_bridge_cells(
    bridge_cells,
    n_cells: int,
) -> list[int]:
    """
    Validate bridge/profile cell indices against the HDF mesh.

    Invalid cell indices are skipped. The function raises an error only
    if no valid bridge/profile cells remain.
    """

    valid_cells = []
    invalid_cells = []

    for cell in bridge_cells:
        cell = int(cell)

        if 0 <= cell < n_cells:
            valid_cells.append(cell)
        else:
            invalid_cells.append(cell)

    if invalid_cells:
        print(
            "WARNING: The following bridge/profile cell indices "
            "are outside the HDF mesh and will be skipped:"
        )
        print(invalid_cells)

    if not valid_cells:
        raise ValueError(
            "No valid bridge/profile cells remain."
        )

    return valid_cells


# ======================================================================
# EXTRACT ONE RUN
# ======================================================================

def extract_run(
    run_id: int,
) -> dict:
    """
    Extract travel-time statistics for one ensemble run.

    Run-level arrival time is defined as the earliest arrival among
    the configured bridge/profile cells.
    """

    path = get_hdf_path(run_id)

    if not path.exists():
        raise FileNotFoundError(
            f"HDF file not found:\n"
            f"{path}"
        )

    # ------------------------------------------------------------------
    # Read HDF datasets
    # ------------------------------------------------------------------

    with h5py.File(path, "r") as f:

        validate_hdf_structure(f)

        wse = np.asarray(
            f[WSE_PATH][:]
        )

        time_days = np.asarray(
            f[TIME_PATH][:]
        )

        elevation = np.asarray(
            f[ELEVATION_PATH][:]
        )

    # ------------------------------------------------------------------
    # Validate dataset dimensions
    # ------------------------------------------------------------------

    if wse.ndim != 2:
        raise ValueError(
            "Water Surface dataset is expected to have "
            "dimensions: time × cell."
        )

    if time_days.ndim != 1:
        raise ValueError(
            "Time dataset is expected to be one-dimensional."
        )

    if elevation.ndim != 1:
        raise ValueError(
            "Elevation dataset is expected to be one-dimensional."
        )

    if wse.shape[0] != len(time_days):
        raise ValueError(
            "WSE time dimension does not match the HDF time vector.\n"
            f"WSE time steps: {wse.shape[0]}\n"
            f"Time values: {len(time_days)}"
        )

    if wse.shape[1] != len(elevation):
        raise ValueError(
            "WSE cell dimension does not match the elevation vector.\n"
            f"WSE cells: {wse.shape[1]}\n"
            f"Elevation cells: {len(elevation)}"
        )

    # ------------------------------------------------------------------
    # Convert HEC-RAS time from days to minutes
    # ------------------------------------------------------------------

    time_min = (
        time_days - time_days[0]
    ) * 24.0 * 60.0

    # ------------------------------------------------------------------
    # Calculate water depth
    # ------------------------------------------------------------------

    depth = (
        wse
        - elevation[None, :]
    )

    # ------------------------------------------------------------------
    # Validate bridge/profile cells
    # ------------------------------------------------------------------

    valid_bridge_cells = validate_bridge_cells(
        BRIDGE_CELLS,
        depth.shape[1],
    )

    # ------------------------------------------------------------------
    # Detect arrival at each bridge/profile cell
    # ------------------------------------------------------------------

    arrivals = []

    for cell in valid_bridge_cells:

        cell_depth = depth[:, cell]

        valid_time_mask = (
            ~np.isnan(cell_depth)
            & ~np.isnan(time_min)
        )

        indices = np.where(
            valid_time_mask
            & (
                cell_depth
                > BRIDGE_DEPTH_THRESHOLD_M
            )
        )[0]

        if len(indices):

            first_index = indices[0]

            arrival_time = float(
                time_min[first_index]
            )

            arrivals.append(
                arrival_time
            )

    # ------------------------------------------------------------------
    # Calculate bridge arrival statistics
    # ------------------------------------------------------------------

    if not arrivals:

        arrival = np.nan
        earliest = np.nan
        latest = np.nan
        mean = np.nan
        median = np.nan
        spread = np.nan

    else:

        arrival_values = np.asarray(
            arrivals,
            dtype=float,
        )

        # Run-level arrival is the earliest bridge-cell arrival.
        arrival = float(
            np.min(arrival_values)
        )

        earliest = float(
            np.min(arrival_values)
        )

        latest = float(
            np.max(arrival_values)
        )

        mean = float(
            np.mean(arrival_values)
        )

        median = float(
            np.median(arrival_values)
        )

        spread = float(
            latest - earliest
        )

    return {
        "Run": run_id,
        "Arrival_h01_min": arrival,
        "Bridge_Earliest_min": earliest,
        "Bridge_Latest_min": latest,
        "Bridge_Mean_min": mean,
        "Bridge_Median_min": median,
        "Bridge_Spread_min": spread,
        "N_Bridge_Cells": len(arrivals),
    }


# ======================================================================
# CALCULATE TEMPORAL METRICS
# ======================================================================

def calculate_temporal_metrics(
    tt: pd.DataFrame,
) -> pd.DataFrame:
    """
    Calculate travel-time errors relative to the observed travel time.
    """

    if tt.empty:
        return tt

    # ------------------------------------------------------------------
    # Round arrival time to the nearest minute.
    #
    # This preserves the original study workflow.
    # ------------------------------------------------------------------

    tt["Arrival_h01_min"] = (
        tt["Arrival_h01_min"]
        .round()
        .astype("Int64")
    )

    # ------------------------------------------------------------------
    # Signed travel-time error
    # ------------------------------------------------------------------

    tt["TT_Error_min"] = (
        tt["Arrival_h01_min"].astype(float)
        - OBSERVED_TRAVEL_TIME_MIN
    )

    # ------------------------------------------------------------------
    # Absolute travel-time error
    # ------------------------------------------------------------------

    tt["Abs_TT_Error_min"] = (
        tt["TT_Error_min"].abs()
    )

    # ------------------------------------------------------------------
    # Relative error
    # ------------------------------------------------------------------

    if OBSERVED_TRAVEL_TIME_MIN == 0:

        tt["Relative_Error_pct"] = np.nan

    else:

        tt["Relative_Error_pct"] = (
            tt["Abs_TT_Error_min"]
            / OBSERVED_TRAVEL_TIME_MIN
            * 100.0
        )

    # ------------------------------------------------------------------
    # Temporal score
    #
    # Original study formulation:
    #
    #     1 - absolute error / 2
    #
    # clipped to [0, 1].
    # ------------------------------------------------------------------

    tt["Temporal_Score"] = (
        1.0
        - tt["Abs_TT_Error_min"] / 2.0
    ).clip(0, 1)

    return tt


# ======================================================================
# MAIN
# ======================================================================

def main() -> None:

    # ==================================================================
    # LOAD PARAMETER TABLE
    # ==================================================================

    params = load_parameter_table(
        PARAMETER_CSV
    )

    total_runs = len(params)

    # ==================================================================
    # PRINT CONFIGURATION
    # ==================================================================

    print(
        "\n" + "=" * 80
    )

    print(
        "HEC-RAS BINGHAM ENSEMBLE — TRAVEL TIME ANALYSIS"
    )

    print(
        "=" * 80
    )

    print(
        f"Parameter file       : {PARAMETER_CSV}"
    )

    print(
        f"Results folder       : {RESULTS_DIR}"
    )

    print(
        f"Total ensemble runs  : {total_runs}"
    )

    print(
        f"Bridge/profile cells : {len(BRIDGE_CELLS)}"
    )

    print(
        f"Depth threshold      : "
        f"{BRIDGE_DEPTH_THRESHOLD_M} m"
    )

    print(
        f"Observed travel time : "
        f"{OBSERVED_TRAVEL_TIME_MIN} min"
    )

    print(
        f"Output               : {TRAVEL_TIME_CSV}"
    )

    print(
        "=" * 80
    )

    # ==================================================================
    # PROCESS ENSEMBLE
    # ==================================================================

    records = []
    missing_runs = []
    failed_runs = []

    for _, parameter_row in params.iterrows():

        run_id = int(
            parameter_row["Run"]
        )

        hdf_path = get_hdf_path(
            run_id
        )

        print(
            f"\nRUN {run_id:03d}/{total_runs}"
        )

        # ==============================================================
        # MISSING HDF
        # ==============================================================

        if not hdf_path.exists():

            print(
                f"Run {run_id:03d}: HDF missing"
            )

            missing_runs.append(
                run_id
            )

            continue

        # ==============================================================
        # EXTRACT TRAVEL TIME
        # ==============================================================

        try:

            row = extract_run(
                run_id
            )

            # ----------------------------------------------------------
            # Add ensemble parameters
            # ----------------------------------------------------------

            parameter_values = (
                parameter_row.to_dict()
            )

            parameter_values.update(
                row
            )

            records.append(
                parameter_values
            )

            arrival = row[
                "Arrival_h01_min"
            ]

            if pd.isna(arrival):

                print(
                    f"Run {run_id:03d}: "
                    "no arrival detected"
                )

            else:

                print(
                    f"Run {run_id:03d}: "
                    f"arrival={arrival:.2f} min"
                )

        # ==============================================================
        # EXTRACTION FAILURE
        # ==============================================================

        except Exception as exc:

            print(
                f"Run {run_id:03d}: "
                f"FAILED — {exc}"
            )

            failed_runs.append(
                {
                    "Run": run_id,
                    "Error": str(exc),
                }
            )

    # ==================================================================
    # CREATE RESULT TABLE
    # ==================================================================

    tt = pd.DataFrame(
        records
    )

    # ==================================================================
    # CALCULATE TEMPORAL METRICS
    # ==================================================================

    tt = calculate_temporal_metrics(
        tt
    )

    # ==================================================================
    # SAVE RESULTS
    # ==================================================================

    TRAVEL_TIME_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tt.to_csv(
        TRAVEL_TIME_CSV,
        index=False,
    )

    # ==================================================================
    # SUMMARY
    # ==================================================================

    successful = len(records)
    missing = len(missing_runs)
    failed = len(failed_runs)

    print(
        "\n" + "=" * 80
    )

    print(
        "TRAVEL-TIME ANALYSIS FINISHED"
    )

    print(
        "=" * 80
    )

    print(
        f"Total parameter sets  : {total_runs}"
    )

    print(
        f"Successfully processed: {successful}"
    )

    print(
        f"Missing HDFs          : {missing}"
    )

    print(
        f"Failed extraction     : {failed}"
    )

    # ------------------------------------------------------------------
    # Travel-time summary
    # ------------------------------------------------------------------

    if not tt.empty:

        print(
            "\nTravel-time summary:"
        )

        print(
            tt["Arrival_h01_min"].describe()
        )

        exact_count = int(
            (
                tt["Abs_TT_Error_min"] == 0
            ).sum()
        )

        within_1 = int(
            (
                tt["Abs_TT_Error_min"] <= 1
            ).sum()
        )

        within_2 = int(
            (
                tt["Abs_TT_Error_min"] <= 2
            ).sum()
        )

        print(
            f"\nExact observed travel time "
            f"({OBSERVED_TRAVEL_TIME_MIN:g} min): "
            f"{exact_count}"
        )

        print(
            f"Within ±1 min: {within_1}"
        )

        print(
            f"Within ±2 min: {within_2}"
        )

    # ------------------------------------------------------------------
    # Missing HDF summary
    # ------------------------------------------------------------------

    if missing_runs:

        print(
            "\nMissing HDF runs:"
        )

        print(
            ", ".join(
                f"{run:03d}"
                for run in missing_runs
            )
        )

    # ------------------------------------------------------------------
    # Failed extraction summary
    # ------------------------------------------------------------------

    if failed_runs:

        print(
            "\nFailed extraction runs:"
        )

        for item in failed_runs:

            print(
                f"Run {item['Run']:03d}: "
                f"{item['Error']}"
            )

    # ------------------------------------------------------------------
    # Output path
    # ------------------------------------------------------------------

    print(
        "\nSaved:"
    )

    print(
        TRAVEL_TIME_CSV
    )

    print(
        "=" * 80
    )


# ======================================================================
# ENTRY POINT
# ======================================================================

if __name__ == "__main__":
    main()

