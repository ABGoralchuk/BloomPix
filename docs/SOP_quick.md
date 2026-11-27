## 1. Data & Metadata

1. Confirm the **Dataset Root Directory** (default: `data/`) and click **Scan Dataset** (auto-scans on startup if populated).
2. Inspect the KPI cards and compact **Replicate Coverage Matrix** (`Week × Treatment`) for the active magnification scale.
3. Audit **HV & Calibration** (toggle `Show only HV-mismatched files` to spot `10 kV` outliers among `5 kV` scans and verify databar crop height).
4. Fix mislabeled treatments/weeks or mark `excluded = True` on defective micrographs, then save to `metadata_override.csv`.

- **Tip:** Select one magnification (`50um` or `200um`) in the left sidebar — scales are never mixed in kinetic curves.

## 2. Roughness & Pseudo-AFM

1. Click **Run Surface Roughness Analysis** to compute all invariant surface metrics and `CBI` for the active scale.
2. Under **Single Treatment (All Weeks)**, pick **Treatment**, **Replicate**, and **Heatmap Type** (`Pseudo-AFM Local TRNR` or `Sato Crystal Blade Response`), then click **Generate All-Weeks Heatmaps & PSD**.
3. Download the combined 300-DPI grid (PNG), individual week maps (ZIP), and 2D FFT Radial PSD (`µm⁻¹`, CSV).
4. Switch to **Compare Two Treatments** for shared-colorbar side-by-side maps and overlaid radial PSD curves.

- **Default:** `50 µm` is the primary quantitative crystal scale; `200 µm` serves as macro cross-validation.

## 3. Kinetics & Comparison

1. Confirm the sidebar **Global HV Policy** (default: exclude `HV_Mismatch` weeks from fits while showing them as hollow diamonds).
2. Pick a **Kinetic Metric** (default: `Composite Bloom Index`) and export **Displayed Kinetic Data (CSV)**.
3. Review **Treatment Ranking** (`Rank #1` = lowest `AUC_norm` = strongest bloom suppression) and export **Heatmap Matrix (CSV)**.
4. Inspect **2D Morphology PCA** trajectories and set **Statistical Comparison Min Week** (default `8`) for ANOVA, Kruskal–Wallis, and pairwise tests.

## 4. DSC Correlation

1. Point **Raw TA Instruments DSC Folder (.txt)** to `data/DSC` (`<treatment>W<week>r<rep>.txt`, `controlr<rep>.txt`) and click **Scan & Analyze Raw DSC Folder** — baselines are detected automatically to compute the 4 core DSC parameters (`T_onset_C`, `T_peak_C`, `FWHM_C`, `Delta_H_J_g`).
2. Check **Baseline QC OK** vs **Needs Review** (flagged only for overshoot `> 5%`, `T_onset < T_lo + 0.05 °C`, or `ΔH ≤ 1.0 J/g`; bimodal peaks are informational). Apply per-file overrides only when flagged (`OK (Manual)`).
3. Inspect **Thermogram QA Inspector** (`T_onset`, `T_peak`, baseline anchors, shaded `ΔH`), **DSC Thermodynamic Evolution**, and export **All Samples — DSC Thermodynamic Parameters** (Weekly Means ± SD or Individual Replicates, CSV).
4. Choose **Correlation Scope** (`All Treatments (Pooled)` vs `Per-Treatment (Within-Group Aging)`) honoring the global HV policy.

## 5. Export & Report

1. Preview `analysis_report.md` and `settings.json` in Section 1.
2. Select **Heatmap & PSD Replicate Scope** (`Rep 1` recommended, `Rep 2`, or `All Replicates`), confirm **Statistical Comparison Min Week**, and optionally toggle individual per-week 300-DPI PNGs.
3. Click **Build Complete Publication Archive** to generate 300-DPI Pseudo-AFM, Sato, PSD, PCA, and all 8 kinetic metric figures & CSVs across every discovered treatment.
4. Confirm the manifest summary and click **Download Complete Publication Archive (ZIP)** (or use **Quick Session Export** for rendered figures only).
