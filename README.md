# HEC-RAS Bingham Ensemble

Reproducibility code for a 60-scenario Bingham rheology ensemble implemented with HEC-RAS 6.6 and Python automation.

## Study workflow

```text
Parameter generation
        ↓
60 Bingham parameter sets
        ↓
HEC-RAS 6.6 ensemble simulation
        ↓
Watchdog / timeout control
        ↓
Archived HDF outputs
        ↓
HDF quality-control extraction
        ├── spatial validation
        └── travel-time extraction
                ↓
        sensitivity analysis
```

## Bingham parameter space

| Parameter | Range |
|---|---:|
| Volumetric concentration, Cv | 30–50 % |
| Yield stress | 50–500 Pa |
| Dynamic viscosity | 0.1–10 Pa.s |
| Total scenarios | 60 |

The final ensemble consists of 25 existing parameter sets plus 35 additional Latin Hypercube samples. The LHS seed is `20260912`.

## HEC-RAS automation

The runner modifies the active U14 file and verifies:

- `Non-Newtonian Constant Vol Conc=`
- `User Yeild=`
- `User Viscosity=`

The project is reloaded before each computation and the parameters are verified again after reload.

### Computation watchdog

The final runner uses non-blocking HEC-RAS computation:

1. `Compute_CurrentPlan(..., False)` starts the computation.
2. `Compute_Complete()` is polled every 5 seconds.
3. The watchdog limit is 1500 seconds.
4. If the limit is exceeded, `Compute_Cancel()` is issued.
5. The failed run is logged and the ensemble continues.

This prevents one unstable/slow scenario from stopping the entire ensemble.

## Repository structure

```text
bingham-hecras-ensemble/
├── README.md
├── requirements.txt
├── .gitignore
├── config/
│   └── config_template.py
├── scripts/
│   ├── 01_generate_parameter_sets.py
│   ├── 02_run_bingham_ensemble.py
│   ├── 03_extract_hdf_results.py
│   ├── 04_extract_travel_time.py
│   ├── 05_spatial_validation.py
│   ├── 06_sensitivity_analysis.py
│   └── 07_ensemble_summary.py
├── notebooks/
│   └── analysis_workflow.ipynb
├── data/
│   └── README.md
├── results/
│   └── README.md
└── logs/
    └── README.md
```

## Requirements

The ensemble runner requires Windows, HEC-RAS 6.6 and the HEC-RAS COM controller.

Python packages used by the workflow include:

- numpy
- pandas
- h5py
- pywin32
- scipy
- geopandas
- rasterio
- matplotlib
- jupyter

See `requirements.txt`.

## Setup

1. Copy `config/config_template.py` to `config/config.py`.
2. Set the local HEC-RAS project and ensemble paths.
3. Put the existing 25-run parameter table at:
   `ensemble_parameter_sets_25.csv`.
4. Run:

```bash
python scripts/01_generate_parameter_sets.py
python scripts/02_run_bingham_ensemble.py
python scripts/03_extract_hdf_results.py
python scripts/04_extract_travel_time.py
python scripts/05_spatial_validation.py
python scripts/06_sensitivity_analysis.py
python scripts/07_ensemble_summary.py
```

Spatial validation additionally requires the observed GEE flood raster and the native HEC-RAS mesh specified in `config.py`.

## What is intentionally not included

Large model outputs and potentially restricted/raw research data are not part of this repository by default:

- HEC-RAS `.hdf` ensemble outputs
- DEM/raw GIS datasets
- observed satellite rasters
- large intermediate files
- local backups
- machine-specific paths
- temporary/debugging files

The repository is intended to document the computational method rather than redistribute the underlying datasets.

## Notes on reproducibility

The exact HEC-RAS project configuration remains an external model dependency. The Python code documents the parameter modification, ensemble generation, timeout control, HDF extraction, spatial validation and temporal analysis used in the study.

## Citation

If this repository accompanies a publication, replace this section with the paper citation and repository DOI after publication.
