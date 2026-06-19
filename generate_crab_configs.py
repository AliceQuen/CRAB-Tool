#!/usr/bin/env python3
"""Generate CRAB configs from one template and local dataset lists."""

from __future__ import annotations

import argparse
import glob
import os
import re
from pathlib import Path

from crab_config_literals import render_template

MANIFEST_NAME = "generated_crab_configs.txt"

LUMI_MASK_BY_YEAR = {
    "2022": "/eos/user/c/cmsdqm/www/CAF/certification/Collisions22/Cert_Collisions2022_355100_362760_Muon.json",
    "2023": "/eos/user/c/cmsdqm/www/CAF/certification/Collisions23/Cert_Collisions2023_366442_370790_Muon.json",
    "2024": "/eos/user/c/cmsdqm/www/CAF/certification/Collisions24/Cert_Collisions2024_378981_386951_Muon.json",
    "2025": "/eos/user/c/cmsdqm/www/CAF/certification/Collisions25/Cert_Collisions2025_391658_398903_Muon.json",
}


class HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    """Help formatter with defaults and preserved line breaks."""


def ensure_cmssw_env() -> None:
    required = ("CMSSW_BASE", "CMSSW_RELEASE_BASE", "SCRAM_ARCH")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        missing_names = ", ".join(missing)
        raise RuntimeError(
            "CMSSW environment is not active. "
            f"Missing {missing_names}. Run 'cmsenv' first."
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate CRAB configuration files from one template and local dataset lists.",
        formatter_class=HelpFormatter,
        epilog=(
            "Examples:\n"
            "  generate_crab_configs.py\n"
            "  generate_crab_configs.py --lists RundataList_2025.txt --units-per-job 20\n"
            "  generate_crab_configs.py --template crab3_template.py --manifest my_manifest.txt\n"
        ),
    )
    parser.add_argument(
        "--lists",
        nargs="*",
        default=[],
        help="Dataset list files. If omitted, use local RundataList_*.txt files.",
    )
    parser.add_argument(
        "--template",
        default="crab3_template.py",
        help="Base CRAB configuration template to render for each dataset.",
    )
    parser.add_argument(
        "--manifest",
        default=MANIFEST_NAME,
        help="Output manifest file that records all generated config paths.",
    )
    parser.add_argument(
        "--prefix",
        default="crab3_refactor",
        help="Request-name prefix used for generated CRAB configs.",
    )
    parser.add_argument(
        "--analysis-mode",
        default="JpsiJpsiPhi",
        help="Value injected into the CMSSW analysisMode parameter.",
    )
    parser.add_argument(
        "--units-per-job",
        type=int,
        default=20,
        help="LumiBased splitting size written into each generated config.",
    )
    parser.add_argument(
        "--storage-site",
        default="T3_CH_CERNBOX",
        help="Target CRAB storage site for generated configs.",
    )
    parser.add_argument(
        "--outlfn",
        default="/store/user/chiw/JpsiJpsiPhi/rootNtuple/",
        help="Base output LFN directory written into generated configs.",
    )
    return parser.parse_args(argv)


def sanitize_token(token: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", token)


def build_request_name(prefix: str, analysis_mode: str, task_token: str) -> str:
    analysis_token = sanitize_token(analysis_mode)
    prefix_token = sanitize_token(prefix)

    if analysis_token and analysis_token.lower() in prefix_token.lower():
        request_name = f"{prefix}_{task_token}"
    else:
        request_name = f"{prefix}_{analysis_token}_{task_token}"
    return request_name[:95]


def dataset_to_meta(dataset: str) -> dict[str, str]:
    parts = dataset.strip().split("/")
    if len(parts) < 4:
        raise ValueError(f"Invalid dataset format: {dataset}")

    primary = parts[1]
    processed = parts[2]
    tier = parts[3]

    era_match = re.search(r"Run(20\d{2}[A-Z]+)", processed)
    if not era_match:
        raise ValueError(f"Cannot parse era from processed dataset: {processed}")
    era = f"Run{era_match.group(1)}"

    year_match = re.search(r"Run(20\d{2})", processed)
    if not year_match:
        raise ValueError(f"Cannot parse year from processed dataset: {processed}")
    year = year_match.group(1)

    campaign = processed.replace("-PromptReco-", "")
    stream_match = re.search(r"(\d+)$", primary)
    stream_idx = stream_match.group(1) if stream_match else "X"

    task_token = sanitize_token(f"{stream_idx}_{campaign}_{tier}")

    return {
        "dataset": dataset,
        "primary": primary,
        "processed": processed,
        "tier": tier,
        "era": era,
        "year": year,
        "campaign": campaign,
        "stream_idx": stream_idx,
        "task_token": task_token,
    }


def pick_lists(explicit_lists: list[str]) -> list[Path]:
    if explicit_lists:
        return [Path(path) for path in explicit_lists]
    return [Path(path) for path in sorted(glob.glob("RundataList_*.txt"))]


def cleanup_previous_configs(manifest_path: Path) -> None:
    if not manifest_path.exists():
        return
    for raw in manifest_path.read_text().splitlines():
        cfg = Path(raw.strip())
        if cfg.name and cfg.exists():
            cfg.unlink()


def main() -> int:
    args = parse_args()
    ensure_cmssw_env()

    template_path = Path(args.template)
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    template_text = template_path.read_text()

    manifest_path = Path(args.manifest)
    cleanup_previous_configs(manifest_path)

    list_paths = pick_lists(args.lists)
    if not list_paths:
        raise RuntimeError("No dataset list files found.")

    generated_cfgs: list[str] = []

    for list_path in list_paths:
        if not list_path.exists():
            raise FileNotFoundError(f"Dataset list not found: {list_path}")

        for raw in list_path.read_text().splitlines():
            dataset = raw.strip()
            if not dataset or dataset.startswith("#"):
                continue

            meta = dataset_to_meta(dataset)
            year = meta["year"]
            if year not in LUMI_MASK_BY_YEAR:
                raise ValueError(f"No lumi mask configured for year {year} (dataset={dataset})")

            request_name = build_request_name(args.prefix, args.analysis_mode, meta["task_token"])
            output_file = f"mymultilep_{meta['campaign']}.root"

            replacements = {
                "__REQUEST_NAME__": request_name,
                "__OUTPUT_FILE__": output_file,
                "__ERA__": meta["era"],
                "__ANALYSIS_MODE__": args.analysis_mode,
                "__DATASET__": dataset,
                "__UNITS_PER_JOB__": str(args.units_per_job),
                "__LUMI_MASK__": LUMI_MASK_BY_YEAR[year],
                "__OUTLFN__": args.outlfn,
                "__OUTPUT_TAG__": request_name,
                "__STORAGE_SITE__": args.storage_site,
            }

            cfg_name = f"{request_name}.py"
            Path(cfg_name).write_text(render_template(template_text, replacements))
            generated_cfgs.append(cfg_name)

    manifest_path.write_text("\n".join(generated_cfgs) + "\n")

    print(f"Generated {len(generated_cfgs)} CRAB config files")
    print(f"Manifest: {manifest_path}")
    if generated_cfgs:
        print("First 5 configs:")
        for cfg in generated_cfgs[:5]:
            print(f"  - {cfg}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
