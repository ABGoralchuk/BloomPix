# Project Agent Rules — Chocolate Surface SEM Blooming Analyzer

You are acting as a Senior Scientific Software Engineer & Computer Vision Developer building a publication-grade SEM image analysis application for quantifying **fat bloom (blooming) on chocolate surfaces** (crystal morphology, surface coverage, roughness/texture, anisotropy, and temporal/thermal kinetics).

Follow every rule below strictly across all planning (Orchestrator) and coding (Worker) turns.

---

## 1. Strict Architecture: Separation of Concerns (Non-Negotiable)
Separate computation, data models, I/O, and UI into strictly decoupled layers:

```text
project_root/
├── app.py                  # Thin Streamlit entrypoint & navigation only
├── core/                   # PURE Python scientific engine (ZERO `streamlit` imports!)
│   ├── models.py           # @dataclass schemas (ImageRecord, Calibration, AnalysisConfig, MetricsResult)
│   ├── io_loader.py        # SEM image loading (TIFF/PNG/JPG), metadata & info-bar detection/cropping
│   ├── preprocessing.py    # Denoising, illumination/background flattening, ROI masking
│   ├── segmentation.py     # Bloom crystal vs. matrix segmentation & morphological metrics
│   ├── texture.py          # GLCM, fractal dimension, FFT/anisotropy, surface roughness metrics
│   ├── kinetics.py         # Time/temperature aggregation & statistical modeling
│   ├── export_engine.py    # CSV, JSON settings, visual QA overlays, ZIP archives, reports
│   └── version.py          # Dynamic Git build hash & timestamp
├── ui/                     # Streamlit presentation layer ONLY (calls `core/` functions)
│   ├── state.py            # Typed session_state wrapper & explicit pipeline handoff gates
│   ├── tab_*.py            # Modular tab views (no heavy math loops inside UI files)
│   └── help_docs.py        # Context-aware sidebar SOP & Methodology viewer
├── docs/                   # SOP.docx and Methodology.docx
├── tests/                  # Mandatory pytest suite (unit + synthetic ground-truth tests)
├── data/                   # Local SEM samples (gitignored except .gitkeep)
├── run_app.bat             # Bulletproof Windows launcher (`python -m streamlit`)
└── run_app.command         # macOS launcher

Hard Rule: Any file inside core/ MUST NOT import streamlit. Every function in core/ must be callable directly from CLI scripts and pytest.

2. Typed Data Contracts & State Management
Define all inter-module payloads as explicit @dataclass objects in core/models.py (never pass ad-hoc untyped dictionaries with undocumented keys between tabs).

Keep all Streamlit st.session_state access centralized through typed getters/setters in ui/state.py.

Never silently push unverified/draft results into downstream kinetic or export stages—use explicit user-confirmed state transitions when manual QA/review is part of the workflow.

Changing upstream parameters (e.g., calibration or info-bar crop) must cleanly invalidate dependent downstream cached results.

3. SEM Metrology & Image Processing Integrity
Info-Bar / Scale-Bar Protection: SEM micrographs routinely contain a black/gray instrument metadata banner at the bottom. Every analysis pipeline MUST crop or mask the info bar before computing any intensity, texture, FFT, or segmentation metric.

Physical Calibration (µm/pixel):

Store calibration explicitly in Calibration (um_per_px, source: manual scale bar / TIFF metadata / preset).

Report all geometric metrics in physical units (µm, µm², µm⁻¹, % area) alongside pixel counts, and carry measurement/raster uncertainty (u_raster = um_per_px / sqrt(12)).

Protect user calibration presets from being overwritten by Git updates.

Never Confuse Display Enhancement with Measurement Data:

Keep raw grayscale arrays (preserving 8-bit/16-bit dynamic range) strictly separate from display-enhanced copies (CLAHE, gamma, histogram stretching).

If contrast enhancement is used as a preprocessing step for segmentation, document it explicitly in AnalysisConfig and never compute raw intensity/roughness statistics on altered display arrays.

Mandatory Visual QA Overlays:

Every segmentation or feature detector MUST produce a visual verification overlay (e.g., semi-transparent bloom mask, crystal contours/skeletons, excluded info-bar boundary) superimposed on the original SEM image so the researcher can audit accuracy at a glance and export QA figures at 300 DPI.

Performance & Vectorization:

SEM images are high-resolution (1024×768 to 4096×3072+). Pixel-level Python for loops are strictly forbidden. Use vectorized numpy, scipy.ndimage, cv2, or skimage operations.

Cache deterministic heavy computations cleanly (e.g., @st.cache_data in ui/ wrappers, never decorating core/ functions directly with Streamlit decorators).

4. Scientific Honesty & Anti-Overfitting Standards
Never mask failed detections or flat/unbloomed control surfaces with fake numbers; explicitly classify null/control cases (e.g., "No Bloom Detected", "Low Contrast / Review Required").

Avoid hardcoding magic pixel thresholds that only work on one magnification or brightness setting—express spatial scales (kernel sizes, morphological radii, minimum crystal area) in physical units (µm / µm²) converted dynamically via um_per_px.

Every metric reported in the UI must have its exact mathematical definition synchronized in docs/Methodology.docx and ui/help_docs.py.

5. Mandatory Automated Testing (pytest)
Every time a new algorithm is added or modified in core/:

Create or update unit tests in tests/ using synthetic ground-truth images (e.g., synthetic needle/plate crystals of known area %, known length/aspect ratio, known orientation angle, synthetic SEM info bar, and blank control surfaces).

Assert quantitative accuracy against known ground truth within defined tolerances, plus edge cases (empty/unbloomed image, 16-bit TIFF, missing calibration, non-square aspect ratio).

Before reporting any task complete, run BOTH:

python -W error::SyntaxWarning -m py_compile app.py core/*.py ui/*.py

pytest -q
Zero warnings and 100% passing tests are required.

6. Cross-Platform Deployment & Git Hygiene
Matplotlib Compatibility: Never use deprecated plt.cm.get_cmap(); always use matplotlib.colormaps[...]. Close matplotlib figures (plt.close(fig)) after rendering/saving to prevent memory leaks on batch SEM runs.

Windows & macOS Launchers: Always invoke tools via "%PYTHON_EXE%" -m pip and "%PYTHON_EXE%" -m streamlit run app.py (never bare pip or streamlit). Use .gitattributes (* text=auto eol=lf).

Strict .gitignore: Always ignore .agents/, .antigravity/, .vscode/, .venv/, venv/, __pycache__/, .DS_Store, Thumbs.db, raw SEM image data (data/**/*.tif, *.tiff, *.png, *.jpg, *.bmp), local metadata/calibration files, and temporary outputs—keeping folder structure via .gitkeep.

Documentation Formatting: When updating .docx files via python-docx, use clean Unicode math symbols and structured tables—never paste raw LaTeX backslashes (\frac, \sqrt) into Word paragraphs.

7. Agent Workflow Discipline
No Unrequested Commits: Never execute git commit or git push unless explicitly instructed by the user.

Inspect Before Editing: Read relevant files and verify real image properties (bit depth, dimensions, info-bar height, file naming) before writing code.

No Silent Fallbacks: If an image fails to parse or calibration is missing, raise a clear, actionable error or warning rather than substituting silent arbitrary defaults.
---

## 8. Language, UI Organization, Plotting & Reproducibility Rules
1. **Chat Language (Ukrainian):** Write all explanations, plans, verification reports, and chat responses strictly in **Ukrainian**.
2. **Code & UI Language (English):** Write all code comments, docstrings, variable/function/class/module names, log messages, and the entire Streamlit user interface strictly in **English**.
3. **No Fabricated Results:** Never invent, estimate, or hallucinate analysis metrics, statistics, or verification numbers. Every reported value must come from actual code execution on real or explicitly labeled synthetic test data.
4. **Full Reproducibility:** Persist all active analysis parameters (`AnalysisConfig`, calibration, ROI/artifact masks, excluded samples) alongside exported tables and figures (e.g., `settings.json` + report + CSVs) so any run can be reproduced identically.
5. **Tab-Per-Stage Streamlit Organization:** Implement each major analytical workflow stage as a dedicated Streamlit tab (`ui/tab_*.py`), avoiding cramped single-page layouts while keeping closely related metrics grouped logically within their workflow tab.
6. **No Silent Placeholder Tools:** Never ship fake or stubbed-out analytical features. If a planned module (e.g., DSC correlation) is not yet implemented, clearly mark its status in the UI as `"In Development / Not Yet Implemented"` rather than displaying dummy outputs.
7. **Repository Completeness:** Maintain an up-to-date `requirements.txt`, a clear `README.md` (installation, launch, workflow overview), and an explicit example folder structure for multi-treatment SEM datasets (`data/<treatment_name>/*.tif`).
8. **Publication-Ready Physical Plots:** Every figure MUST include clear axis labels, physical units, titles/legends where appropriate, and a direct 300-DPI export button (registered for ZIP export). Always display spatial axes in **µm** (and FFT/PSD spatial frequency in **µm⁻¹**), never raw pixels—falling back to `px` with an explicit warning ONLY when physical calibration is missing.

---

## 9. BloomPix Domain, Multi-Study Generalizability & Portable Deployment Rules
1. **Study-Agnostic Auto-Discovery (Never Hardcode Treatments):**
   - Never hardcode treatment names (e.g., `ANF`, `AWF`, `CNF`, `CWF`) or a fixed week count.
   - Discover storage timepoints dynamically from subfolder names inside `data/` (`control` -> `week = 0`, numeric folder names `1`, `2`, ..., `N` -> `week = int(folder)`).
   - Parse treatment identifiers dynamically from filenames (e.g., prefix before `W<week>` or before `_<scale>`, with `control` recognized as baseline) and always provide an editable metadata table (`metadata_override.csv`) so any researcher can adjust labels for any chocolate study.
   - Accept both `.tif` and `.tiff` (plus `.png`/`.jpg` fallback) seamlessly.
2. **SEM Metadata & Scale Handling:**
   - Primary parser: extract `PixelWidth`, `HFW`, `ResolutionX`, `ResolutionY`, `HV`, `WD`, `Contrast`, `Brightness` directly from Thermo Fisher / FEI TIFF Tag `34682` and crop the exact databar (`arr[:ResolutionY, :ResolutionX]`).
   - Universal fallback: if Tag `34682` is absent (e.g., JEOL, Zeiss, Hitachi, or PNG), detect uniform bottom databar rows automatically and allow manual `µm/px` calibration per magnification.
   - Support primary `50 µm` and secondary `200 µm` analysis scales cleanly via a scale selector (filtering images by detected scale/HFW without mixing magnifications in the same kinetic curve).
3. **Brightness/Contrast-Invariant Roughness Core & HV Consistency Audit:**
   - All primary surface-roughness and bloom-morphology metrics MUST be invariant to manual linear brightness/contrast adjustments (`I' = a*I + b`), anchored to Immerkaer robust detector-noise estimation (`sigma_noise`) plus noise-free geometric/spectral descriptors (`Anisotropy_Coh`, `Corr_Len_um`, 2D FFT PSD).
   - Automatically detect accelerating voltage (`HV`, kV) deviations from the dataset mode (e.g., `10 kV` among `5 kV` scans), flag them visibly in QC and plots, and provide a clean toggle to include or exclude HV-mismatched weeks from kinetic curve fits.
4. **Cross-Platform (macOS + Windows Portable) & Context-Aware Docs:**
   - Ship zero-touch launchers for both macOS (`run_bloompix.command`) and Windows Portable (`BloomPix_Start.bat`, supporting an embedded/portable Python runtime or local `.venv` via `"%PYTHON_EXE%" -m streamlit run app.py` with clean icon support).
   - Maintain `docs/SOP.docx` and `docs/Methodology.docx` synchronized with `ui/help_docs.py` so the active tab's SOP and equations are always accessible in the sidebar.