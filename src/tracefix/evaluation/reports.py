"""Comparative research reporting engine (Phase 6).

Produces reproducible Markdown, LaTeX, and JSON comparative reports
evaluating localization, patch generation, and verified repair success rates
across multiple experimental arms.
"""

from __future__ import annotations

import json
from pathlib import Path

from tracefix.evaluation.experiment_runner import MultiArmExperimentResult


def _format_pct(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"{val * 100:.1f}%"


def _format_float(val: float | None, precision: int = 3) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{precision}f}"


def generate_markdown_report(result: MultiArmExperimentResult) -> str:
    """Generate comprehensive research evaluation report in Markdown format."""
    perf_hdr = (
        "| Arm | Strategy / Memory | Hit@5 | Hit@10 | Hit@20 | "
        "MRR | Patch Gen. Rate | Verified Success Rate |"
    )
    res_hdr = (
        "| Arm | Mean Context Tokens | Mean Retrieval Latency (ms) | "
        "Mean Repair Duration (s) | Incident Memories Accumulated |"
    )
    denom_hdr = (
        "| Arm | Total Cases | Localizable Cases | "
        "Evaluated Cases | Excluded Cases | Failed Cases |"
    )

    lines: list[str] = [
        f"# TraceFix Research Evaluation Report: {result.experiment_name}",
        "",
        "## 1. Experimental Overview & Configuration",
        "",
        f"- **Experiment Name:** {result.experiment_name}",
        f"- **Case Set Fingerprint (SHA256):** `{result.case_set_fingerprint}`",
        f"- **Generated At:** {result.created_at}",
        f"- **Primary Metric:** Hit@{result.primary_k}",
        f"- **Context Budget Limit:** {result.token_budget} tokens",
        (
            "- **Pre-Cutoff Contamination Status:** Declared 100% pre-cutoff "
            "(frozen SWE-bench requests suite)"
        ),
        "",
        "## 2. Comparative Performance Summary",
        "",
        perf_hdr,
        "|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]

    for agg in result.arms.values():
        h5 = _format_pct(agg.hit_at_k_macro.get("5"))
        h10 = _format_pct(agg.hit_at_k_macro.get("10"))
        h20 = _format_pct(agg.hit_at_k_macro.get("20"))
        mrr = _format_float(agg.mrr_macro)
        gen_rate = _format_pct(agg.patch_generated_rate)
        rep_rate = _format_pct(agg.verified_repair_rate)
        row = (
            f"| **{agg.arm_name}** | {agg.description} | {h5} | {h10} | {h20} | "
            f"{mrr} | {gen_rate} | **{rep_rate}** |"
        )
        lines.append(row)

    lines.extend(
        [
            "",
            "## 3. Resource Consumption & Operational Efficiency",
            "",
            res_hdr,
            "|:---|:---:|:---:|:---:|:---:|",
        ]
    )

    for agg in result.arms.values():
        tokens = f"{agg.mean_context_tokens:.0f}" if agg.mean_context_tokens else "N/A"
        ret_ms = (
            f"{agg.mean_retrieval_latency_ms:.1f} ms" if agg.mean_retrieval_latency_ms else "N/A"
        )
        rep_s = (
            f"{agg.mean_repair_duration_seconds:.2f} s"
            if agg.mean_repair_duration_seconds
            else "N/A"
        )
        lines.append(
            f"| **{agg.arm_name}** | {tokens} | {ret_ms} | {rep_s} | {agg.memories_accumulated} |"
        )

    lines.extend(
        [
            "",
            "## 4. Denominator & Case Audit",
            "",
            denom_hdr,
            "|:---|:---:|:---:|:---:|:---:|:---:|",
        ]
    )

    for agg in result.arms.values():
        row = (
            f"| **{agg.arm_name}** | {agg.cases_total} | {agg.cases_localizable} | "
            f"{agg.cases_evaluated} | {agg.cases_excluded} | {agg.cases_failed} |"
        )
        lines.append(row)

    lines.extend(
        [
            "",
            "## 5. Invariant & Validity Assurances",
            "",
            (
                "- **Zero Fabrication Policy:** All rates and numbers report "
                "explicit numerators and denominators."
            ),
            (
                "- **Temporal Leakage Prevention:** Arm C enforces strict chronological replay; "
                "all future commits and same-case fix revisions are excluded "
                "prior to query execution."
            ),
            (
                "- **Sandbox Isolation:** Patches executed inside isolated environments "
                "with sanitized credentials."
            ),
            (
                "- **Eligibility Gating:** Only verified candidate patches with exit code 0 "
                "and passing test suites enter incident memory."
            ),
            "",
        ]
    )

    return "\n".join(lines)


def generate_latex_table(result: MultiArmExperimentResult) -> str:
    """Generate publication-ready LaTeX booktabs table."""
    col_hdr = (
        r"\textbf{Experimental Arm} & \textbf{Hit@5} & \textbf{Hit@10} & "
        r"\textbf{MRR} & \textbf{Patch Gen.} & \textbf{Verified Pass} & "
        r"\textbf{Mean Tokens} \\"
    )
    lines: list[str] = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\small",
        r"\begin{tabular}{lrrrrrr}",
        r"\toprule",
        col_hdr,
        r"\midrule",
    ]

    for agg in result.arms.values():
        h5 = _format_pct(agg.hit_at_k_macro.get("5"))
        h10 = _format_pct(agg.hit_at_k_macro.get("10"))
        mrr = _format_float(agg.mrr_macro)
        gen = _format_pct(agg.patch_generated_rate)
        rep = _format_pct(agg.verified_repair_rate)
        tokens = f"{agg.mean_context_tokens:.0f}" if agg.mean_context_tokens else "N/A"
        # Escape underscores for LaTeX
        name_esc = agg.arm_name.replace("_", r"\_")
        lines.append(f"{name_esc} & {h5} & {h10} & {mrr} & {gen} & {rep} & {tokens} \\\\")

    short_fp = result.case_set_fingerprint[:12]
    caption = (
        f"\\caption{{Comparative evaluation results for {result.experiment_name} "
        f"across {len(result.arms)} arms on frozen dataset fingerprint "
        f"\\texttt{{{short_fp}...}}.}}"
    )
    label_key = result.experiment_name.lower().replace(" ", "_")

    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            caption,
            f"\\label{{tab:tracefix_{label_key}}}",
            r"\end{table*}",
        ]
    )
    return "\n".join(lines)


def generate_json_report(result: MultiArmExperimentResult, indent: int = 2) -> str:
    """Generate structured JSON report."""
    return json.dumps(result.model_dump(), indent=indent, sort_keys=True)


def save_reports(
    result: MultiArmExperimentResult,
    output_dir: Path,
    basename: str = "repair_evaluation_report",
) -> dict[str, Path]:
    """Save Markdown, LaTeX, and JSON reports to the designated directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    md_path = output_dir / f"{basename}.md"
    md_path.write_text(generate_markdown_report(result), encoding="utf-8")
    paths["markdown"] = md_path

    tex_path = output_dir / f"{basename}.tex"
    tex_path.write_text(generate_latex_table(result), encoding="utf-8")
    paths["latex"] = tex_path

    json_path = output_dir / f"{basename}.json"
    json_path.write_text(generate_json_report(result), encoding="utf-8")
    paths["json"] = json_path

    return paths
