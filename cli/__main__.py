#!/usr/bin/env python3
"""CLI wrapper for the ccg2lambda RTE pipeline.

Usage:
    python -m cli --input "data/*.json" --output-dir results/ --parser depccg
"""

import argparse
import glob
import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path

from cli.pipeline import (
    read_candc_dir,
    tokenize,
    parse_depccg,
    parse_candc,
    semparse,
    prove,
)

log = logging.getLogger("cli")


def setup_logging(verbose):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def load_input(path):
    with open(path) as f:
        return json.load(f)


def process_one(item, parser_name, templates, project_root, candc_dir, work_dir):
    premises = item["premise"]
    hypothesis = item["hypothesis"]
    sentences = premises + [hypothesis]

    log.debug("tokenizing %d sentences", len(sentences))
    tokenized = tokenize(sentences, project_root)

    parsed_xml = work_dir / "parsed.jigg.xml"
    log.debug("parsing with %s", parser_name)
    if parser_name == "depccg":
        ok, err = parse_depccg(tokenized, candc_dir, parsed_xml)
    elif parser_name == "candc":
        ok, err = parse_candc(tokenized, candc_dir, parsed_xml, project_root)
    else:
        log.error("unknown parser: %s", parser_name)
        return "error"
    if not ok:
        log.warning("parse failed: %s", err.strip().split("\n")[-1] if err.strip() else "(no output)")

    sem_xml = work_dir / "sem.xml"
    log.debug("semantic parsing")
    ok, err = semparse(parsed_xml, templates, sem_xml, project_root)
    if not ok:
        log.warning("semparse failed: %s", err.strip().split("\n")[-1] if err.strip() else "(no output)")

    html_out = work_dir / "proof.html"
    log.debug("proving")
    prediction, err = prove(sem_xml, project_root, html_out)
    if not prediction:
        prediction = "unknown"

    return prediction


def main():
    p = argparse.ArgumentParser(description="ccg2lambda RTE pipeline CLI")
    p.add_argument("--input", required=True, help="glob pattern for input JSON files")
    p.add_argument("--output-dir", required=True, help="directory for output JSON files")
    p.add_argument("--parser", default="depccg", choices=["depccg", "candc"])
    p.add_argument("--templates", default=None, help="semantic templates YAML (default: en/semantic_templates_en_event.yaml)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    setup_logging(args.verbose)

    project_root = Path(__file__).resolve().parent.parent
    candc_dir = read_candc_dir(project_root)
    templates = Path(args.templates) if args.templates else project_root / "en" / "semantic_templates_en_event.yaml"
    if not templates.exists():
        log.error("templates not found: %s", templates)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_path = Path(args.input)
    if input_path.is_dir():
        input_files = sorted(str(p) for p in input_path.glob("*.json"))
    else:
        input_files = sorted(glob.glob(args.input))
    if not input_files:
        log.error("no input files matched: %s", args.input)
        sys.exit(1)

    log.info("processing %d file(s) with %s parser", len(input_files), args.parser)

    results = []
    for fpath in input_files:
        fname = Path(fpath).stem
        log.info("[%s] start", fname)
        item = load_input(fpath)

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            prediction = process_one(item, args.parser, templates, project_root, candc_dir, work_dir)

        result = {
            "premise": item["premise"],
            "hypothesis": item["hypothesis"],
            "label": item.get("label"),
            "prediction": prediction,
        }
        results.append(result)

        out_path = output_dir / f"{fname}.json"
        with open(out_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        match = prediction == item.get("label")
        log.info("[%s] prediction=%s label=%s %s", fname, prediction, item.get("label"), "OK" if match else "MISS")

    total = len(results)
    correct = sum(1 for r in results if r["prediction"] == r.get("label"))
    log.info("done: %d/%d correct (%.1f%%)", correct, total, 100 * correct / total if total else 0)


if __name__ == "__main__":
    main()
