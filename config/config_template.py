"""
Configuration template for the HEC-RAS Bingham ensemble workflow.

Copy this file to config/config.py and edit the paths for your machine.
Do not commit config/config.py if it contains private/local paths.
"""

from pathlib import Path

# ---------------------------------------------------------------------
# HEC-RAS model
# ---------------------------------------------------------------------
MODEL_DIR = Path(r"C:\PATH\TO\HEC-RAS_MODEL")
PROJECT_FILE = MODEL_DIR / "MataianAutomation.prj"
PLAN_FILE = MODEL_DIR / "MataianAutomation.p31"
BASE_HDF = MODEL_DIR / "MataianAutomation.p31.hdf"

# ---------------------------------------------------------------------
# Ensemble workspace
# ---------------------------------------------------------------------
ENSEMBLE_DIR = Path(r"C:\PATH\TO\ENSEMBLE")
RESULTS_DIR = ENSEMBLE_DIR / "results"
LOG_DIR = ENSEMBLE_DIR / "logs"

PARAMETER_CSV = ENSEMBLE_DIR / "ensemble_parameter_sets_60.csv"
RESULTS_CSV = ENSEMBLE_DIR / "ensemble_results_60.csv"
FAILURES_CSV = ENSEMBLE_DIR / "ensemble_failures_60.csv"
QC_CSV = ENSEMBLE_DIR / "ensemble_postprocessing_QC.csv"
TRAVEL_TIME_CSV = ENSEMBLE_DIR / "ensemble_travel_time_60runs.csv"
SPATIAL_VALIDATION_CSV = ENSEMBLE_DIR / "ensemble_spatial_validation_60runs.csv"

# ---------------------------------------------------------------------
# Bingham parameter ranges used in the study
# ---------------------------------------------------------------------
CV_RANGE = (30.0, 50.0)          # %
YIELD_STRESS_RANGE = (50.0, 500.0)  # Pa
VISCOSITY_RANGE = (0.1, 10.0)    # Pa.s

# The final ensemble consisted of 25 previously generated scenarios
# plus 35 new LHS scenarios.
N_EXISTING = 25
N_NEW = 35
TOTAL_RUNS = 60

LHS_SEED = 20260912

# ---------------------------------------------------------------------
# HEC-RAS computation watchdog
# ---------------------------------------------------------------------
MAX_RUNTIME_SECONDS = 1500
POLL_INTERVAL_SECONDS = 5

# ---------------------------------------------------------------------
# Spatial validation
# ---------------------------------------------------------------------
DEPTH_THRESHOLDS = (0.1, 0.5, 1.0)
PRIMARY_DEPTH_THRESHOLD = 0.5

# ---------------------------------------------------------------------
# Temporal validation
# ---------------------------------------------------------------------
OBSERVED_TRAVEL_TIME_MIN = 54.0
BRIDGE_DEPTH_THRESHOLD_M = 0.01

# 30 bridge/profile cells used in the previous travel-time analysis.
BRIDGE_CELLS = [
    53295, 117636, 117758, 117908, 118080,
    118274, 118501, 118755, 119023, 119024,
    119287, 119555, 119830, 120112, 120401,
    120698, 121002, 121315, 121639, 121977,
    122312, 122645, 122975, 123288, 123289,
    123582, 141707, 145643, 147605, 151576
]

# ---------------------------------------------------------------------
# Optional observed spatial data
# ---------------------------------------------------------------------
GEE_FLOOD_RASTER = ENSEMBLE_DIR / "GEE_flood.tif"
HECRAS_NATIVE_MESH = ENSEMBLE_DIR / "HECRAS_native_cells.gpkg"

# ---------------------------------------------------------------------
# HEC-RAS HDF5 dataset paths
# ---------------------------------------------------------------------
WSE_PATH = (
    "Results/Unsteady/Output/Output Blocks/Base Output/"
    "Unsteady Time Series/2D Flow Areas/2D Flow Area/Water Surface"
)
TIME_PATH = (
    "Results/Unsteady/Output/Output Blocks/Base Output/"
    "Unsteady Time Series/Time"
)
ELEVATION_PATH = (
    "Geometry/2D Flow Areas/2D Flow Area/Cells Minimum Elevation"
)
CELL_AREA_PATH = (
    "Geometry/2D Flow Areas/2D Flow Area/Cells Surface Area"
)
CELL_COORDINATE_PATH = (
    "Geometry/2D Flow Areas/2D Flow Area/Cells Center Coordinate"
)
