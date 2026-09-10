"""Generate an original synthetic paper and run the offline generation/QA pipeline."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_pipeline import build_fixture, structural, content, write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output-dir", type=Path, default=Path("tmp/demo"))
args = parser.parse_args()
if args.output_dir.exists():
    parser.error("output directory already exists; choose a fresh path")
args.output_dir.mkdir(parents=True)
config, generation = build_fixture(args.output_dir.resolve())
write_json(args.output_dir / "generation-report.json", generation)
if not generation["written"]:
    raise SystemExit("Demo generation failed; inspect generation-report.json")
for name, check in (("structure", structural.qa_paper), ("content", content.qa_paper)):
    report = check(config)
    write_json(args.output_dir / f"{name}-report.json", report)
    if report["errors"] or report["warnings"]:
        raise SystemExit(f"Demo QA failed: {report}")
print(f"PASS: {generation['output_pages']} bilingual pages; {config['output']}")
