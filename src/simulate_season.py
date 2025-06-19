import pandas as pd, numpy as np, requests, random, os, datetime as dt
from icalendar import Calendar

# ------------------ CONFIG ------------------ #
HFA      = 65          # home-field advantage in Elo pts
DRAW_P   = 0.24        # baseline draw probability
N_RUNS   = 50000       # Monte-Carlo loops
ICS_URL  = "https://fixtures.ecal.com/pl-all.ics"   # official PL calendar feed
SEED_CSV = "data/elo_seed_2025.csv"                 # fallback Elo ratings
# -------------------------------------------- #

# 1) Fetch fixtures ------------------------------------------------------- #
try:
    ics_bytes = requests.get(ICS_URL, timeout=30).content
    cal = Calendar.from_ical(ics_bytes)
    fixtures = []
    for ev in cal.walk('vevent'):
        summary = str(ev.get('summary'))
        if ' v ' in summary:
            home, away = summary.split(' v ')
            fixtures.append((home.strip(), away.strip()))
except Exception as e:
    raise RuntimeError(f"Could not fetch or parse ICS feed: {e}")

if len(fixtures) != 380:
    raise ValueError(f"Expected 380 fixtures, got {len(fixtures)} – check the feed URL.")

# 2) Load Elo ratings ----------------------------------------------------- #
elo_df = pd.read_csv(SEED_CSV)
elo = dict(zip(elo_df["Team"], elo_df["Elo"]))
if len(elo) != 20:
    raise ValueError("Elo CSV should contain 20 teams.")

def outcome_probs(home, away):
    diff = (elo[home] + HFA) - elo[away]
    p_home = 1 / (1 + 10 ** (-diff / 400))
    p_draw = DRAW_P
    p_away = max(0, 1 - p_home - p_draw)
    if p_away == 0:               # re-scale if rounding hit zero
        p_draw = 1 - p_home
    return p_home, p_draw, p_away

# 3) Monte-Carlo simulation ---------------------------------------------- #
totals = {t: [] for t in elo}
for _ in range(N_RUNS):
    pts = dict.fromkeys(elo, 0)
    for home, away in fixtures:
        ph, pd, pa = outcome_probs(home, away)
        r = random.random()
        if r < ph:
            pts[home] += 3
        elif r < ph + pd:
            pts[home] += 1
            pts[away] += 1
        else:
            pts[away] += 3
    for t in pts:
        totals[t].append(pts[t])

# 4) Summarise results ---------------------------------------------------- #
out = pd.DataFrame({
    "Team": totals.keys(),
    "MeanPts": [np.mean(t) for t in totals.values()],
    "StdPts":  [np.std(t)  for t in totals.values()],
    "Title%":  [np.mean(np.array(t) >= 85)  * 100 for t in totals.values()],
    "Top4%":   [np.mean(np.array(t) >= 72)  * 100 for t in totals.values()],
    "Releg%":  [np.mean(np.array(t) <= 38)  * 100 for t in totals.values()],
}).sort_values("MeanPts", ascending=False).round(2)

stamp = dt.datetime.utcnow().strftime("%Y%m%d_%H%M")
os.makedirs("results", exist_ok=True)
out.to_csv(f"results/table_{stamp}.csv", index=False)
out.to_csv("results/latest_table.csv", index=False)

# 5) Optional bar chart --------------------------------------------------- #
try:
    import matplotlib.pyplot as plt
    plt.figure(figsize=(5, 7))
    plt.barh(out["Team"][::-1], out["MeanPts"][::-1])
    plt.title("PL 2025/26 – Mean Points (50k sims)")
    plt.xlabel("Points")
    plt.tight_layout()
    plt.savefig("results/latest_table.png", dpi=150)
except Exception as e:
    print("Chart skipped:", e)

cat > .github/workflows/weekly-sim.yml <<'EOF'
name: Weekly PL Simulation

on:
  schedule:
    - cron: '0 7 * * 1'       # 07:00 UTC every Monday
  workflow_dispatch:          # manual “Run workflow” button

jobs:
  run-sim:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run Monte-Carlo engine
        run: python src/simulate_season.py

      - name: Commit refreshed outputs
        run: |
          git config --global user.email "actions@github.com"
          git config --global user.name  "GH Action"
          git add results/* || true
          git commit -m "Auto-update weekly simulation" || echo "No changes"
          git push
EOF

