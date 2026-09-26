"""
======================================================================
HEC-RAS BINGHAM ENSEMBLE — MASTER SUMMARY
by Raka Ghifari (2026)
======================================================================

Combine parameter, spatial-validation, and temporal-validation results
into a single master table.

The script integrates:

    1. Ensemble rheological parameters
    2. Spatial validation metrics
    3. Temporal validation metrics

The primary spatial validation threshold is selected using
PRIMARY_DEPTH_THRESHOLD.

The script does not select, rank, or identify a single preferred
scenario. It only consolidates the documented computational results
for subsequent analysis and interpretation.

Required configuration
----------------------
    ENSEMBLE_DIR
    PARAMETER_CSV
    SPATIAL_VALIDATION_CSV
    TRAVEL_TIME_CSV
    PRIMARY_DEPTH_THRESHOLD
    OBSERVED_TRAVEL_TIME_MIN

Optional configuration
----------------------
    SENSITIVITY_PARAMETERS

Default:

    Cv
    Yield_Stress_Pa
    Viscosity_Pa_s

Output
------
    master_bingham_spatial_temporal.csv

Notes
-----
The parameter CSV is treated as the source of truth for the ensemble
parameter definitions.

Spatial validation is filtered to the configured primary depth
threshold.

Temporal validation is merged by Run ID.

The resulting table contains one row per Run for the selected spatial
validation threshold.
======================================================================
"""

from pathlib import Path
import sys

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
        ENSEMBLE_DIR,
        PARAMETER_CSV,
        SPATIAL_VALIDATION_CSV,
        TRAVEL_TIME_CSV,
        PRIMARY_DEPTH_THRESHOLD,
        OBSERVED_TRAVEL_TIME_MIN,
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
    from config.config import SENSITIVITY_PARAMETERS
except ImportError:
    SENSITIVITY_PARAMETERS = [
        "Cv",
        "Yield_Stress_Pa",
        "Viscosity_Pa_s",
    ]


# ======================================================================
# CONSTANTS
# ======================================================================

MASTER_OUTPUT_FILENAME = (
    "master_bingham_spatial_temporal.csv"
)

REQUIRED_PARAMETER_COLUMNS = [
    "Run",
    *SENSITIVITY_PARAMETERS,
]

REQUIRED_SPATIAL_COLUMNS = [
    "Run",
    "Threshold_m",
    "IoU",
    "F1",
    "POD",
    "FAR",
]

REQUIRED_TEMPORAL_COLUMNS = [
    "Run",
    "Arrival_h01_min",
    "TT_Error_min",
    "Abs_TT_Error_min",
    "Relative_Error_pct",
    "Temporal_Score",
]


# ======================================================================
# VALIDATE RUN COLUMN
# ======================================================================

def validate_run_column(
    df: pd.DataFrame,
    source_name: str,
) -> pd.DataFrame:
    """
    Validate and normalize the Run column.
    """

    if "Run" not in df.columns:
        raise ValueError(
            f"{source_name} does not contain a 'Run' column."
        )

    try:
        df["Run"] = (
            df["Run"]
            .astype(int)
        )
    except Exception as exc:
        raise ValueError(
            f"The Run column in {source_name} "
            "contains invalid values."
        ) from exc

    if df["Run"].duplicated().any():

        duplicated = (
            df.loc[
                df["Run"].duplicated(),
                "Run",
            ]
            .tolist()
        )

        raise ValueError(
            f"Duplicate Run IDs found in {source_name}:\n"
            f"{duplicated}"
        )

    return df


# ======================================================================
# VALIDATE REQUIRED COLUMNS
# ======================================================================

def validate_required_columns(
    df: pd.DataFrame,
    required_columns: list[str],
    source_name: str,
) -> None:
    """
    Verify that all required columns are present.
    """

    missing = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            f"Missing required columns in {source_name}:\n"
            f"{missing}"
        )


# ======================================================================
# LOAD PARAMETER TABLE
# ======================================================================

def load_parameter_table(
    path: Path,
) -> pd.DataFrame:
    """
    Load and validate the ensemble parameter table.
    """

    if not path.exists():
        raise FileNotFoundError(
            f"Parameter CSV not found:\n"
            f"{path}"
        )

    params = pd.read_csv(
        path
    )

    validate_required_columns(
        params,
        REQUIRED_PARAMETER_COLUMNS,
        "parameter CSV",
    )

    params = validate_run_column(
        params,
        "parameter CSV",
    )

    params = (
        params
        .sort_values("Run")
        .reset_index(drop=True)
    )

    return params


# ======================================================================
# LOAD SPATIAL VALIDATION
# ======================================================================

def load_spatial_validation(
    path: Path,
) -> pd.DataFrame:
    """
    Load spatial validation results and select the primary threshold.
    """

    if not path.exists():
        raise FileNotFoundError(
            f"Spatial validation CSV not found:\n"
            f"{path}"
        )

    spatial = pd.read_csv(
        path
    )

    validate_required_columns(
        spatial,
        REQUIRED_SPATIAL_COLUMNS,
        "spatial validation CSV",
    )

    # ------------------------------------------------------------------
    # Validate Run IDs
    #
    # Spatial validation normally contains multiple rows per Run
    # because multiple depth thresholds may be evaluated.
    # Therefore duplicate Run IDs are checked only after threshold
    # filtering.
    # ------------------------------------------------------------------

    spatial = spatial[
        np.isclose(
            spatial["Threshold_m"],
            PRIMARY_DEPTH_THRESHOLD,
        )
    ].copy()

    if spatial.empty:
        raise ValueError(
            "No spatial validation records were found for "
            f"the primary depth threshold "
            f"{PRIMARY_DEPTH_THRESHOLD} m."
        )

    spatial = validate_run_column(
        spatial,
        "primary-threshold spatial validation data",
    )

    spatial = (
        spatial
        .sort_values("Run")
        .reset_index(drop=True)
    )

    return spatial


# ======================================================================
# LOAD TEMPORAL VALIDATION
# ======================================================================

def load_temporal_validation(
    path: Path,
) -> pd.DataFrame:
    """
    Load and validate travel-time results.
    """

    if not path.exists():
        raise FileNotFoundError(
            f"Travel-time CSV not found:\n"
            f"{path}"
        )

    temporal = pd.read_csv(
        path
    )

    validate_required_columns(
        temporal,
        REQUIRED_TEMPORAL_COLUMNS,
        "travel-time CSV",
    )

    temporal = validate_run_column(
        temporal,
        "travel-time CSV",
    )

    temporal = (
        temporal
        .sort_values("Run")
        .reset_index(drop=True)
    )

    return temporal


# ======================================================================
# MERGE RESULTS
# ======================================================================

def build_master_table(
    params: pd.DataFrame,
    spatial: pd.DataFrame,
    temporal: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge parameter, spatial, and temporal results by Run ID.
    """

    # ------------------------------------------------------------------
    # Select parameter columns
    # ------------------------------------------------------------------

    parameter_columns = [
        "Run",
        *SENSITIVITY_PARAMETERS,
    ]

    parameter_table = params[
        parameter_columns
    ].copy()

    # ------------------------------------------------------------------
    # Select temporal columns
    # ------------------------------------------------------------------

    temporal_columns = [
        "Run",
        "Arrival_h01_min",
        "TT_Error_min",
        "Abs_TT_Error_min",
        "Relative_Error_pct",
        "Temporal_Score",
    ]

    temporal_table = temporal[
        temporal_columns
    ].copy()

    # ------------------------------------------------------------------
    # Merge parameters and spatial validation
    # ------------------------------------------------------------------

    master = parameter_table.merge(
        spatial,
        on="Run",
        how="left",
        validate="one_to_one",
    )

    # ------------------------------------------------------------------
    # Merge temporal validation
    # ------------------------------------------------------------------

    master = master.merge(
        temporal_table,
        on="Run",
        how="left",
        validate="one_to_one",
    )

    # ------------------------------------------------------------------
    # Sort by Run
    # ------------------------------------------------------------------

    master = (
        master
        .sort_values("Run")
        .reset_index(drop=True)
    )

    # ------------------------------------------------------------------
    # Add analysis metadata
    # ------------------------------------------------------------------

    master[
        "Observed_Travel_Time_min"
    ] = OBSERVED_TRAVEL_TIME_MIN

    master[
        "Primary_Threshold_m"
    ] = PRIMARY_DEPTH_THRESHOLD

    return master


# ======================================================================
# VALIDATE MASTER TABLE
# ======================================================================

def validate_master_table(
    master: pd.DataFrame,
) -> None:
    """
    Perform basic consistency checks on the master table.
    """

    if master.empty:
        raise ValueError(
            "The master table is empty."
        )

    if master["Run"].duplicated().any():

        duplicated = (
            master.loc[
                master["Run"].duplicated(),
                "Run",
            ]
            .tolist()
        )

        raise ValueError(
            "Duplicate Run IDs found in the master table:\n"
            f"{duplicated}"
        )

    # ------------------------------------------------------------------
    # Check primary threshold consistency
    # ------------------------------------------------------------------

    if not np.allclose(
        master["Primary_Threshold_m"],
        PRIMARY_DEPTH_THRESHOLD,
    ):
        raise ValueError(
            "Primary threshold metadata is inconsistent."
        )

    # ------------------------------------------------------------------
    # Check observed travel time consistency
    # ------------------------------------------------------------------

    if not np.allclose(
        master["Observed_Travel_Time_min"],
        OBSERVED_TRAVEL_TIME_MIN,
    ):
        raise ValueError(
            "Observed travel-time metadata is inconsistent."
        )


# ======================================================================
# MAIN
# ======================================================================

def main() -> None:

    # ==================================================================
    # LOAD INPUT TABLES
    # ==================================================================

    params = load_parameter_table(
        PARAMETER_CSV
    )

    spatial = load_spatial_validation(
        SPATIAL_VALIDATION_CSV
    )

    temporal = load_temporal_validation(
        TRAVEL_TIME_CSV
    )

    # ==================================================================
    # BUILD MASTER TABLE
    # ==================================================================

    master = build_master_table(
        params=params,
        spatial=spatial,
        temporal=temporal,
    )

    # ==================================================================
    # VALIDATE MASTER TABLE
    # ==================================================================

    validate_master_table(
        master
    )

    # ==================================================================
    # CREATE OUTPUT DIRECTORY
    # ==================================================================

    ENSEMBLE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        ENSEMBLE_DIR
        / MASTER_OUTPUT_FILENAME
    )

    # ==================================================================
    # SAVE MASTER TABLE
    # ==================================================================

    master.to_csv(
        output_path,
        index=False,
    )

    # ==================================================================
    # PRINT SUMMARY
    # ==================================================================

    total_parameter_runs = len(
        params
    )

    spatial_runs = len(
        spatial
    )

    temporal_runs = len(
        temporal
    )

    master_runs = len(
        master
    )

    print(
        "\n" + "=" * 80
    )

    print(
        "HEC-RAS BINGHAM ENSEMBLE — MASTER SUMMARY"
    )

    print(
        "=" * 80
    )

    print(
        f"Parameter runs       : "
        f"{total_parameter_runs}"
    )

    print(
        f"Spatial runs         : "
        f"{spatial_runs}"
    )

    print(
        f"Temporal runs        : "
        f"{temporal_runs}"
    )

    print(
        f"Master-table runs    : "
        f"{master_runs}"
    )

    print(
        f"Primary threshold    : "
        f"{PRIMARY_DEPTH_THRESHOLD} m"
    )

    print(
        f"Observed travel time : "
        f"{OBSERVED_TRAVEL_TIME_MIN} min"
    )

    print(
        "=" * 80
    )

    # ------------------------------------------------------------------
    # Check for missing spatial results
    # ------------------------------------------------------------------

    missing_spatial = sorted(
        set(
            params["Run"]
        )
        - set(
            spatial["Run"]
        )
    )

    if missing_spatial:

        print(
            "\nRuns missing spatial validation:"
        )

        print(
            ", ".join(
                f"{run:03d}"
                for run in missing_spatial
            )
        )

    # ------------------------------------------------------------------
    # Check for missing temporal results
    # ------------------------------------------------------------------

    missing_temporal = sorted(
        set(
            params["Run"]
        )
        - set(
            temporal["Run"]
        )
    )

    if missing_temporal:

        print(
            "\nRuns missing temporal validation:"
        )

        print(
            ", ".join(
                f"{run:03d}"
                for run in missing_temporal
            )
        )

    # ------------------------------------------------------------------
    # Print master table
    # ------------------------------------------------------------------

    print(
        "\nMaster table:"
    )

    print(
        master.to_string(
            index=False
        )
    )

    # ------------------------------------------------------------------
    # Output path
    # ------------------------------------------------------------------

    print(
        "\nSaved:"
    )

    print(
        output_path
    )

    print(
        "\n" + "=" * 80
    )

    print(
        "MASTER SUMMARY FINISHED"
    )

    print(
        "=" * 80
    )


# ======================================================================
# ENTRY POINT
# ======================================================================

if __name__ == "__main__":
    main()

