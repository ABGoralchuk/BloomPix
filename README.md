# BloomPix v1.1.2 — Chocolate Surface SEM Fat-Bloom Analyzer

Publication-grade scientific application for quantifying fat bloom on chocolate surfaces from Scanning Electron Microscopy (SEM) micrographs using brightness/contrast-invariant surface roughness, smooth isotropic Gaussian Pseudo-AFM heatmaps (`σ = 1.0 µm`), 2D FFT spectral analysis, kinetic modeling, and DSC thermal correlation.

---

## Architecture & Scientific Integrity

- **Strict Separation of Concerns:** All I/O, metrology, preprocessing, roughness/morphology metrics, kinetics, DSC correlation, and ZIP export live in `core/` (zero `streamlit` imports). Presentation lives in `ui/` and `app.py`.
- **Study-Agnostic Dataset Discovery:** Automatically discovers storage timepoints and treatment codes from folder structure and filenames without hardcoding sample names or study duration.
- **Thermo Fisher / FEI Metrology Integrity:** Parses TIFF Tag `34682` (`PixelWidth`, `HFW`, `ResolutionX`, `ResolutionY`, `HV`, `WD`, detector `Contrast`/`Brightness`), crops instrument databars (`arr[:ResolutionY, :ResolutionX]`) prior to any computation, and provides a universal fallback for non-FEI images.
- **Brightness/Contrast-Invariant Roughness Core:** All amplitude and slope metrics anchor to Immerkaer (1996) detector-noise estimation (`σ_noise`), guaranteeing `< 0.05%` error under arbitrary gain/offset adjustments (`I' = a·I + b`).
- **Accelerating Voltage (`HV_Mismatch`) Audit:** Automatically flags scans acquired at non-dominant kV (e.g., `10 kV` among `5 kV` series) and excludes them from kinetic curve fits by default while marking them clearly on plots.

---

## 5-Tab Workflow

1. **`1. Data & Metadata`** — Dataset scanning, KPI summary, compact `Replicate Coverage Matrix`, `HV & Calibration Audit`, and editable `metadata_override.csv`.
2. **`2. Roughness & Pseudo-AFM`** — Multi-threaded batch metric computation, `Single Treatment (All Weeks)` smooth isotropic Gaussian Pseudo-AFM / Sato ridge grids (`300 DPI` combined PNG + individual week PNG ZIP), all-weeks 2D FFT Radial PSD (`µm⁻¹` + CSV), and `Compare Two Treatments` side-by-side mode.
3. **`3. Kinetics & Comparison`** — Bounded 4-parameter logistic modeling, objective ranking (`AUC_norm`, Rank #1 = best suppression), `Treatment × Week` heatmap + CSV exports, 2D Morphology PCA ordination, and post-induction ANOVA / Kruskal–Wallis / pairwise hypothesis tests.
4. **`4. DSC Correlation`** — Raw TA Instruments `.txt` DSC scanning with automatic baseline detection and 4 core thermodynamic parameters (`T_onset_C`, `T_peak_C`, `FWHM_C`, `Delta_H_J_g`), pre-populated CSV template & `.csv`/`.xlsx` upload, Pooled/Per-Treatment Pearson `r` & Spearman `ρ` matrices, and linear scatter plots.
5. **`5. Export & Report`** — Preview `analysis_report.md` and `settings.json`, configure replicate scope, and run the two-step **Build Complete Publication Archive** → **Download ZIP** to package 300-DPI Pseudo-AFM, Sato, PSD, PCA, and all 8 kinetic metric plots + CSVs for every discovered treatment.

Synchronized documentation is available both in the sidebar (**SOP & Methodology Docs**) and in [docs/SOP.docx](docs/SOP.docx) and [docs/Methodology.docx](docs/Methodology.docx).

---

## Installation & Launching

Requires Python 3.11–3.13.

### macOS
Double-click `bloompix_run.command` in Finder, or run from terminal:
```bash
./bloompix_run.command
```
On first run, the launcher creates `./venv`, installs `requirements.txt`, and opens BloomPix in your default browser.

### Windows Portable & Git Clone Launch
Double-click `BloomPix_Start.bat`. On first launch it automatically creates a Desktop shortcut (`BloomPix.lnk`) with the BloomPix icon (`assets\bloompix.ico`), safely checks for repository updates (`git pull --ff-only`) when running inside a Git clone, and locates Python in strict priority order:
1. `python_embed\python.exe` (standalone Windows Portable embedded runtime — zero setup)
2. `venv\Scripts\python.exe`
3. `.venv\Scripts\python.exe`
4. System `python` on `PATH` (automatically creates `venv\` and installs `requirements.txt` on first run)

To manually recreate the Desktop shortcut at any time, run:
```bat
wscript scripts\create_windows_shortcut.vbs
```

To build a self-contained offline Windows x64 Portable archive (`dist/BloomPix_Windows_Portable.zip` with embedded Python 3.11 and all Windows wheels), run on macOS or Windows:
```bash
./venv/bin/python scripts/build_windows_portable.py
```

---

## Expected `data/` Folder Layout

```text
data/
├── control/                  # Week 0 baseline (shared control_* or per-treatment *W0_*)
│   ├── control_50um_5.00kV_4545.tif
│   └── control_200um_5.00kV_4543.tif
├── 1/                        # Week 1
│   ├── TreatmentAW1_50um_5.00kV_0001.tif
│   └── TreatmentBW1_50um_5.00kV_0002.tif
...
└── N/                        # Week N
```

Supported formats: `.tif`, `.tiff`, `.png`, `.jpg`, `.jpeg` (case-insensitive).

---

## Running Tests

```bash
./venv/bin/python -W error::SyntaxWarning -m py_compile app.py core/*.py ui/*.py scripts/build_icons.py
./venv/bin/pytest -q
```
