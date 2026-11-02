"""Render the report figure from the checked process-mining results."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    reports = Path("reports")
    data = json.loads((reports / "process-mining.json").read_text())
    recent = next(r["statistics"] for r in data if "findings" in r["file"])
    cohort = recent["HE_Fail_cohort"]
    outcomes = dict(cohort["next_observed_outcomes"])
    outcomes["No next result in window"] = cohort["no_next_in_log"]
    pairs = sorted(outcomes.items(), key=lambda v: -v[1])
    top = pairs[:7]
    if len(pairs) > 7:
        top.append(("Other recorded outcomes", sum(n for _, n in pairs[7:])))
    fig, ax = plt.subplots(figsize=(10, 5.6), layout="constrained")
    labels, values = zip(*top)
    bars = ax.barh(labels[::-1], values[::-1], color=["#d4953b" if "No next" in l else "#267d92" for l in labels[::-1]])
    ax.bar_label(bars, labels=[f"{n:,} ({100*n/cohort['total_events']:.1f}%)" for n in values[::-1]], padding=5, fontsize=10)
    ax.set_xlim(0, max(values) * 1.36)
    ax.set_xlabel("Number of HE_Fail events (one result group per license and timestamp)")
    ax.set_title(f"What follows a recorded HE_Fail result?\nBoston, 2022–2025 · {cohort['total_events']:,} HE_Fail events", loc="left", pad=18)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_axisbelow(True)
    ax.xaxis.grid(alpha=.2)
    fig.text(.01, -.055,
             "Next observed result on the same license. Administrative outcomes are retained.\n"
             "No next result is observation-window truncation or missing follow-up, not proof that no follow-up occurred.",
             fontsize=9, color="#454545")
    fig.savefig(reports / "next-observed-outcome.png", dpi=180, bbox_inches="tight", facecolor="white")


if __name__ == "__main__":
    main()
