"""The five agents. Each exposes run(case, ...) -> dict and runs alone:
python -m dome.agents.<name> --case <case_id> [--scenario <name>]
"""
from __future__ import annotations

import argparse

from ..case import Case


def cli(step: str, out_file: str, run, extra_args=()):
    """Shared CLI so every agent runs alone from the command line."""
    p = argparse.ArgumentParser(prog=f"dome.agents.{step}")
    p.add_argument("--case", required=True)
    p.add_argument("--scenario", default=None)
    for name, kw in extra_args:
        p.add_argument(name, **kw)
    a = vars(p.parse_args())
    case = Case.open(a.pop("case"), scenario=a.pop("scenario"))
    obj = case.save(out_file, run(case, **a))
    case.log(actor="agent", event="tool_result", step=step, output_file=out_file,
             message=f"{step} run alone from the CLI")
    print(obj.model_dump_json(indent=2))
