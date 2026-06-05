# JiT Finance Denoising Seed

Related: [[roadmap]], [[xp-73-mission-guide]], [[xp-78-mission-guide]], [[xp-88-backtest-hygiene-checklist]], [[xp-90-mission-guide]]

Status: inbox seed, not an active XP.

Source inspiration: Kaiming He style "back to basics" research taste, especially the idea that a denoising model should directly learn to denoise rather than hide the core task behind too many proxy objectives.

---

## Why This Seed Exists

The current quant roadmap is complete. This note should not restart roadmap pressure. Its job is to preserve one research impulse:

> Can a simple denoising generative model, especially a JiT-like clean-target formulation, be adapted to financial panels in a way that produces a measurable, defensible result?

The useful interpretation is not "generate realistic stock prices." That direction is too easy to make impressive and too hard to make tradable.

The sharper interpretation is:

> Use denoising as representation learning for low signal-to-noise financial data.

If this becomes XP-92 later, it should be framed as a small empirical experiment, not a grand AI strategy.

---

## Question 1: What Is Clean Data in Finance?

This is the central problem. Images have a natural clean target: the original image before noise corruption. Finance does not.

Candidate definitions:

- **Clean factor panel**
  A cross-sectional feature matrix after winsorization, neutralization, scaling, and missing-value handling.

- **Clean return target**
  A forward return label after ranking, clipping, volatility scaling, or sector neutralization.

- **Clean latent signal**
  A smoothed or consensus version of a noisy alpha signal, such as an ensemble average, rolling stable component, or PCA/shrinkage-denoised representation.

- **Clean portfolio decision**
  A more stable ranking or weight vector, not necessarily a cleaner price series.

Working hypothesis:

> In finance, "clean data" should mean "a representation that improves out-of-sample ranking stability or portfolio behavior," not "the true hidden price process."

If the clean target cannot be defined without leaking future information, the experiment fails before modeling starts.

---

## Question 2: What Is the Noising Process?

A financial denoising task must define how information is corrupted.

Possible noising processes:

- **Feature masking**
  Randomly mask factors, assets, or dates and ask the model to reconstruct the missing structure.

- **Cross-sectional corruption**
  Add noise to selected assets in a daily factor vector, then reconstruct the clean cross-section.

- **Temporal corruption**
  Mask short windows in a return or factor series, then reconstruct from neighboring context.

- **Rank corruption**
  Shuffle or perturb factor ranks and ask the model to recover a cleaner ranking.

- **Microstructure-like corruption**
  Add bid-ask bounce, stale price effects, missing ticks, or outlier spikes to synthetic or real intraday features.

The noising process should mimic a real financial failure mode. Random Gaussian noise is acceptable only as a first sanity check.

Best first MVP:

> Start with feature masking on a daily `date x asset x factor` panel, because it is easy to validate, hard to overclaim, and close to the missing-data / noisy-factor problem already present in quant research.

---

## Question 3: What Baseline Must Beat It?

This experiment is only meaningful if it beats boring methods.

Minimum baselines:

- **Do nothing**
  Use raw factor values or raw ranks.

- **Simple smoothing**
  Rolling mean, EWMA, or volatility scaling.

- **PCA denoising**
  Keep top components, reconstruct the panel, compare stability and IC.

- **Shrinkage**
  Compare against covariance or signal shrinkage intuition from [[xp-78-mission-guide]].

- **LightGBM / ridge**
  If the model is used for prediction, compare against disciplined supervised learning from [[xp-90-mission-guide]].

- **Denoising autoencoder**
  A simple MLP or Transformer autoencoder should be the nearest neural baseline before any JiT-style architecture is justified.

Baseline rule:

> If JiT-for-finance cannot beat PCA denoising or a simple denoising autoencoder on a clean walk-forward protocol, it is probably aesthetic inspiration rather than useful research.

---

## Question 4: What Would Count as a Real Result?

Do not count visual plausibility, lower reconstruction loss, or prettier generated samples as success.

A real result should satisfy at least two of the following:

- **Out-of-sample Rank IC improvement**
  Denoised factors improve Rank IC under walk-forward validation.

- **Stability improvement**
  The signal has lower turnover, lower rank volatility, or more stable top/bottom baskets.

- **Portfolio behavior improvement**
  A simple long-short or long-only construction improves realized volatility, drawdown, turnover-adjusted return, or risk attribution.

- **Regime robustness**
  The result does not disappear when split by market regime, sector, or time period.

- **Ablation clarity**
  The result can be traced to the denoising objective, not accidental leakage, overfitting, or data preprocessing.

Hard rejection criteria:

- Any target uses future information not available at prediction time.
- The split violates purge / embargo logic from [[xp-88-backtest-hygiene-checklist]].
- The model only improves in-sample reconstruction loss.
- The improvement disappears after transaction costs or turnover control.
- The result cannot be explained in one paragraph to a PM.

---

## Minimal Experiment Sketch

Input:

- Daily panel: `date x asset x factor`
- Optional labels: forward returns or cross-sectional ranks
- Universe: small liquid stock universe first, not the whole market

Task:

1. Construct a clean factor panel using standard preprocessing.
2. Mask or corrupt part of the panel.
3. Train a simple denoising model to reconstruct the clean panel.
4. Use reconstructed factors for ranking or prediction.
5. Compare against raw factor, PCA denoising, and a simple autoencoder.

Validation:

- Walk-forward split
- Purge / embargo if labels overlap
- No cross-date leakage in normalization
- Report Rank IC, turnover, long-short spread, and drawdown

Deliverable if upgraded:

> A notebook plus a 1-page research memo: "Does denoising improve factor stability under realistic backtest hygiene?"

---

## Open Questions Before XP-92

- What is the smallest dataset that is enough to test the idea honestly?
- Should the first target be factor reconstruction or forward-return ranking?
- Is the JiT architectural idea relevant, or is the real transferable idea just "direct clean-target denoising"?
- Can financial panel structure be represented as patches without creating arbitrary geometry?
- What does "large patch" mean for finance: assets, factors, dates, sectors, or regimes?
- Should sector membership be treated as structure, metadata, or leakage risk?
- Does denoising remove useful idiosyncratic alpha along with noise?
- Can the model explain what it denoised, or does it become another black-box smoother?
- Would a PM care about the denoised representation, or only about the resulting risk-adjusted decision?

---

## Current Decision

Do not start this as an active XP yet.

Use this note as a parked seed while the current mainline is:

1. Internship hunting and application CRM.
2. Packaging the completed [[roadmap]] into external-facing proof.
3. Only then deciding whether JiT finance denoising deserves a formal XP-92.

Upgrade condition:

> Start XP-92 only if there is a 2-3 session window where a small, honest denoising experiment can be completed end to end without displacing internship execution.
