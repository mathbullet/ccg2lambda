"""Thin wrapper around the ccg2lambda RTE pipeline.

Calls existing scripts via subprocess, mirroring en/rte_en_mp_any.sh.
No logging here; logging is handled by __main__.py.
"""

import os
import subprocess
import tempfile
from pathlib import Path


def _run(cmd, stdin_text=None, timeout=200, cwd=None, env=None):
    result = subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        env=env,
    )
    return result


def read_candc_dir(project_root):
    loc = project_root / "en" / "candc_location.txt"
    if loc.exists():
        return loc.read_text().strip()
    parser_loc = project_root / "en" / "parser_location.txt"
    if parser_loc.exists():
        for line in parser_loc.read_text().splitlines():
            if line.startswith("candc:"):
                return line.split(":", 1)[1]
    return None


def tokenize(sentences, project_root):
    raw = "\n".join(sentences) + "\n"
    sed_file = project_root / "en" / "tokenizer.sed"
    r = _run(["sed", "-f", str(sed_file)], stdin_text=raw)
    lines = r.stdout.replace(" _ ", "_").rstrip().splitlines()
    return [line.rstrip() for line in lines]


def parse_depccg(tokenized_lines, candc_dir, output_path):
    env = os.environ.copy()
    if candc_dir:
        env["CANDC"] = candc_dir
    text = "\n".join(tokenized_lines) + "\n"
    r = _run(
        ["depccg_en", "--input-format", "raw", "--annotator", "candc", "--format", "jigg_xml"],
        stdin_text=text,
        env=env,
    )
    output_path.write_text(r.stdout)
    return r.returncode == 0, r.stderr


def parse_candc(tokenized_lines, candc_dir, output_path, project_root):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tok", delete=False) as f:
        f.write("\n".join(tokenized_lines) + "\n")
        tok_path = f.name
    try:
        candc_xml = output_path.with_suffix(".candc.xml")
        r = _run([
            f"{candc_dir}/bin/candc",
            "--models", f"{candc_dir}/models",
            "--candc-printer", "xml",
            "--input", tok_path,
        ])
        candc_xml.write_text(r.stdout)
        r2 = _run(["python", str(project_root / "en" / "candc2transccg.py"), str(candc_xml)])
        output_path.write_text(r2.stdout)
        return r2.returncode == 0, r.stderr + r2.stderr
    finally:
        os.unlink(tok_path)


def semparse(parsed_xml, templates, output_xml, project_root):
    r = _run(
        [
            "python", str(project_root / "scripts" / "semparse.py"),
            str(parsed_xml),
            str(templates),
            str(output_xml),
            "--arbi-types",
            "--ncores", "1",
        ],
        cwd=str(project_root),
    )
    return r.returncode == 0, r.stderr


def prove(sem_xml, project_root, html_out=None):
    cmd = [
        "python", str(project_root / "scripts" / "prove.py"),
        str(sem_xml),
        "--abduction", "spsa",
    ]
    if html_out:
        cmd.extend(["--graph_out", str(html_out)])
    r = _run(cmd, timeout=200, cwd=str(project_root))
    return r.stdout.strip(), r.stderr
