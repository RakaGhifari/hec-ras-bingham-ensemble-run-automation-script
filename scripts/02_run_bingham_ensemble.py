"""
======================================================================
HEC-RAS 2D BINGHAM ENSEMBLE SIMULATION AUTOMATION
By Raka Ghifari (2026)
======================================================================

Run a Bingham non-Newtonian ensemble in HEC-RAS 6.6.

The script reads the complete ensemble definition from a parameter CSV
file and automatically runs every parameter set found in that file.

The number of simulations is NOT hard-coded. Therefore, the same
runner can be used for:

    60 runs
    100 runs
    500 runs
    or any other number of valid parameter sets.

Workflow
--------
For each ensemble member:

    1. Check whether a valid archived HDF already exists.
    2. Skip the run if the HDF is already available.
    3. Read the active HEC-RAS U14 file.
    4. Back up the U14 file.
    5. Modify:
           - Constant Volumetric Concentration (Cv)
           - Yield Stress
           - Dynamic Viscosity
    6. Verify the modified parameters.
    7. Reload the HEC-RAS project.
    8. Verify that the correct plan is active.
    9. Verify the parameters again after reload.
   10. Run HEC-RAS in non-blocking mode.
   11. Monitor the computation using Compute_Complete().
   12. Abort the computation if the maximum runtime is exceeded.
   13. Validate the resulting HDF.
   14. Archive the HDF using the ensemble run number.
   15. Record the result in the results CSV.
   16. If the run fails, record the failure and continue.

Requirements
------------
- Windows
- HEC-RAS 6.6
- Python
- pandas
- pywin32

Input
-----
PARAMETER_CSV

Required columns:

    Run
    Cv
    Yield_Stress_Pa
    Viscosity_Pa_s

Output
------
Archived HDF files:

    results/run_001.p31.hdf
    results/run_002.p31.hdf
    ...

Result log:

    RESULTS_CSV

Failure log:

    FAILURES_CSV

Notes
-----
This script is designed for reproducible ensemble simulations.
The parameter space itself should be generated separately using
01_generate_parameter_sets.py.

The runner does not determine the number of samples. It simply runs
all valid parameter combinations contained in PARAMETER_CSV.
======================================================================
"""

from pathlib import Path
import sys
import os
import shutil
import time
import traceback

import pandas as pd
import win32com.client
import pythoncom


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
        PROJECT_FILE,
        PLAN_FILE,
        RESULTS_DIR,
        PARAMETER_CSV,
        RESULTS_CSV,
        FAILURES_CSV,
        MAX_RUNTIME_SECONDS,
        POLL_INTERVAL_SECONDS,
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
#
# These settings can be placed in config.py if desired.
#
# If they are not present, the default values below are used.
#
# This makes the script backward-compatible with a simpler config.py.
# ======================================================================

try:
    from config.config import HECRAS_PROG_ID
except ImportError:
    HECRAS_PROG_ID = "RAS66.HECRASController"


try:
    from config.config import MINIMUM_HDF_SIZE_MB
except ImportError:
    MINIMUM_HDF_SIZE_MB = 10.0


try:
    from config.config import CREATE_U14_BACKUP
except ImportError:
    CREATE_U14_BACKUP = True


try:
    from config.config import SHOW_HECRAS
except ImportError:
    SHOW_HECRAS = True


try:
    from config.config import SHOW_COMPUTATION_WINDOW
except ImportError:
    SHOW_COMPUTATION_WINDOW = True


try:
    from config.config import VERIFY_PLAN_AFTER_RELOAD
except ImportError:
    VERIFY_PLAN_AFTER_RELOAD = True


try:
    from config.config import VERIFY_PARAMETERS_AFTER_RELOAD
except ImportError:
    VERIFY_PARAMETERS_AFTER_RELOAD = True


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
# HEC-RAS U14 PARAMETER MAPPING
# ======================================================================
#
# These strings correspond to the entries written in the HEC-RAS
# non-Newtonian U14 file.
#
# IMPORTANT:
# "Yeild" is intentionally preserved because this is the spelling
# used by the HEC-RAS U14 parameter line in the original workflow.
# ======================================================================

PARAMETER_KEYS = {

    "Cv":
        "Non-Newtonian Constant Vol Conc=",

    "Yield_Stress_Pa":
        "User Yeild=",

    "Viscosity_Pa_s":
        "User Viscosity=",
}


# ======================================================================
# FILE VALIDATION
# ======================================================================

def valid_hdf(
    path: Path,
    minimum_mb: float = MINIMUM_HDF_SIZE_MB,
) -> bool:
    """
    Check whether an HDF file exists and exceeds the minimum size.

    This is intentionally a lightweight validation. It does not open
    the HDF and inspect internal datasets.
    """

    if not path.exists():
        return False

    try:
        size_mb = path.stat().st_size / (1024 ** 2)
    except OSError:
        return False

    return size_mb >= minimum_mb


# ======================================================================
# READ RHEOLOGY PARAMETERS FROM U14
# ======================================================================

def read_rheology(u_file: Path) -> dict:
    """
    Read the Bingham rheological parameters from a HEC-RAS U14 file.
    """

    if not u_file.exists():
        raise FileNotFoundError(
            f"U14 file not found: {u_file}"
        )

    values = {}

    with open(
        u_file,
        "r",
        errors="ignore",
    ) as f:

        for line in f:

            if line.startswith(
                PARAMETER_KEYS["Cv"]
            ):

                values["Cv"] = float(
                    line.split("=", 1)[1].strip()
                )

            elif line.startswith(
                PARAMETER_KEYS["Yield_Stress_Pa"]
            ):

                values["Yield_Stress_Pa"] = float(
                    line.split("=", 1)[1].strip()
                )

            elif line.startswith(
                PARAMETER_KEYS["Viscosity_Pa_s"]
            ):

                values["Viscosity_Pa_s"] = float(
                    line.split("=", 1)[1].strip()
                )

    return values


# ======================================================================
# WRITE RHEOLOGY PARAMETERS TO U14
# ======================================================================

def write_rheology(
    u_file: Path,
    cv: float,
    tau: float,
    mu: float,
) -> None:
    """
    Replace the Bingham rheological parameters in the U14 file.
    """

    if not u_file.exists():
        raise FileNotFoundError(
            f"U14 file not found: {u_file}"
        )

    with open(
        u_file,
        "r",
        errors="ignore",
    ) as f:

        lines = f.readlines()


    new_lines = []

    found = {
        "Cv": False,
        "Yield_Stress_Pa": False,
        "Viscosity_Pa_s": False,
    }


    for line in lines:

        # ----------------------------------------------------------
        # Cv
        # ----------------------------------------------------------

        if line.startswith(
            PARAMETER_KEYS["Cv"]
        ):

            line = (
                f"{PARAMETER_KEYS['Cv']}"
                f"{cv:.6f}\n"
            )

            found["Cv"] = True


        # ----------------------------------------------------------
        # Yield stress
        # ----------------------------------------------------------

        elif line.startswith(
            PARAMETER_KEYS["Yield_Stress_Pa"]
        ):

            line = (
                f"{PARAMETER_KEYS['Yield_Stress_Pa']}"
                f"   {tau:.6f}\n"
            )

            found["Yield_Stress_Pa"] = True


        # ----------------------------------------------------------
        # Dynamic viscosity
        # ----------------------------------------------------------

        elif line.startswith(
            PARAMETER_KEYS["Viscosity_Pa_s"]
        ):

            line = (
                f"{PARAMETER_KEYS['Viscosity_Pa_s']}"
                f"{mu:.6f}\n"
            )

            found["Viscosity_Pa_s"] = True


        new_lines.append(line)


    # --------------------------------------------------------------
    # Check whether all required parameters were found
    # --------------------------------------------------------------

    missing = [
        key
        for key, value in found.items()
        if not value
    ]


    if missing:

        raise RuntimeError(
            "Required rheology lines were not found "
            f"in U14: {missing}"
        )


    # --------------------------------------------------------------
    # Write modified U14
    # --------------------------------------------------------------

    with open(
        u_file,
        "w",
        errors="ignore",
    ) as f:

        f.writelines(new_lines)


# ======================================================================
# PARAMETER VERIFICATION
# ======================================================================

def verify_parameters(
    actual: dict,
    expected: dict,
    tolerance: float = 1e-5,
) -> None:
    """
    Verify that the U14 parameters match the requested values.
    """

    for key, expected_value in expected.items():

        if key not in actual:

            raise RuntimeError(
                f"Parameter '{key}' could not be read from U14."
            )


        actual_value = actual[key]


        if abs(
            actual_value - expected_value
        ) > tolerance:

            raise RuntimeError(
                f"{key} mismatch: "
                f"expected {expected_value}, "
                f"found {actual_value}"
            )


# ======================================================================
# COMPUTATION WATCHDOG
# ======================================================================

def wait_for_compute(
    hec,
    timeout_seconds: int,
    poll_seconds: int,
) -> tuple[str, float]:
    """
    Monitor a non-blocking HEC-RAS computation.

    Returns
    -------
    ("COMPLETED", elapsed)
        Normal completion.

    ("TIMEOUT", elapsed)
        Computation exceeded the maximum runtime and was cancelled.

    ("MANUAL_ABORT", elapsed)
        Reserved status for future/custom abort conditions.

    Notes
    -----
    HEC-RAS 6.6 is monitored through Compute_Complete().
    The controller is polled at a fixed interval.
    """

    start = time.time()


    while True:

        # ----------------------------------------------------------
        # Allow Windows/COM messages to be processed.
        # ----------------------------------------------------------

        pythoncom.PumpWaitingMessages()


        elapsed = time.time() - start


        # ----------------------------------------------------------
        # Timeout
        # ----------------------------------------------------------

        if elapsed >= timeout_seconds:

            print(
                "\n"
                f"TIMEOUT reached after "
                f"{elapsed:.1f} seconds."
            )

            print(
                "Requesting HEC-RAS computation cancellation..."
            )

            try:

                hec.Compute_Cancel()

            except Exception as cancel_error:

                print(
                    "WARNING: Compute_Cancel() raised an error:"
                )

                print(cancel_error)


            return "TIMEOUT", elapsed


        # ----------------------------------------------------------
        # Check computation status
        # ----------------------------------------------------------

        try:

            complete = hec.Compute_Complete()

        except Exception:

            # COM can occasionally fail while HEC-RAS is busy.
            # Continue polling instead of immediately terminating.
            complete = False


        # ----------------------------------------------------------
        # Completed
        # ----------------------------------------------------------

        if bool(complete):

            return "COMPLETED", elapsed


        # ----------------------------------------------------------
        # Wait before polling again
        # ----------------------------------------------------------

        time.sleep(poll_seconds)


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


    df = pd.read_csv(parameter_csv)


    # --------------------------------------------------------------
    # Check required columns
    # --------------------------------------------------------------

    missing = [
        column
        for column in REQUIRED_PARAMETER_COLUMNS
        if column not in df.columns
    ]


    if missing:

        raise ValueError(
            "Missing required parameter columns:\n"
            f"{missing}"
        )


    df = df[
        REQUIRED_PARAMETER_COLUMNS
    ].copy()


    # --------------------------------------------------------------
    # Convert data types
    # --------------------------------------------------------------

    try:

        df["Run"] = df["Run"].astype(int)

        df["Cv"] = df["Cv"].astype(float)

        df["Yield_Stress_Pa"] = (
            df["Yield_Stress_Pa"]
            .astype(float)
        )

        df["Viscosity_Pa_s"] = (
            df["Viscosity_Pa_s"]
            .astype(float)
        )

    except Exception as exc:

        raise ValueError(
            "Parameter CSV contains invalid "
            "numeric values."
        ) from exc


    # --------------------------------------------------------------
    # Check duplicate run IDs
    # --------------------------------------------------------------

    duplicated_runs = (
        df.loc[
            df["Run"].duplicated(),
            "Run"
        ]
        .tolist()
    )


    if duplicated_runs:

        raise ValueError(
            "Duplicate Run IDs found:\n"
            f"{duplicated_runs}"
        )


    # --------------------------------------------------------------
    # Sort by Run
    # --------------------------------------------------------------

    df = (
        df
        .sort_values("Run")
        .reset_index(drop=True)
    )


    # --------------------------------------------------------------
    # Validate sequential numbering
    #
    # This intentionally does NOT use TOTAL_RUNS.
    # The CSV itself defines the ensemble size.
    # --------------------------------------------------------------

    n_runs = len(df)

    expected_runs = set(
        range(1, n_runs + 1)
    )

    actual_runs = set(
        df["Run"].astype(int)
    )


    if actual_runs != expected_runs:

        raise ValueError(
            "Run numbers must be sequential "
            f"from 1 to {n_runs}.\n"
            f"Found: {sorted(actual_runs)}"
        )


    # --------------------------------------------------------------
    # Check for NaN values
    # --------------------------------------------------------------

    if df.isnull().any().any():

        bad_columns = (
            df.columns[
                df.isnull().any()
            ]
            .tolist()
        )

        raise ValueError(
            "Missing values detected in parameter CSV "
            f"columns: {bad_columns}"
        )


    # --------------------------------------------------------------
    # Check physically meaningful values
    # --------------------------------------------------------------

    if (df["Cv"] < 0).any():

        raise ValueError(
            "Cv contains negative values."
        )


    if (df["Yield_Stress_Pa"] < 0).any():

        raise ValueError(
            "Yield stress contains negative values."
        )


    if (df["Viscosity_Pa_s"] <= 0).any():

        raise ValueError(
            "Dynamic viscosity must be greater than zero."
        )


    return df


# ======================================================================
# LOAD EXISTING RESULT LOG
# ======================================================================

def load_results(
    path: Path,
) -> pd.DataFrame:

    columns = [
        "Run",
        "Cv",
        "Yield_Stress_Pa",
        "Viscosity_Pa_s",
        "Status",
        "Runtime_min",
        "Compute_Status",
        "HDF",
        "HDF_Size_MB",
    ]


    if not path.exists():

        return pd.DataFrame(
            columns=columns
        )


    try:

        results = pd.read_csv(path)

    except Exception as exc:

        raise RuntimeError(
            f"Could not read results CSV:\n{path}"
        ) from exc


    return results


# ======================================================================
# LOAD EXISTING FAILURE LOG
# ======================================================================

def load_failures(
    path: Path,
) -> pd.DataFrame:

    columns = [
        "Run",
        "Cv",
        "Yield_Stress_Pa",
        "Viscosity_Pa_s",
        "Status",
        "Error",
        "Runtime_min",
    ]


    if not path.exists():

        return pd.DataFrame(
            columns=columns
        )


    try:

        failures = pd.read_csv(path)

    except Exception as exc:

        raise RuntimeError(
            f"Could not read failure CSV:\n{path}"
        ) from exc


    return failures


# ======================================================================
# SAVE RESULT RECORD
# ======================================================================

def save_result(
    results: pd.DataFrame,
    path: Path,
    record: dict,
) -> pd.DataFrame:
    """
    Add or replace a result for a specific Run ID.
    """

    run_id = int(record["Run"])


    results = results[
        results["Run"] != run_id
    ].copy()


    results = pd.concat(
        [
            results,
            pd.DataFrame([record]),
        ],
        ignore_index=True,
    )


    results = (
        results
        .sort_values("Run")
        .reset_index(drop=True)
    )


    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    results.to_csv(
        path,
        index=False,
    )


    return results


# ======================================================================
# SAVE FAILURE RECORD
# ======================================================================

def save_failure(
    failures: pd.DataFrame,
    path: Path,
    record: dict,
) -> pd.DataFrame:
    """
    Add or replace a failure record for a specific Run ID.
    """

    run_id = int(record["Run"])


    failures = failures[
        failures["Run"] != run_id
    ].copy()


    failures = pd.concat(
        [
            failures,
            pd.DataFrame([record]),
        ],
        ignore_index=True,
    )


    failures = (
        failures
        .sort_values("Run")
        .reset_index(drop=True)
    )


    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    failures.to_csv(
        path,
        index=False,
    )


    return failures


# ======================================================================
# MAIN
# ======================================================================

def main() -> None:

    # ==================================================================
    # INITIAL VALIDATION
    # ==================================================================

    if not PROJECT_FILE.exists():

        raise FileNotFoundError(
            f"HEC-RAS project file not found:\n"
            f"{PROJECT_FILE}"
        )


    if not PLAN_FILE.exists():

        raise FileNotFoundError(
            f"HEC-RAS plan file not found:\n"
            f"{PLAN_FILE}"
        )


    if not PARAMETER_CSV.exists():

        raise FileNotFoundError(
            f"Parameter CSV not found:\n"
            f"{PARAMETER_CSV}"
        )


    # ==================================================================
    # CREATE OUTPUT DIRECTORIES
    # ==================================================================

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    RESULTS_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    FAILURES_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    # ==================================================================
    # LOAD PARAMETER TABLE
    # ==================================================================

    df = load_parameter_table(
        PARAMETER_CSV
    )


    total_runs = len(df)


    # ==================================================================
    # LOAD PREVIOUS LOGS
    # ==================================================================

    results = load_results(
        RESULTS_CSV
    )


    failures = load_failures(
        FAILURES_CSV
    )


    # ==================================================================
    # PRINT CONFIGURATION
    # ==================================================================

    print("\n" + "=" * 80)
    print(
        "HEC-RAS 6.6 — BINGHAM ENSEMBLE RUNNER"
    )
    print("=" * 80)

    print(
        f"Project file        : {PROJECT_FILE}"
    )

    print(
        f"Plan file           : {PLAN_FILE}"
    )

    print(
        f"Parameter CSV       : {PARAMETER_CSV}"
    )

    print(
        f"Total ensemble runs : {total_runs}"
    )

    print(
        f"HEC-RAS ProgID      : {HECRAS_PROG_ID}"
    )

    print(
        f"Timeout             : "
        f"{MAX_RUNTIME_SECONDS} s"
    )

    print(
        f"Polling interval    : "
        f"{POLL_INTERVAL_SECONDS} s"
    )

    print(
        f"Minimum HDF size    : "
        f"{MINIMUM_HDF_SIZE_MB} MB"
    )

    print(
        f"U14 backup          : "
        f"{CREATE_U14_BACKUP}"
    )

    print("=" * 80)


    # ==================================================================
    # INITIALIZE COM
    # ==================================================================

    pythoncom.CoInitialize()

    hec = None


    try:

        # ==============================================================
        # CONNECT TO HEC-RAS
        # ==============================================================

        print(
            "\nStarting HEC-RAS controller..."
        )


        hec = win32com.client.Dispatch(
            HECRAS_PROG_ID
        )


        # ==============================================================
        # OPTIONAL HEC-RAS DISPLAY
        # ==============================================================

        if SHOW_HECRAS:

            try:

                hec.ShowRas()

            except Exception as exc:

                print(
                    "WARNING: Could not show HEC-RAS window:"
                )

                print(exc)


        if SHOW_COMPUTATION_WINDOW:

            try:

                hec.Compute_ShowComputationWindow()

            except Exception as exc:

                print(
                    "WARNING: Could not show "
                    "computation window:"
                )

                print(exc)


        # ==============================================================
        # OPEN PROJECT
        # ==============================================================

        print(
            "\nOpening HEC-RAS project..."
        )


        hec.Project_Open(
            str(PROJECT_FILE)
        )


        # ==============================================================
        # VERIFY ACTIVE PLAN
        # ==============================================================

        current_plan = Path(
            hec.CurrentPlanFile()
        )


        if os.path.normcase(
            str(current_plan)
        ) != os.path.normcase(
            str(PLAN_FILE)
        ):

            raise RuntimeError(
                "\n"
                "The active HEC-RAS plan does not "
                "match the configured plan.\n\n"
                f"Current plan:\n{current_plan}\n\n"
                f"Expected plan:\n{PLAN_FILE}"
            )


        # ==============================================================
        # DETECT EXISTING ARCHIVED HDF FILES
        # ==============================================================

        existing_runs = set()


        for run_id in df["Run"].astype(int):

            target_hdf = (
                RESULTS_DIR
                / f"run_{run_id:03d}.p31.hdf"
            )


            if valid_hdf(target_hdf):

                existing_runs.add(
                    run_id
                )


        print(
            f"\nExisting valid HDFs: "
            f"{len(existing_runs)} / {total_runs}"
        )


        # ==============================================================
        # ENSEMBLE LOOP
        # ==============================================================

        for _, row in df.iterrows():

            run_id = int(
                row["Run"]
            )

            cv = float(
                row["Cv"]
            )

            tau = float(
                row["Yield_Stress_Pa"]
            )

            mu = float(
                row["Viscosity_Pa_s"]
            )


            target_hdf = (
                RESULTS_DIR
                / f"run_{run_id:03d}.p31.hdf"
            )


            # ==========================================================
            # RESUME
            # ==========================================================

            if run_id in existing_runs:

                print(
                    f"\nRUN {run_id:03d}/{total_runs}: "
                    "SKIP — valid HDF already exists."
                )

                continue


            # ==========================================================
            # START TIMER
            # ==========================================================

            started = time.time()


            expected_params = {

                "Cv":
                    cv,

                "Yield_Stress_Pa":
                    tau,

                "Viscosity_Pa_s":
                    mu,
            }


            # ==========================================================
            # RUN HEADER
            # ==========================================================

            print(
                "\n" + "=" * 80
            )

            print(
                f"RUN {run_id:03d}/{total_runs}"
            )

            print(
                f"Cv = {cv:.6f} % | "
                f"Yield stress = {tau:.6f} Pa | "
                f"Viscosity = {mu:.6f} Pa.s"
            )

            print(
                "=" * 80
            )


            try:

                # ======================================================
                # GET ACTIVE U14
                # ======================================================

                u_file = Path(
                    hec.CurrentUnSteadyFile()
                )


                if not u_file.exists():

                    raise FileNotFoundError(
                        f"Active U14 file not found:\n"
                        f"{u_file}"
                    )


                print(
                    f"Active U14:\n{u_file}"
                )


                # ======================================================
                # BACKUP U14
                # ======================================================

                if CREATE_U14_BACKUP:

                    backup = u_file.with_name(
                        u_file.name
                        + f".run_{run_id:03d}.backup"
                    )


                    shutil.copy2(
                        u_file,
                        backup,
                    )


                    print(
                        f"U14 backup created:\n"
                        f"{backup}"
                    )


                # ======================================================
                # MODIFY U14
                # ======================================================

                print(
                    "Updating Bingham parameters..."
                )


                write_rheology(
                    u_file,
                    cv,
                    tau,
                    mu,
                )


                # ======================================================
                # VERIFY BEFORE RELOAD
                # ======================================================

                actual_before_reload = (
                    read_rheology(u_file)
                )


                verify_parameters(
                    actual_before_reload,
                    expected_params,
                )


                print(
                    "Parameters verified before reload."
                )


                # ======================================================
                # RELOAD PROJECT
                # ======================================================

                print(
                    "Reloading HEC-RAS project..."
                )


                hec.Project_Close()

                time.sleep(2)


                hec.Project_Open(
                    str(PROJECT_FILE)
                )

                time.sleep(2)


                # ======================================================
                # VERIFY PLAN AFTER RELOAD
                # ======================================================

                if VERIFY_PLAN_AFTER_RELOAD:

                    current_plan = Path(
                        hec.CurrentPlanFile()
                    )


                    if os.path.normcase(
                        str(current_plan)
                    ) != os.path.normcase(
                        str(PLAN_FILE)
                    ):

                        raise RuntimeError(
                            "Active plan changed "
                            "after project reload.\n"
                            f"Current: {current_plan}\n"
                            f"Expected: {PLAN_FILE}"
                        )


                # ======================================================
                # VERIFY PARAMETERS AFTER RELOAD
                # ======================================================

                if VERIFY_PARAMETERS_AFTER_RELOAD:

                    current_u = Path(
                        hec.CurrentUnSteadyFile()
                    )


                    actual_after_reload = (
                        read_rheology(current_u)
                    )


                    verify_parameters(
                        actual_after_reload,
                        expected_params,
                    )


                    print(
                        "Parameters verified "
                        "after reload."
                    )


                # ======================================================
                # RUN HEC-RAS
                # ======================================================

                print(
                    "\nStarting HEC-RAS computation..."
                )


                compute_start = time.time()


                # ------------------------------------------------------
                # Non-blocking computation
                # ------------------------------------------------------

                hec.Compute_CurrentPlan(
                    0,
                    None,
                    False,
                )


                # ======================================================
                # WATCHDOG
                # ======================================================

                status, compute_elapsed = (
                    wait_for_compute(
                        hec,
                        MAX_RUNTIME_SECONDS,
                        POLL_INTERVAL_SECONDS,
                    )
                )


                # ======================================================
                # TIMEOUT
                # ======================================================

                if status == "TIMEOUT":

                    raise TimeoutError(
                        "HEC-RAS computation exceeded "
                        f"{MAX_RUNTIME_SECONDS} seconds "
                        "and was cancelled."
                    )


                # ======================================================
                # OTHER NON-COMPLETED STATUS
                # ======================================================

                if status != "COMPLETED":

                    raise RuntimeError(
                        "HEC-RAS computation stopped "
                        f"with status: {status}"
                    )


                # ======================================================
                # FIND HDF
                # ======================================================

                print(
                    "\nHEC-RAS computation completed."
                )


                base_hdf = Path(
                    hec.CurrentPlanFile()
                    + ".hdf"
                )


                # ------------------------------------------------------
                # Fallback
                # ------------------------------------------------------

                if not base_hdf.exists():

                    base_hdf = (
                        PROJECT_FILE.parent
                        / (
                            PLAN_FILE.stem
                            + ".hdf"
                        )
                    )


                print(
                    f"Computed HDF:\n{base_hdf}"
                )


                # ======================================================
                # VALIDATE HDF
                # ======================================================

                if not valid_hdf(
                    base_hdf
                ):

                    raise FileNotFoundError(
                        "\n"
                        "Valid computed HDF not found.\n"
                        f"Expected: {base_hdf}\n"
                        f"Minimum size: "
                        f"{MINIMUM_HDF_SIZE_MB} MB"
                    )


                # ======================================================
                # ARCHIVE HDF
                # ======================================================

                print(
                    f"Archiving HDF:\n"
                    f"{target_hdf}"
                )


                shutil.copy2(
                    base_hdf,
                    target_hdf,
                )


                # ======================================================
                # VERIFY ARCHIVED HDF
                # ======================================================

                if not valid_hdf(
                    target_hdf
                ):

                    raise RuntimeError(
                        "Archived HDF failed validation."
                    )


                # ======================================================
                # RUNTIME
                # ======================================================

                runtime_min = (
                    time.time()
                    - started
                ) / 60.0


                compute_min = (
                    compute_elapsed
                    / 60.0
                )


                size_mb = (
                    target_hdf.stat().st_size
                    / (1024 ** 2)
                )


                # ======================================================
                # SAVE SUCCESS RESULT
                # ======================================================

                result_record = {

                    "Run":
                        run_id,

                    "Cv":
                        cv,

                    "Yield_Stress_Pa":
                        tau,

                    "Viscosity_Pa_s":
                        mu,

                    "Status":
                        "SUCCESS",

                    "Runtime_min":
                        runtime_min,

                    "Compute_Status":
                        status,

                    "HDF":
                        str(target_hdf),

                    "HDF_Size_MB":
                        size_mb,
                }


                results = save_result(
                    results,
                    RESULTS_CSV,
                    result_record,
                )


                # ======================================================
                # SUCCESS MESSAGE
                # ======================================================

                print(
                    "\nSUCCESS"
                )

                print(
                    f"Compute time : "
                    f"{compute_min:.2f} min"
                )

                print(
                    f"Total time   : "
                    f"{runtime_min:.2f} min"
                )

                print(
                    f"HDF size     : "
                    f"{size_mb:.2f} MB"
                )


            # ==========================================================
            # RUN FAILURE
            # ==========================================================

            except Exception as exc:

                runtime_min = (
                    time.time()
                    - started
                ) / 60.0


                print(
                    "\nFAILED"
                )

                print(
                    f"Run {run_id:03d}: {exc}"
                )


                traceback.print_exc()


                # ======================================================
                # SAVE FAILURE
                # ======================================================

                failure_record = {

                    "Run":
                        run_id,

                    "Cv":
                        cv,

                    "Yield_Stress_Pa":
                        tau,

                    "Viscosity_Pa_s":
                        mu,

                    "Status":
                        "FAILED",

                    "Error":
                        str(exc),

                    "Runtime_min":
                        runtime_min,
                }


                failures = save_failure(
                    failures,
                    FAILURES_CSV,
                    failure_record,
                )


                # ======================================================
                # CONTINUE TO NEXT RUN
                # ======================================================

                print(
                    "\nContinuing to the next "
                    "ensemble member..."
                )


                continue


    # ==================================================================
    # CLEANUP
    # ==================================================================

    finally:

        try:

            if hec is not None:

                hec.Project_Close()

        except Exception:

            pass


        pythoncom.CoUninitialize()


    # ==================================================================
    # FINAL SUMMARY
    # ==================================================================

    print(
        "\n" + "=" * 80
    )

    print(
        "ENSEMBLE RUNNER FINISHED"
    )

    print(
        "=" * 80
    )

    print(
        f"Total parameter sets : {total_runs}"
    )


    # ------------------------------------------------------------------
    # Count archived HDFs
    # ------------------------------------------------------------------

    successful_hdfs = 0


    for run_id in df["Run"].astype(int):

        target_hdf = (
            RESULTS_DIR
            / f"run_{run_id:03d}.p31.hdf"
        )


        if valid_hdf(target_hdf):

            successful_hdfs += 1


    print(
        f"Valid HDF files     : "
        f"{successful_hdfs}"
    )


    print(
        f"Results log         : "
        f"{RESULTS_CSV}"
    )

    print(
        f"Failure log         : "
        f"{FAILURES_CSV}"
    )

    print(
        "=" * 80
    )


# ======================================================================
# ENTRY POINT
# ======================================================================

if __name__ == "__main__":

    main()