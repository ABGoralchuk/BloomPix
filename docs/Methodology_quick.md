## 1. Data & Metadata

- **TIFF Tag `34682` Auto-Calibration:** Parses `PixelWidth` ($\Delta x$ in $\mu\text{m/px}$), `HFW`, `ResolutionX`, `ResolutionY`, `HV`, and `WD`, and crops the bottom databar (`arr[:ResolutionY, :ResolutionX]`) before any computation (with automatic banner detection + manual override fallback for non-FEI images).
- **Raster Quantization Uncertainty ($u_{\text{raster}}$):** Single-pixel uniform discretization uncertainty:

$$u_{\text{raster}} = \frac{\Delta x}{\sqrt{12}} \quad [\mu\text{m}]$$

- **HV Consistency Audit (`HV_Mismatch`):** Flags micrographs acquired off the modal beam voltage (e.g., `10 kV` among `5 kV` scans) and excludes them from kinetic fits by default:

$$|\text{HV} - \text{HV}_{\text{mode}}| > 0.25\ \text{kV}$$

## 2. Roughness & Pseudo-AFM

- **Immerkaer Detector Noise ($\sigma_{\text{noise}}$):** Robust MAD high-frequency shot/electronic noise floor via the $3 \times 3$ zero-mean Laplacian $K_{\text{Im}}$:

$$K_{\text{Im}} = \begin{bmatrix} 1 & -2 & 1 \\ -2 & 4 & -2 \\ 1 & -2 & 1 \end{bmatrix}, \quad \sigma_{\text{noise}} = \max\!\left(\frac{\text{median}(|I * K_{\text{Im}}|) / 0.6745}{6},\; 10^{-9}\right)$$

- **Affine Brightness/Contrast Invariance:** Zero-sum $K_{\text{Im}}$ plus Gaussian tilt removal ($I_{\text{flat}} = I - G_{\sigma_{\text{bg}}}(I)$, $I_{\text{topo}} = G_{\sigma_{\text{topo}}}(I_{\text{flat}})$) makes manual gain $a > 0$ and offset $b$ cancel identically:

$$I' = a \cdot I + b \implies \sigma'_{\text{noise}} = a \cdot \sigma_{\text{noise}}$$

- **`TRNR_Relief`:** Global topographic relief-to-noise ratio (AFM $S_q$ proxy):

$$\text{TRNR}_{\text{Relief}} = \frac{\text{std}(I_{\text{topo}})}{\sigma_{\text{noise}}}$$

- **Smooth Isotropic Gaussian Pseudo-AFM (`LocTRNR`):** Local roughness map with $\sigma_{\text{loc}} = \text{clip}(1.0\ \mu\text{m}/\Delta x,\; 4.0,\; \min(H,W)/16)$ (summarized via `LocTRNR_Med` and `LocTRNR_P90`):

$$\text{LocTRNR}(x, y) = \frac{\sqrt{\max\!\left(G_{\sigma_{\text{loc}}}(I_{\text{topo}}^2) - [G_{\sigma_{\text{loc}}}(I_{\text{topo}})]^2,\; 0\right)}}{\sigma_{\text{noise}}}$$

- **`Bloom_Coverage_%`:** Valid surface area exceeding Week 0 control 95th percentile $T_{\text{ctrl},95}$ (fresh baseline $\approx 5\%$):

$$\text{Bloom\_Coverage}_{\%} = 100 \times \text{mean}\!\left(\text{LocTRNR}(x, y) > T_{\text{ctrl},95}\right)$$

- **`Meso_SNR`:** Mesoscale (`0.27–2.7 µm`) Difference-of-Gaussians crystal-cluster relief-to-noise ratio:

$$\text{Meso\_SNR} = \frac{\text{std}\!\left(G_{\sigma_{\text{small}}}(I_{\text{flat}}) - G_{\sigma_{\text{large}}}(I_{\text{flat}})\right)}{\sigma_{\text{noise}}}$$

- **`Grad_SNR`:** Noise-normalized Scharr RMS slope (AFM $S_{dq}$ proxy):

$$\text{Grad\_SNR} = \frac{\sqrt{\text{mean}\!\left(G_x^2 + G_y^2\right)}}{\sigma_{\text{noise}}}$$

- **`Blade_Index`:** Multiscale Sato Hessian ridge response (`0.16, 0.32, 0.54 µm`) to protruding crystal needles:

$$\text{Blade\_Index} = \text{mean}\!\left(\text{Sato}\!\left(\frac{I_{\text{topo}} - \text{mean}(I_{\text{topo}})}{\sigma_{\text{noise}}};\; \sigma_1, \sigma_2, \sigma_3\right)\right)$$

- **`Anisotropy_Coh`:** Noise-free Structure Tensor directional coherency (`0–1`) of crystal blades:

$$\text{Anisotropy\_Coh} = \text{mean}\!\left(\frac{\sqrt{(J_{xx} - J_{yy})^2 + 4J_{xy}^2}}{J_{xx} + J_{yy}}\right)$$

- **2D FFT Radial PSD (`PSD_logSNR`, `PSD_Beta`):** Physical spatial frequency $f_{\mu\text{m}^{-1}}$, structural-to-noise power ratio, and mid-band power-law slope $\beta$:

$$f_{\mu\text{m}^{-1}} = \frac{f_{\text{px}}}{N_{\text{ref}} \cdot \Delta x}, \quad \text{PSD\_logSNR} = \log_{10}\!\left(\frac{\text{mean}(\text{PSD}[f_{\text{struct}}])}{\text{mean}(\text{PSD}[f_{\text{noise}}])}\right)$$

$$\log_{10}\text{PSD}(f) = -\beta \cdot \log_{10}(f) + c$$

- **Spatial Correlation Length (`Corr_Len_um`):** Characteristic crystal domain size at 2D autocorrelation $1/e$ decay:

$$L_{\text{corr}} = r_{1/e} \cdot \Delta x \quad [\mu\text{m}]$$

- **Composite Bloom Index (`CBI`):** Mean baseline-anchored score across 8 monotonic bloom metrics (Control $\approx 0$, severe bloom $> 100$):

$$\text{CBI} = \frac{1}{8} \sum_{m=1}^{8} \max\!\left(\frac{x_m - \mu_{m,\text{ctrl}}}{P_{95,m} - \mu_{m,\text{ctrl}}} \times 100,\; -20\right)$$

- **`Geom_Bloom_Index`:** HV-resilient cross-check across 3 noise-free geometric/spectral metrics (`Anisotropy_Coh`, `Corr_Len_um`, `PSD_Beta`):

$$\text{Geom\_Bloom\_Index} = \frac{1}{3} \sum_{g=1}^{3} \max\!\left(\frac{x_g - \mu_{g,\text{ctrl}}}{P_{95,g} - \mu_{g,\text{ctrl}}} \times 100,\; -20\right)$$

## 3. Kinetics & Comparison

- **4-Parameter Logistic Fit & Lag Time ($t_{\text{lag}}$):** Bounded nonlinear least-squares curve with 10%-rise induction lag ($\ln 9 \approx 2.197$):

$$y(t) = y_0 + \frac{y_{\max} - y_0}{1 + \exp\!\left(-k\,(t - t_{1/2})\right)}, \quad t_{\text{lag}} = \max\!\left(0,\; t_{1/2} - \frac{\ln 9}{k}\right)$$

- **Normalized Area Under Curve (`AUC_norm`):** Objective cumulative bloom burden (`Rank #1` = lowest `AUC_norm` = strongest suppression):

$$\text{AUC}_{\text{norm}} = \frac{1}{t_{\max} - t_{\min}} \int_{t_{\min}}^{t_{\max}} y(t)\,dt$$

- **Trajectory Classes:**
  - **`Suppressed`:** $\Delta\text{CBI} < 20$ pts (or max Coverage $< 15\%$), $t_{\text{lag}} = \text{None}$.
  - **`Fitted`:** Accepted logistic fit with $R^2 \ge 0.50$ and $k < 4.95$.
  - **`Mild / Non-Sigmoidal Drift`:** Fallback class; reports $t_{\text{lag}}$ only when $\text{CBI} \ge 25$ (or Coverage $\ge 15\%$) persists across $\ge 2$ consecutive valid weeks.
- **2D PCA (9 Metrics):** `StandardScaler` PCA over 9 invariant surface metrics tracking smooth-to-bloomed morphological evolution.
- **Hypothesis Tests (Weeks $\ge \text{Min\_Week}$, default `8`):** One-Way **ANOVA** ($F, p$), **Kruskal–Wallis** ($H, p$), and pairwise **Welch $t$-test** & **Mann–Whitney $U$**.

## 4. DSC Correlation

- **Smart Pre-/Post-Melting Baseline (`HF_base`):** Left anchor $(T_{\text{lo}}, HF_{\text{lo}})$ picks the flattest $0.6\,^\circ\text{C}$ plateau in $[21.6, 24.2]\,^\circ\text{C}$ within $0.006\ \text{W/g}$ of the $[21.6, 23.0]\,^\circ\text{C}$ 90th percentile; right anchor $(T_{\text{hi}}, HF_{\text{hi}})$ picks the flattest $1.5\,^\circ\text{C}$ window in $[38.0, 45.0]\,^\circ\text{C}$:

$$HF_{\text{base}}(T) = HF_{\text{lo}} + \frac{HF_{\text{hi}} - HF_{\text{lo}}}{T_{\text{hi}} - T_{\text{lo}}} \cdot (T - T_{\text{lo}})$$

- **Endothermic Signal (`endo(T)`) & Melting Peak (`T_peak`):** Positive endothermic heat flow (endothermic down) and dominant polymorph maximum ($\beta_{\text{V}} \approx 32\text{--}34\,^\circ\text{C}$, $\beta_{\text{VI}} > 34\,^\circ\text{C}$):

$$\text{endo}(T) = HF_{\text{base}}(T) - HF(T), \quad T_{\text{peak}} = \arg\max_{T \in [T_{\text{lo}}, T_{\text{hi}}]} \text{endo}_{\text{smooth}}(T)$$

- **ASTM E794 Onset & Endset (`T_onset`, `T_endset`):** Steepest leading ($T^*_{\text{lead}}$) and trailing ($T^*_{\text{trail}}$) tangent baseline intercepts (20–80% peak height):

$$T_{\text{onset}} = T^*_{\text{lead}} - \frac{\text{endo}_{\text{smooth}}(T^*_{\text{lead}})}{(d\,\text{endo}_{\text{smooth}}/dT)\big|_{T^*_{\text{lead}}}}, \quad T_{\text{endset}} = T^*_{\text{trail}} - \frac{\text{endo}_{\text{smooth}}(T^*_{\text{trail}})}{(d\,\text{endo}_{\text{smooth}}/dT)\big|_{T^*_{\text{trail}}}}$$

- **Melting Range (`ΔT`) & Peak Broadening (`FWHM`):** Polymorphic heterogeneity and width at 50% peak height:

$$\Delta T = T_{\text{endset}} - T_{\text{onset}}, \quad \text{FWHM} = T_{\text{right},0.5} - T_{\text{left},0.5}$$

- **Melting Enthalpy (`ΔH`) & High-Melt Fraction (`F_>34°C`):** Time-integrated crystallinity ($t = \text{time}_{\min} \times 60\ \text{s}$) and $\beta_{\text{VI}}$ proxy above cutoff (default $34.0\,^\circ\text{C}$):

$$\Delta H = \int_{t_{\text{lo}}}^{t_{\text{hi}}} \max\!\big(HF_{\text{base}}(t) - HF(t),\; 0\big)\,dt \quad [\text{J/g}], \quad F_{>34^\circ\text{C}} = \frac{\Delta H_{T \ge 34^\circ\text{C}}}{\Delta H} \times 100\%$$

- **Baseline QC (`Overshoot_%`):** Flags `Review Baseline` only if $\text{Overshoot}_{\%} > 5.0\%$, $T_{\text{onset}} < T_{\text{lo}} + 0.05\,^\circ\text{C}$, or $\Delta H \le 1.0\ \text{J/g}$ (bimodal curves are informational; valid manual overrides become `OK (Manual)`):

$$\text{Overshoot}_{\%} = \frac{100}{N} \sum_{i=1}^{N} \mathbb{I}\!\left(HF(T_i) > HF_{\text{base}}(T_i) + 0.004\right)$$

- **SEM × DSC Correlation (Pearson $r$ & Spearman $\rho$):** Linear and tie-adjusted monotonic correlation on matched weekly means ($n \ge 3$; Pooled or Per-Treatment scope, honoring global HV policy):

$$r = \frac{\sum_{i=1}^{n}(x_i - \bar{x})(y_i - \bar{y})}{\sqrt{\sum_{i=1}^{n}(x_i - \bar{x})^2}\sqrt{\sum_{i=1}^{n}(y_i - \bar{y})^2}}, \quad \rho = 1 - \frac{6\sum_{i=1}^{n} d_i^2}{n(n^2 - 1)}$$

## 5. Export & Report

- **Reproducible ZIP Archive Manifest:** Single study-agnostic bundle archiving complete run provenance and publication deliverables:
  - **`settings.json`:** Build version/hash, active scale, `AnalysisConfig` (`pseudo_afm_gaussian_sigma_um = 1.0 µm`), and HV exclusion policy.
  - **`analysis_report.md`:** Structured Markdown summary of dataset coverage, HV audit, treatment rankings, statistics, and optional DSC correlation highlights.
  - **300-DPI PNG Figures:** Per-treatment All-Weeks Pseudo-AFM & Sato grids, 2D FFT Radial PSD (`µm⁻¹`), 2D PCA, and kinetic progression + Treatment × Week heatmaps for all 8 metrics.
  - **CSV Tables:** Image-level roughness, weekly kinetics, rankings, ANOVA/Kruskal–Wallis & pairwise tests, radial PSDs, and optional DSC replicate/summary/correlation tables.
