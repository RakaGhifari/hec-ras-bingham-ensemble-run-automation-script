
"""
======================================================================
HEC-RAS BINGHAM ENSEMBLE — SPATIAL VALIDATION
by Raka Ghifari (2026)
======================================================================

Validate the spatial flood extent produced by the Bingham ensemble
against an observed flood raster derived from Google Earth Engine (GEE).

Workflow
--------
For each ensemble run:

    1. Read the maximum water surface elevation from the HEC-RAS HDF.
    2. Calculate maximum water depth for each native HEC-RAS cell.
    3. Join cell depths to the native HEC-RAS mesh.
    4. Reproject the mesh to the GEE reference raster CRS.
    5. Rasterize HEC-RAS cell depths onto the exact GEE raster grid.
    6. Define the common assessment domain.
    7. Apply the configured depth thresholds.
    8. Calculate IoU, F1, POD, and FAR.
    9. Store the results together with the rheological parameters.

The number of ensemble runs is determined automatically from
PARAMETER_CSV.

Required packages
-----------------
    geopandas
    rasterio
    h5py
    pandas
    numpy

Required parameter CSV columns
------------------------------
    Run
    Cv
    Yield_Stress_Pa
    Viscosity_Pa_s

Required configuration
----------------------
    RESULTS_DIR
    PARAMETER_CSV
    SPATIAL_VALIDATION_CSV
    GEE_FLOOD_RASTER
    HECRAS_NATIVE_MESH
    DEPTH_THRESHOLDS
    WSE_PATH
    ELEVATION_PATH
    CELL_CENTER_PATH

Optional configuration
----------------------
    HDF_FILE_PATTERN

Default:

    run_{run_id:03d}.p31.hdf

Output
------
    SPATIAL_VALIDATION_CSV

Output metrics
--------------
    Threshold_m
    Observed_Flood_Pixels
    Predicted_Flood_Pixels
    TP
    FP
    FN
    TN
    IoU
    F1
    POD
    FAR

Notes
-----
The spatial validation uses the common assessment domain defined by
the rasterized HEC-RAS mesh. Pixels outside the HEC-RAS mesh are not
included in the confusion matrix.

The observed flood raster is interpreted as:

    1 = flooded
    0 = not flooded

The HEC-RAS prediction is classified as flooded when:

    depth > threshold

All spatial metrics are calculated independently for each configured
depth threshold.
======================================================================
"""

from pathlib import Path
import sys

import h5py
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.features import rasterize


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
        SPATIAL_VALIDATION_CSV,
        GEE_FLOOD_RASTER,
        HECRAS_NATIVE_MESH,
        DEPTH_THRESHOLDS,
        WSE_PATH,
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


try:
    from config.config import CELL_CENTER_PATH
except ImportError:
    CELL_CENTER_PATH = (
        "Geometry/2D Flow Areas/2D Flow Area/"
        "Cells Center Coordinate"
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

    The parameter CSV is the single source of truth for the ensemble
    size and run IDs.
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
        params["Run"] = (
            params["Run"]
            .astype(int)
        )
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
# CALCULATE SPATIAL METRICS
# ======================================================================

def calculate_metrics(
    observed: np.ndarray,
    depth: np.ndarray,
    domain: np.ndarray,
    threshold: float,
) -> dict:
    """
    Calculate spatial flood extent metrics.

    Parameters
    ----------
    observed:
        Boolean observed flood raster.

    depth:
        HEC-RAS maximum depth raster.

    domain:
        Boolean assessment domain indicating valid HEC-RAS cells.

    threshold:
        Flood depth threshold in metres.

    Returns
    -------
    dict
        Confusion matrix counts and spatial performance metrics.
    """

    # ------------------------------------------------------------------
    # Classify predicted flood pixels
    # ------------------------------------------------------------------

    predicted = (
        (depth > threshold)
        & domain
    )

    observed_domain = (
        observed
        & domain
    )

    # ------------------------------------------------------------------
    # Confusion matrix
    # ------------------------------------------------------------------

    tp = int(
        np.sum(
            predicted
            & observed_domain
        )
    )

    fp = int(
        np.sum(
            predicted
            & ~observed_domain
        )
    )

    fn = int(
        np.sum(
            ~predicted
            & observed_domain
        )
    )

    tn = int(
        np.sum(
            ~predicted
            & ~observed_domain
        )
    )

    # ------------------------------------------------------------------
    # Intersection over Union
    # ------------------------------------------------------------------

    iou_denominator = (
        tp + fp + fn
    )

    iou = (
        tp / iou_denominator
        if iou_denominator
        else np.nan
    )

    # ------------------------------------------------------------------
    # F1 score
    # ------------------------------------------------------------------

    f1_denominator = (
        2 * tp + fp + fn
    )

    f1 = (
        2 * tp / f1_denominator
        if f1_denominator
        else np.nan
    )

    # ------------------------------------------------------------------
    # Probability of Detection
    # ------------------------------------------------------------------

    pod_denominator = (
        tp + fn
    )

    pod = (
        tp / pod_denominator
        if pod_denominator
        else np.nan
    )

    # ------------------------------------------------------------------
    # False Alarm Ratio
    # ------------------------------------------------------------------

    far_denominator = (
        tp + fp
    )

    far = (
        fp / far_denominator
        if far_denominator
        else np.nan
    )

    return {
        "Threshold_m": threshold,
        "Observed_Flood_Pixels": int(
            observed_domain.sum()
        ),
        "Predicted_Flood_Pixels": int(
            predicted.sum()
        ),
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "TN": tn,
        "IoU": iou,
        "F1": f1,
        "POD": pod,
        "FAR": far,
    }


# ======================================================================
# READ MAXIMUM DEPTH
# ======================================================================

def read_max_depth(
    hdf_path: Path,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Read HEC-RAS HDF output and calculate maximum depth per cell.

    Returns
    -------
    depth:
        Maximum water depth for each HEC-RAS cell.

    coords:
        Native HEC-RAS cell-center coordinates.
    """

    if not hdf_path.exists():
        raise FileNotFoundError(
            f"HDF file not found:\n"
            f"{hdf_path}"
        )

    with h5py.File(
        hdf_path,
        "r",
    ) as hdf:

        # --------------------------------------------------------------
        # Check required datasets
        # --------------------------------------------------------------

        required_paths = [
            WSE_PATH,
            ELEVATION_PATH,
            CELL_CENTER_PATH,
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

        # --------------------------------------------------------------
        # Read datasets
        # --------------------------------------------------------------

        wse = np.asarray(
            hdf[WSE_PATH][:]
        )

        elevation = np.asarray(
            hdf[ELEVATION_PATH][:]
        )

        coords = np.asarray(
            hdf[CELL_CENTER_PATH][:]
        )

    # ------------------------------------------------------------------
    # Validate dimensions
    # ------------------------------------------------------------------

    if wse.ndim != 2:
        raise ValueError(
            "Water Surface dataset is expected to have "
            "dimensions: time × cell."
        )

    if elevation.ndim != 1:
        raise ValueError(
            "Elevation dataset is expected to be one-dimensional."
        )

    if wse.shape[1] != len(elevation):
        raise ValueError(
            "WSE cell dimension does not match elevation length.\n"
            f"WSE cells: {wse.shape[1]}\n"
            f"Elevation cells: {len(elevation)}"
        )

    if len(coords) != len(elevation):
        raise ValueError(
            "Cell-center coordinate count does not match "
            "the number of HEC-RAS cells.\n"
            f"Coordinates: {len(coords)}\n"
            f"Elevation cells: {len(elevation)}"
        )

    # ------------------------------------------------------------------
    # Calculate maximum water surface elevation
    # ------------------------------------------------------------------

    max_wse = np.max(
        wse,
        axis=0,
    )

    # ------------------------------------------------------------------
    # Calculate maximum depth
    # ------------------------------------------------------------------

    depth = (
        max_wse
        - elevation
    )

    # ------------------------------------------------------------------
    # Mask invalid elevation cells
    # ------------------------------------------------------------------

    depth[
        np.isnan(elevation)
    ] = np.nan

    # ------------------------------------------------------------------
    # Remove negative depths
    # ------------------------------------------------------------------

    depth[
        depth < 0
    ] = 0

    return depth, coords


# ======================================================================
# VALIDATE INPUT RASTER
# ======================================================================

def read_observed_raster(
    raster_path: Path,
) -> tuple[
    np.ndarray,
    object,
    object,
    tuple[int, int],
]:
    """
    Read the observed GEE flood raster and return its reference grid.
    """

    if not raster_path.exists():
        raise FileNotFoundError(
            f"Observed flood raster not found:\n"
            f"{raster_path}"
        )

    with rasterio.open(
        raster_path,
        "r",
    ) as src:

        observed_raw = src.read(
            1
        )

        observed = (
            observed_raw == 1
        )

        crs = src.crs
        transform = src.transform
        shape = (
            src.height,
            src.width,
        )

    if crs is None:
        raise ValueError(
            "The observed flood raster does not contain a CRS."
        )

    return (
        observed,
        crs,
        transform,
        shape,
    )


# ======================================================================
# LOAD AND VALIDATE HEC-RAS MESH
# ======================================================================

def load_hecras_mesh(
    mesh_path: Path,
) -> gpd.GeoDataFrame:
    """
    Load and validate the native HEC-RAS mesh.
    """

    if not mesh_path.exists():
        raise FileNotFoundError(
            f"HEC-RAS native mesh not found:\n"
            f"{mesh_path}"
        )

    mesh = gpd.read_file(
        mesh_path
    )

    if "cell_id" not in mesh.columns:
        raise ValueError(
            "Native HEC-RAS mesh must contain "
            "a 'cell_id' column."
        )

    if mesh.crs is None:
        raise ValueError(
            "Native HEC-RAS mesh does not contain a CRS."
        )

    mesh["cell_id"] = (
        mesh["cell_id"]
        .astype(int)
    )

    if mesh["cell_id"].duplicated().any():
        raise ValueError(
            "Duplicate cell_id values were found "
            "in the native HEC-RAS mesh."
        )

    return mesh


# ======================================================================
# RASTERIZE HEC-RAS DEPTH
# ======================================================================

def rasterize_depth(
    mesh: gpd.GeoDataFrame,
    depth: np.ndarray,
    gee_crs,
    transform,
    shape,
) -> np.ndarray:
    """
    Rasterize HEC-RAS maximum depth onto the exact GEE reference grid.
    """

    # ------------------------------------------------------------------
    # Validate depth length
    # ------------------------------------------------------------------

    if len(depth) != len(mesh) and len(depth) < len(mesh):
        raise ValueError(
            "The HEC-RAS depth array contains fewer cells "
            "than the native mesh."
        )

    # ------------------------------------------------------------------
    # Create cell-depth table
    # ------------------------------------------------------------------

    depth_df = pd.DataFrame(
        {
            "cell_id": np.arange(
                len(depth),
                dtype=int,
            ),
            "depth": depth,
        }
    )

    # ------------------------------------------------------------------
    # Join depth to native HEC-RAS mesh
    # ------------------------------------------------------------------

    gdf = mesh.merge(
        depth_df,
        on="cell_id",
        how="left",
    )

    gdf = gdf[
        gdf["depth"].notna()
    ].copy()

    if gdf.empty:
        raise ValueError(
            "No valid HEC-RAS cells remain after "
            "joining depth data to the native mesh."
        )

    gdf["depth"] = (
        gdf["depth"]
        .astype(float)
        .clip(lower=0)
    )

    # ------------------------------------------------------------------
    # Reproject mesh to the GEE reference CRS
    # ------------------------------------------------------------------

    if gdf.crs != gee_crs:

        gdf = gdf.to_crs(
            gee_crs
        )

    # ------------------------------------------------------------------
    # Remove invalid geometries
    # ------------------------------------------------------------------

    gdf = gdf[
        gdf.geometry.notna()
        & ~gdf.geometry.is_empty
    ].copy()

    if gdf.empty:
        raise ValueError(
            "No valid HEC-RAS geometries remain "
            "after CRS transformation."
        )

    # ------------------------------------------------------------------
    # Prepare rasterization shapes
    # ------------------------------------------------------------------

    shapes = (
        (
            geometry,
            value,
        )
        for geometry, value
        in zip(
            gdf.geometry,
            gdf["depth"],
        )
        if (
            geometry is not None
            and not geometry.is_empty
        )
    )

    # ------------------------------------------------------------------
    # Rasterize using the exact GEE grid
    # ------------------------------------------------------------------

    depth_grid = rasterize(
        shapes=shapes,
        out_shape=shape,
        transform=transform,
        fill=np.nan,
        all_touched=False,
        dtype="float32",
    )

    return depth_grid


# ======================================================================
# MAIN
# ======================================================================

def main() -> None:

    # ==================================================================
    # LOAD INPUTS
    # ==================================================================

    params = load_parameter_table(
        PARAMETER_CSV
    )

    total_runs = len(params)

    (
        observed,
        gee_crs,
        transform,
        shape,
    ) = read_observed_raster(
        GEE_FLOOD_RASTER
    )

    mesh = load_hecras_mesh(
        HECRAS_NATIVE_MESH
    )

    # ==================================================================
    # PRINT CONFIGURATION
    # ==================================================================

    print(
        "\n" + "=" * 80
    )

    print(
        "HEC-RAS BINGHAM ENSEMBLE — SPATIAL VALIDATION"
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
        f"Native HEC-RAS mesh  : {HECRAS_NATIVE_MESH}"
    )

    print(
        f"GEE flood raster     : {GEE_FLOOD_RASTER}"
    )

    print(
        f"Raster dimensions    : {shape[1]} × {shape[0]}"
    )

    print(
        f"Depth thresholds     : "
        f"{list(DEPTH_THRESHOLDS)}"
    )

    print(
        f"Output               : "
        f"{SPATIAL_VALIDATION_CSV}"
    )

    print(
        "=" * 80
    )

    # ==================================================================
    # PROCESS ENSEMBLE
    # ==================================================================

    all_records = []

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
        # PROCESS RUN
        # ==============================================================

        try:

            # ----------------------------------------------------------
            # Read maximum HEC-RAS depth
            # ----------------------------------------------------------

            depth, _ = read_max_depth(
                hdf_path
            )

            # ----------------------------------------------------------
            # Rasterize HEC-RAS depth to GEE grid
            # ----------------------------------------------------------

            depth_grid = rasterize_depth(
                mesh=mesh,
                depth=depth,
                gee_crs=gee_crs,
                transform=transform,
                shape=shape,
            )

            # ----------------------------------------------------------
            # Define common assessment domain
            # ----------------------------------------------------------

            domain = np.isfinite(
                depth_grid
            )

            if not domain.any():
                raise ValueError(
                    "The rasterized HEC-RAS depth grid "
                    "contains no valid cells."
                )

            # ----------------------------------------------------------
            # Calculate metrics for each depth threshold
            # ----------------------------------------------------------

            for threshold in DEPTH_THRESHOLDS:

                row = (
                    parameter_row
                    .to_dict()
                )

                row.update(
                    calculate_metrics(
                        observed=observed,
                        depth=depth_grid,
                        domain=domain,
                        threshold=float(
                            threshold
                        ),
                    )
                )

                all_records.append(
                    row
                )

            print(
                f"Run {run_id:03d}: "
                "spatial validation complete"
            )

        # ==============================================================
        # EXTRACTION / VALIDATION FAILURE
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
    # CREATE OUTPUT TABLE
    # ==================================================================

    out = pd.DataFrame(
        all_records
    )

    # ==================================================================
    # SAVE RESULTS
    # ==================================================================

    SPATIAL_VALIDATION_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    out.to_csv(
        SPATIAL_VALIDATION_CSV,
        index=False,
    )

    # ==================================================================
    # SUMMARY
    # ==================================================================

    successful_runs = (
        len(
            out["Run"].unique()
        )
        if not out.empty
        else 0
    )

    print(
        "\n" + "=" * 80
    )

    print(
        "SPATIAL VALIDATION FINISHED"
    )

    print(
        "=" * 80
    )

    print(
        f"Total parameter sets  : {total_runs}"
    )

    print(
        f"Successfully processed: "
        f"{successful_runs}"
    )

    print(
        f"Missing HDFs          : "
        f"{len(missing_runs)}"
    )

    print(
        f"Failed runs           : "
        f"{len(failed_runs)}"
    )

    print(
        f"Output rows           : "
        f"{len(out)}"
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
    # Failed run summary
    # ------------------------------------------------------------------

    if failed_runs:

        print(
            "\nFailed runs:"
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
        SPATIAL_VALIDATION_CSV
    )

    print(
        "=" * 80
    )


# ======================================================================
# ENTRY POINT
# ======================================================================

if __name__ == "__main__":
    main()

