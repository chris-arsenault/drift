"""CLI entry point for the semantic drift detection pipeline."""

import time
from pathlib import Path

import click

_D = ".drift-audit/semantic"
_odir = click.option(
    "--output-dir", type=click.Path(), default=_D, help="Directory for pipeline artifacts."
)


def _run_stage(label: str, fn) -> None:
    click.echo(f"Running {label}...", err=True)
    fn()
    click.echo("Done.", err=True)


@click.group()
def cli() -> None:
    """Semantic drift detection pipeline."""


@cli.command()
@_odir
@click.option("--project", type=click.Path(exists=True), default=None, help="Project root (for CSS extraction).")
@click.option("--threshold", type=float, default=0.35)
def run(output_dir: str, project: str | None, threshold: float) -> None:
    """Run the full deterministic pipeline (all stages except extract)."""
    from .callgraph import run as cg
    from .cluster import compute_clusters
    from .depcontext import run as dc
    from .embed import embed_if_available
    from .fingerprint import run as fp
    from .report import generate_report
    from .score import compute_scores
    from .typesig import run as ts

    od = Path(output_dir)
    stages = [
        ("fingerprint", lambda: fp(od)),
        ("typesig", lambda: ts(od)),
        ("callgraph", lambda: cg(od)),
        ("depcontext", lambda: dc(od)),
        ("embed", lambda: embed_if_available(od)),
        ("score", lambda: compute_scores(od, threshold)),
        ("cluster", lambda: compute_clusters(od, threshold)),
    ]

    # CSS stages (only if --project is provided or css-units.json exists)
    if project or (od / "css-units.json").exists():
        from .css_extract import run as css_ext
        from .css_score import run as css_sc

        if project:
            stages.append(("css-extract", lambda: css_ext(Path(project), od)))
        stages.append(("css-score", lambda: css_sc(od)))

    stages.append(("report", lambda: generate_report(od)))
    t_total = time.time()
    for name, fn in stages:
        click.echo(f"[{name}] Starting...", err=True)
        t0 = time.time()
        fn()
        click.echo(f"[{name}] Done in {time.time() - t0:.2f}s", err=True)
    click.echo(f"\nPipeline complete in {time.time() - t_total:.2f}s", err=True)


@cli.command()
@_odir
def fingerprint(output_dir: str) -> None:
    """Compute structural fingerprints."""
    from .fingerprint import run

    _run_stage("fingerprint", lambda: run(Path(output_dir)))


@cli.command()
@_odir
def typesig(output_dir: str) -> None:
    """Normalize type signatures."""
    from .typesig import run

    _run_stage("typesig", lambda: run(Path(output_dir)))


@cli.command()
@_odir
def callgraph(output_dir: str) -> None:
    """Compute call graph vectors."""
    from .callgraph import run

    _run_stage("callgraph", lambda: run(Path(output_dir)))


@cli.command()
@_odir
def depcontext(output_dir: str) -> None:
    """Compute dependency context."""
    from .depcontext import run

    _run_stage("depcontext", lambda: run(Path(output_dir)))


@cli.command()
@_odir
@click.option("--ollama-url", type=str, default=None, help="Ollama API URL (uses built-in TF-IDF if omitted).")
@click.option("--model", type=str, default="nomic-embed-text")
def embed(output_dir: str, ollama_url: str | None, model: str) -> None:
    """Embed purpose statements. Uses built-in TF-IDF by default, Ollama if --ollama-url is set."""
    from .embed import embed_purposes

    _run_stage("embed", lambda: embed_purposes(Path(output_dir), ollama_url, model))


@cli.command("css-extract")
@_odir
@click.option("--project", type=click.Path(exists=True), required=True, help="Project root to scan for CSS files.")
def css_extract(output_dir: str, project: str) -> None:
    """Extract CSS units from .css files."""
    from .css_extract import run

    _run_stage("css-extract", lambda: run(Path(project), Path(output_dir)))


@cli.command("css-score")
@_odir
@click.option("--threshold", type=float, default=0.40)
def css_score(output_dir: str, threshold: float) -> None:
    """Score and cluster CSS file pairs."""
    from .css_score import run

    _run_stage("css-score", lambda: run(Path(output_dir), threshold))


@cli.command()
@_odir
@click.option("--threshold", type=float, default=0.35)
def score(output_dir: str, threshold: float) -> None:
    """Compute pairwise similarity scores."""
    from .score import compute_scores

    _run_stage("score", lambda: compute_scores(Path(output_dir), threshold))


@cli.command()
@_odir
@click.option("--threshold", type=float, default=0.35)
def cluster(output_dir: str, threshold: float) -> None:
    """Cluster similar units."""
    from .cluster import compute_clusters

    _run_stage("cluster", lambda: compute_clusters(Path(output_dir), threshold))


@cli.command()
@_odir
@click.option("--manifest", type=click.Path(), default=None)
def report(output_dir: str, manifest: str | None) -> None:
    """Generate report, manifest, and atlas."""
    from .report import generate_report

    od = Path(output_dir)
    mp = Path(manifest) if manifest else None
    _run_stage(
        "report", lambda: generate_report(od, manifest_path=mp) if mp else generate_report(od)
    )


# -- ingest -----------------------------------------------------------------


@cli.command("ingest-purposes")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True))
@_odir
def ingest_purposes(file_path: str, output_dir: str) -> None:
    """Ingest purpose statements written by Claude."""
    from .ingest import ingest_purposes as _f

    _f(Path(file_path), Path(output_dir))


@cli.command("ingest-findings")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True))
@_odir
def ingest_findings(file_path: str, output_dir: str) -> None:
    """Ingest findings written by Claude."""
    from .ingest import ingest_findings as _f

    _f(Path(file_path), Path(output_dir))


# -- inspect group ----------------------------------------------------------


@cli.group()
def inspect() -> None:
    """Inspect pipeline artifacts."""


@inspect.command("unit")
@click.argument("unit_id")
@_odir
def inspect_unit(unit_id: str, output_dir: str) -> None:
    """Show full unit metadata."""
    from .inspect_cmd import inspect_unit as _f

    _f(unit_id, Path(output_dir))


@inspect.command("similar")
@click.argument("unit_id")
@click.option("--top", type=int, default=10)
@_odir
def inspect_similar_cmd(unit_id: str, top: int, output_dir: str) -> None:
    """Show most similar units."""
    from .inspect_cmd import inspect_similar

    inspect_similar(unit_id, top, Path(output_dir))


@inspect.command("cluster")
@click.argument("cluster_id")
@_odir
def inspect_cluster_cmd(cluster_id: str, output_dir: str) -> None:
    """Show cluster details."""
    from .inspect_cmd import inspect_cluster

    inspect_cluster(cluster_id, Path(output_dir))


@inspect.command("consumers")
@click.argument("unit_id")
@_odir
def inspect_consumers_cmd(unit_id: str, output_dir: str) -> None:
    """Show who imports this unit."""
    from .inspect_cmd import inspect_consumers

    inspect_consumers(unit_id, Path(output_dir))


@inspect.command("callers")
@click.argument("unit_id")
@_odir
def inspect_callers_cmd(unit_id: str, output_dir: str) -> None:
    """Show who calls this unit."""
    from .inspect_cmd import inspect_callers

    inspect_callers(unit_id, Path(output_dir))


# -- search group -----------------------------------------------------------


@cli.group()
def search() -> None:
    """Search the code unit index."""


@search.command("calls")
@click.argument("unit_id")
@_odir
def search_calls_cmd(unit_id: str, output_dir: str) -> None:
    """Find all units that the given unit calls."""
    from .search_cmd import search_calls

    search_calls(unit_id, Path(output_dir))


@search.command("called-by")
@click.argument("unit_id")
@_odir
def search_called_by_cmd(unit_id: str, output_dir: str) -> None:
    """Find all units that call the given unit."""
    from .search_cmd import search_called_by

    search_called_by(unit_id, Path(output_dir))


@search.command("co-occurs-with")
@click.argument("unit_id")
@_odir
def search_co_occurs_cmd(unit_id: str, output_dir: str) -> None:
    """Find units frequently imported alongside."""
    from .search_cmd import search_co_occurs

    search_co_occurs(unit_id, Path(output_dir))


@search.command("type-like")
@click.argument("unit_id")
@_odir
def search_type_like_cmd(unit_id: str, output_dir: str) -> None:
    """Find units with matching type signatures."""
    from .search_cmd import search_type_like

    search_type_like(unit_id, Path(output_dir))


if __name__ == "__main__":
    cli()
