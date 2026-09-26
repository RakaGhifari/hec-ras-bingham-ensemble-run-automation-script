"""
======================================================================
HEC-RAS 2D BINGHAM ENSEMBLE PARAMETER SAMPLING
by Raka Ghifari (2026)
======================================================================

Generate an ensemble of Bingham non-Newtonian flow parameters using
Latin Hypercube Sampling (LHS).

The user can define:
    - Total number of parameter sets
    - Whether to include existing parameter sets
    - LHS random seed
    - Parameter ranges through config.py

The final parameter table contains:
    Run
    Cv
    Yield_Stress_Pa
    Viscosity_Pa_s

Parameter ranges:
    Cv: 30–50 %
    Yield stress: 50–500 Pa
    Dynamic viscosity: 0.1–10 Pa.s
======================================================================
"""

from pathlib import Path
import sys

import numpy as np
import pandas as pd


# ============================================================
# PROJECT PATH
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ============================================================
# CONFIG
# ============================================================

try:
    from config.config import (
        ENSEMBLE_DIR,
        CV_RANGE,
        YIELD_STRESS_RANGE,
        VISCOSITY_RANGE,
    )
except ImportError as exc:
    raise SystemExit(
        "Create config/config.py from config/config_template.py first."
    ) from exc


# ============================================================
# USER SETTINGS
# ============================================================

# Total number of parameter sets to generate
TOTAL_SAMPLES = 60

# Use existing parameter sets?
USE_EXISTING_SAMPLES = True

# Existing parameter-set file
EXISTING_CSV = ENSEMBLE_DIR / "ensemble_parameter_sets_existing.csv"

# Random seed for reproducibility
LHS_SEED = 20260912

# Output file
OUT_CSV = ENSEMBLE_DIR / f"ensemble_parameter_sets_{TOTAL_SAMPLES}.csv"


# ============================================================
# REQUIRED COLUMNS
# ============================================================

REQUIRED_COLUMNS = [
    "Run",
    "Cv",
    "Yield_Stress_Pa",
    "Viscosity_Pa_s",
]


# ============================================================
# LATIN HYPERCUBE SAMPLING
# ============================================================

def lhs(
    n_samples: int,
    dimensions: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Generate Latin Hypercube samples in the interval (0, 1).
    """

    result = np.zeros((n_samples, dimensions))

    for j in range(dimensions):

        points = (
            np.arange(n_samples) + rng.random(n_samples)
        ) / n_samples

        rng.shuffle(points)

        result[:, j] = points

    return result


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    # --------------------------------------------------------
    # Validate total sample size
    # --------------------------------------------------------

    if TOTAL_SAMPLES < 1:
        raise ValueError(
            "TOTAL_SAMPLES must be greater than or equal to 1."
        )


    # --------------------------------------------------------
    # Load existing samples if requested
    # --------------------------------------------------------

    if USE_EXISTING_SAMPLES:

        if not EXISTING_CSV.exists():
            raise FileNotFoundError(
                f"Existing parameter file not found:\n"
                f"{EXISTING_CSV}"
            )

        existing = pd.read_csv(EXISTING_CSV)

        missing = [
            col
            for col in REQUIRED_COLUMNS
            if col not in existing.columns
        ]

        if missing:
            raise ValueError(
                f"Missing columns in existing parameter file: "
                f"{missing}"
            )

        existing = existing[REQUIRED_COLUMNS].copy()

        existing["Run"] = existing["Run"].astype(int)

        n_existing = len(existing)

    else:

        existing = pd.DataFrame(
            columns=REQUIRED_COLUMNS
        )

        n_existing = 0


    # --------------------------------------------------------
    # Determine number of LHS samples
    # --------------------------------------------------------

    n_lhs = TOTAL_SAMPLES - n_existing

    if n_lhs < 0:

        raise ValueError(
            f"TOTAL_SAMPLES = {TOTAL_SAMPLES}, but "
            f"{n_existing} existing parameter sets were found.\n\n"
            "TOTAL_SAMPLES must be greater than or equal to "
            "the number of existing parameter sets."
        )


    print("=" * 70)
    print("BINGHAM ENSEMBLE PARAMETER SAMPLING")
    print("=" * 70)

    print(f"Total samples       : {TOTAL_SAMPLES}")
    print(f"Existing samples    : {n_existing}")
    print(f"New LHS samples     : {n_lhs}")
    print(f"LHS seed            : {LHS_SEED}")
    print(f"Cv range            : {CV_RANGE}")
    print(f"Yield stress range  : {YIELD_STRESS_RANGE}")
    print(f"Viscosity range     : {VISCOSITY_RANGE}")
    print("=" * 70)


    # --------------------------------------------------------
    # Generate LHS samples
    # --------------------------------------------------------

    if n_lhs > 0:

        rng = np.random.default_rng(LHS_SEED)

        samples = lhs(
            n_samples=n_lhs,
            dimensions=3,
            rng=rng,
        )

        # Cv
        cv = (
            CV_RANGE[0]
            + samples[:, 0]
            * (CV_RANGE[1] - CV_RANGE[0])
        )

        # Yield stress
        tau = (
            YIELD_STRESS_RANGE[0]
            + samples[:, 1]
            * (
                YIELD_STRESS_RANGE[1]
                - YIELD_STRESS_RANGE[0]
            )
        )

        # Dynamic viscosity
        mu = (
            VISCOSITY_RANGE[0]
            + samples[:, 2]
            * (
                VISCOSITY_RANGE[1]
                - VISCOSITY_RANGE[0]
            )
        )

        new = pd.DataFrame(
            {
                "Run": np.arange(
                    n_existing + 1,
                    TOTAL_SAMPLES + 1,
                ),
                "Cv": cv,
                "Yield_Stress_Pa": tau,
                "Viscosity_Pa_s": mu,
            }
        )

    else:

        new = pd.DataFrame(
            columns=REQUIRED_COLUMNS
        )


    # --------------------------------------------------------
    # Combine existing + new samples
    # --------------------------------------------------------

    final = pd.concat(
        [existing, new],
        ignore_index=True,
    )

    final = (
        final
        .sort_values("Run")
        .reset_index(drop=True)
    )


    # --------------------------------------------------------
    # Validate final parameter table
    # --------------------------------------------------------

    if len(final) != TOTAL_SAMPLES:

        raise RuntimeError(
            f"Expected {TOTAL_SAMPLES} parameter sets, "
            f"but generated {len(final)}."
        )


    if final["Run"].nunique() != TOTAL_SAMPLES:

        raise RuntimeError(
            "Run numbers are not unique."
        )


    expected_runs = set(
        range(1, TOTAL_SAMPLES + 1)
    )

    actual_runs = set(
        final["Run"].astype(int)
    )

    if actual_runs != expected_runs:

        raise RuntimeError(
            "Run numbering is not continuous from "
            f"1 to {TOTAL_SAMPLES}."
        )


    # --------------------------------------------------------
    # Round parameter precision
    # --------------------------------------------------------

    for column in REQUIRED_COLUMNS[1:]:

        final[column] = final[column].round(6)


    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    OUT_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    final.to_csv(
        OUT_CSV,
        index=False,
    )


    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print("\nParameter ensemble generated successfully.\n")

    print(f"Output:")
    print(OUT_CSV)

    print("\nParameter sets:")
    print(final.to_string(index=False))


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()