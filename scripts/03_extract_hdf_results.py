
"""
======================================================================
HEC-RAS BINGHAM ENSEMBLE — HDF RESULTS QC
by Raka Ghifari (2026)
======================================================================

Extract maximum-depth quality-control statistics from all archived
Bingham HEC-RAS HDF files.

The number of ensemble runs is determined automatically from
PARAMETER_CSV. No fixed number of runs is required.

Workflow
--------
    Parameter CSV
          |
          v
    Read Run IDs
          |
          v
    Find archived HDF for each run
          |
          v
    Read:
        - Water Surface
        - Cell Minimum Elevation
          |
          v
    Calculate:
        - Maximum depth
        - Mean depth
        - Number of cells with depth > thresholds
        - Valid cells
        - Total cells
        - HDF file size
          |
          v
    Save QC table

Required parameter CSV columns
------------------------------
    Run
    Cv
    Yield_Stress_Pa
    Viscosity_Pa_s

Output
------
    QC_CSV

Notes
-----
This script performs lightweight post-processing and quality control.

It does not modify the original HDF files.
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
        QC_CSV,
        WSE_PATH,
        ELEVATION_PATH,
    )

except ImportError as exc:

    raise SystemExit(
        "\n"
        "Configuration file not found.\n\n"
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

    # Default HEC-RAS plan naming convention.
    HDF_FILE_PATTERN = "run_{run_id:03d}.p31.hdf"


try:

    from config.config import DEPTH_THRESHOLDS

except ImportError:

    DEPTH_THRESHOLDS = (
        0,
        5,
        10,
        20,
        40,
    )


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

    The filename pattern can be changed through config.py using:

        HDF_FILE_PATTERN = "run_{run_id:03d}.p31.hdf"
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

    The number of runs is determined directly from the CSV.
    """

    if not parameter_csv.exists():

        raise FileNotFoundError(
            f"Parameter CSV not found:\n"
            f"{parameter_csv}"
        )


    params = pd.read_csv(
        parameter_csv
    )


    # ------------------------------------------------------------------
    # Required columns
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


    # ------------------------------------------------------------------
    # Keep the expected parameter columns
    # ------------------------------------------------------------------

    params = params[
        REQUIRED_PARAMETER_COLUMNS
    ].copy()


    # ------------------------------------------------------------------
    # Convert Run to integer
    # ------------------------------------------------------------------

    try:

        params["Run"] = (
            params["Run"]
            .astype(int)
        )

    except Exception as exc:

        raise ValueError(
            "Run column contains invalid values."
        ) from exc


    # ------------------------------------------------------------------
    # Check duplicate Run IDs
    # ------------------------------------------------------------------

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


    # ------------------------------------------------------------------
    # Sort
    # ------------------------------------------------------------------

    params = (
        params
        .sort_values("Run")
        .reset_index(drop=True)
    )


    # ------------------------------------------------------------------
    # Check sequential Run numbering
    #
    # No TOTAL_RUNS is required.
    # The CSV defines the ensemble size.
    # ------------------------------------------------------------------

    n_runs = len(params)

    expected_runs = set(
        range(1, n_runs + 1)
    )

    actual_runs = set(
        params["Run"].astype(int)
    )


    if actual_runs != expected_runs:

        raise ValueError(
            "Run numbers must be sequential "
            f"from 1 to {n_runs}.\n"
            f"Found: {sorted(actual_runs)}"
        )


    return params


# ======================================================================
# HDF VALIDATION
# ======================================================================

def validate_hdf_structure(
    hdf: h5py.File,
) -> None:
    """
    Check whether the required HDF datasets exist.
    """

    required_paths = [
        WSE_PATH,
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
# EXTRACT ONE HDF
# ======================================================================

def extract_one(
    hdf_path: Path,
) -> dict:
    """
    Extract maximum-depth QC statistics from one HDF file.
    """

    if not hdf_path.exists():

        raise FileNotFoundError(
            f"HDF file not found:\n"
            f"{hdf_path}"
        )


    # ------------------------------------------------------------------
    # Open HDF
    # ------------------------------------------------------------------

    with h5py.File(
        hdf_path,
        "r",
    ) as hdf:

        validate_hdf_structure(
            hdf
        )

        wse = hdf[
            WSE_PATH
        ][:]

        elevation = hdf[
            ELEVATION_PATH
        ][:]


    # ------------------------------------------------------------------
    # Validate dimensions
    # ------------------------------------------------------------------

    if wse.ndim < 2:

        raise ValueError(
            "Water Surface dataset must contain "
            "a time dimension and a cell dimension."
        )


    if elevation.ndim != 1:

        raise ValueError(
            "Elevation dataset is expected to "
            "contain one value per cell."
        )


    if wse.shape[-1] != len(elevation):

        raise ValueError(
            "Water Surface and elevation dimensions "
            "do not match.\n"
            f"WSE cells: {wse.shape[-1]}\n"
            f"Elevation cells: {len(elevation)}"
        )


    # ------------------------------------------------------------------
    # Maximum water surface elevation over time
    # ------------------------------------------------------------------

    max_wse = np.max(
        wse,
        axis=0,
    )


    # ------------------------------------------------------------------
    # Calculate maximum depth
    # ------------------------------------------------------------------

    max_depth = (
        max_wse
        - elevation
    )


    # ------------------------------------------------------------------
    # Mask invalid elevation cells
    # ------------------------------------------------------------------

    max_depth[
        np.isnan(elevation)
    ] = np.nan


    # ------------------------------------------------------------------
    # Remove negative numerical depth
    # ------------------------------------------------------------------

    max_depth[
        max_depth < 0
    ] = 0


    # ------------------------------------------------------------------
    # Valid depth cells
    # ------------------------------------------------------------------

    valid_mask = ~np.isnan(
        max_depth
    )


    valid_depth = max_depth[
        valid_mask
    ]


    if valid_depth.size == 0:

        raise ValueError(
            "No valid depth cells were found."
        )


    # ------------------------------------------------------------------
    # Basic statistics
    # ------------------------------------------------------------------

    values = {

        "Max_Depth_m":
            float(
                np.nanmax(
                    max_depth
                )
            ),

        "Mean_Depth_m":
            float(
                np.nanmean(
                    max_depth
                )
            ),

        "Valid_Cells":
            int(
                np.sum(
                    ~np.isnan(
                        elevation
                    )
                )
            ),

        "Total_Cells":
            int(
                len(elevation)
            ),
    }


    # ------------------------------------------------------------------
    # Depth threshold statistics
    # ------------------------------------------------------------------
    #
    # Preserve the original workflow thresholds:
    #
    #   > 0 m
    #   > 5 m
    #   > 10 m
    #   > 20 m
    #   > 40 m
    #
    # Additional thresholds can be supplied through config.py.
    # ------------------------------------------------------------------

    for threshold in DEPTH_THRESHOLDS:

        # Create a clean column name.
        threshold_text = (
            f"{threshold:g}"
        )

        column_name = (
            f"Cells_Depth_GT_"
            f"{threshold_text}"
        )


        values[column_name] = int(
            np.sum(
                max_depth > threshold
            )
        )


    return values


# ======================================================================
# MAIN
# ======================================================================

def main() -> None:

    # ==================================================================
    # LOAD PARAMETERS
    # ==================================================================

    params = load_parameter_table(
        PARAMETER_CSV
    )


    total_runs = len(
        params
    )


    # ==================================================================
    # PRINT HEADER
    # ==================================================================

    print(
        "\n" + "=" * 80
    )

    print(
        "HEC-RAS BINGHAM ENSEMBLE — HDF QC"
    )

    print(
        "=" * 80
    )

    print(
        f"Parameter file : "
        f"{PARAMETER_CSV}"
    )

    print(
        f"Results folder : "
        f"{RESULTS_DIR}"
    )

    print(
        f"Total runs     : "
        f"{total_runs}"
    )

    print(
        f"Output         : "
        f"{QC_CSV}"
    )

    print(
        "=" * 80
    )


    # ==================================================================
    # PROCESS ALL RUNS
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
            f"\nRUN "
            f"{run_id:03d}/{total_runs}"
        )

        print(
            f"HDF: {hdf_path}"
        )


        # ==============================================================
        # HDF MISSING
        # ==============================================================

        if not hdf_path.exists():

            print(
                "STATUS: HDF missing"
            )

            missing_runs.append(
                run_id
            )

            continue


        # ==============================================================
        # EXTRACT
        # ==============================================================

        try:

            values = extract_one(
                hdf_path
            )


            # ----------------------------------------------------------
            # Start with ensemble parameters
            # ----------------------------------------------------------

            row = (
                parameter_row
                .to_dict()
            )


            # ----------------------------------------------------------
            # Add QC statistics
            # ----------------------------------------------------------

            row.update(
                values
            )


            # ----------------------------------------------------------
            # Add HDF metadata
            # ----------------------------------------------------------

            row[
                "HDF_Size_MB"
            ] = (
                hdf_path.stat().st_size
                / (1024 ** 2)
            )


            row[
                "Status"
            ] = "VALID"


            records.append(
                row
            )


            print(
                "STATUS: OK"
            )

            print(
                f"Max depth : "
                f"{values['Max_Depth_m']:.4f} m"
            )

            print(
                f"Mean depth: "
                f"{values['Mean_Depth_m']:.4f} m"
            )


        # ==============================================================
        # EXTRACTION FAILURE
        # ==============================================================

        except Exception as exc:

            print(
                "STATUS: FAILED"
            )

            print(
                f"Error: {exc}"
            )


            failed_runs.append(
                {
                    "Run": run_id,
                    "Error": str(exc),
                }
            )


    # ==================================================================
    # CREATE OUTPUT TABLE
    # ==================================================================

    out = pd.DataFrame(
        records
    )


    # ==================================================================
    # SAVE QC TABLE
    # ==================================================================

    QC_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    out.to_csv(
        QC_CSV,
        index=False,
    )


    # ==================================================================
    # SUMMARY
    # ==================================================================

    successful = len(
        records
    )

    missing = len(
        missing_runs
    )

    failed = len(
        failed_runs
    )


    print(
        "\n" + "=" * 80
    )

    print(
        "HDF QC FINISHED"
    )

    print(
        "=" * 80
    )

    print(
        f"Total parameter sets : "
        f"{total_runs}"
    )

    print(
        f"Successfully processed: "
        f"{successful}"
    )

    print(
        f"Missing HDFs         : "
        f"{missing}"
    )

    print(
        f"Failed extraction    : "
        f"{failed}"
    )


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


    if failed_runs:

        print(
            "\nFailed extraction runs:"
        )

        for item in failed_runs:

            print(
                f"Run {item['Run']:03d}: "
                f"{item['Error']}"
            )


    print(
        "\nSaved:"
    )

    print(
        QC_CSV
    )

    print(
        "=" * 80
    )


# ======================================================================
# ENTRY POINT
# ======================================================================

if __name__ == "__main__":

    main()

