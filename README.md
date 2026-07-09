# cfb-spread-model

A college football model that predicts **margin of victory** and compares it
against the **market spread** to look for edges. The point of the project is not
the model architecture. It is the validation discipline: every feature is
point-in-time, every test is walk-forward, and the model is graded against the
closing line, not against itself.

## The one rule that matters

A feature for a given game uses only information available **before kickoff.**
That sounds obvious and it is the single most common reason these projects get
thrown out in review. If a Week 8 prediction uses Week 8 through 13 stats, the
backtest looks incredible and means nothing.

`cfb/features.py` enforces this. `tests/test_no_leakage.py` proves it by
corrupting future games and asserting that earlier features do not move. Run the
test before you trust any result.

```
python tests/test_no_leakage.py
```

## How success is measured

The spread is the market's own expected margin, and the closing line is one of
the most efficient predictors in sports. So the bar is not "did the model pick
winners." The bar is:

1. **Mean absolute error vs the closing line.** Can the model's margin beat the
   closing spread's margin error? Hard to do. That is the point.
2. **Closing line value (CLV).** Do the games the model flags as edges move
   toward the model after you would have bet them? CLV is the only repeatable
   proof of skill, so it is the primary metric.
3. **ROI at realistic vig** (-110), as a sanity check, never the headline.

A model that routinely claims 3+ point edges is almost certainly miscalibrated,
not clairvoyant. The honest framing is small, defensible edges measured against
the close.

## Pipeline

```
01_fetch.py        CFBD -> data/raw/        (schedule, lines, advanced stats)
02_build_features  raw -> data/processed/   (point-in-time, Week 4+, leak-free)
[next] model       ridge baseline, walk-forward by season/week
[next] backtest    grade edges vs closing line: MAE, CLV, ROI
[next] website     Streamlit demo + analytics hub
```

A regularized linear baseline (ridge / elastic-net on efficiency differentials)
is the right v1 model. It is hard to beat, easy to explain, and far more
defensible to an analytics department than a black box.

## Setup

```
pip install -r requirements.txt
cp .env.example .env        # then paste your free key from collegefootballdata.com/key
python scripts/01_fetch.py 2021 2022 2023 2024
python scripts/02_build_features.py
python tests/test_no_leakage.py
```

## Layout

```
cfb/            feature engine, fetch, config (the importable package)
scripts/        thin CLI steps you run in order
tests/          leakage test + synthetic data generator
data/raw/       cached API pulls (gitignored)
data/processed/ model-ready tables (gitignored)
manual_inputs/  injury ratings and other hand-entered data
outputs/        backtest results, picks, figures
website/        Streamlit app (later)
notebooks/      exploration
```

## Status

- Feature engine: built and leakage-tested.
- Fetch module: written against CFBD's documented schema, run it with your key.
  All CFBD field mapping lives in `cfb/fetch_data.py`, so if a field name is off
  you fix it in one place.
- Model, backtest, website: next.

## Design decisions worth knowing

- **Week 4+ only in v1.** Weeks 1 to 3 are too noisy. Even at Week 4 a team has
  only 3 prior games, so features are **shrunk** toward a fixed league baseline
  (`SHRINK_K` in config). Small samples get pulled toward average instead of
  trusted.
- **Coaching big-game splits are website content, not v1 features.** A coach has
  maybe 2 to 4 conference title games. "3-1 ATS after a bye" is noise at N=4,
  and most coaching quality already shows up in the efficiency numbers. Keep
  tenure and play-caller continuity if anything; treat the splits as storytelling.
- **Injuries start minimal.** A QB availability tier and an OL-continuity count
  move margins. Rating seven position groups for every team every week is a lot
  of subjective labor that has to be logged before kickoff to stay leak-free.
  Prove you will keep it current before expanding it.

## Demo app

`python3 -m streamlit run app.py` -- split-screen matchup explorer: point-in-time team stats, model prediction vs Bovada open/close, cover probability with calibration caveats, and the 2026 schedule with a preseason talent prior. Requires the data files built by the notebooks.
