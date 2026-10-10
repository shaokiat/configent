"""Configent CLI: ingest and eval commands."""
import asyncio
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

app = typer.Typer(help="Configent — config-driven enterprise AI assistant platform")
console = Console()

_REPO_ROOT = Path(__file__).parents[3]


def _print_report(report, failed: list[dict]) -> None:
    """The accounting both modes print: every file in the folder, in exactly one column."""
    table = Table(title="Corpus folder")
    table.add_column("Extension", style="bold")
    table.add_column("Files", justify="right")
    for ext, n in report.extensions.items():
        table.add_row(ext, str(n))
    table.add_row("will ingest", str(len(report.ingest)), style="green")
    table.add_row("will skip: unsupported", str(len(report.unsupported)), style="yellow")
    table.add_row("will fail", str(len(failed)), style="red")
    console.print(table)
    for f in report.unsupported:
        console.print(f"  [yellow]skip (unsupported)[/yellow] {f}")
    for f in failed:
        console.print(f"  [red]fail[/red] {f['path']}: {f['reason']}")
    for f in report.stubs:
        console.print(f"  [yellow]stub (under 50 tokens)[/yellow] {f}")
    for paths in report.duplicates:
        console.print(f"  [yellow]same text in[/yellow] {', '.join(paths)}")
    console.print(
        f"Full rebuild: {report.chunks} chunks, {report.tokens:,} embedding tokens, "
        f"~${report.cost_usd:.4f}, up to ~{report.seconds // 60} min {report.seconds % 60} s "
        f"on the free tier"
    )


@app.command()
def ingest(
    client: str = typer.Option(..., "--client", "-c", help="client_id to ingest"),
    force: bool = typer.Option(False, "--force", help="Re-ingest even unchanged docs"),
    check: bool = typer.Option(
        False, "--check", help="Report what ingest would do; embed and write nothing"
    ),
):
    """Bring a client's index in line with its corpus folder and `corpus` config."""

    async def _run():
        import os

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.agent.engines import ENGINES
        from app.config.registry import ConfigRegistry

        registry = ConfigRegistry(config_dir=_REPO_ROOT / "config")
        try:
            cfg = registry.get(client)
        except KeyError:
            console.print(f"[red]Unknown client_id: {client!r}[/red]")
            raise typer.Exit(1)

        engine = ENGINES[cfg.agent.engine]
        if check:
            report = engine.check(cfg, _REPO_ROOT)
            _print_report(report, report.failed)
            raise typer.Exit(1 if report.failed else 0)

        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/configent",
        )
        engine = create_async_engine(db_url, echo=False)
        AsyncSession = async_sessionmaker(engine, expire_on_commit=False)

        console.print(f"[bold]Ingesting corpus for [cyan]{client}[/cyan]...[/bold]")

        async with AsyncSession() as db:
            stats = await engine.ingest(db, cfg, _REPO_ROOT, force=force)

        await engine.dispose()

        _print_report(stats["report"], stats["failed"])
        table = Table(title=f"Ingest summary: {client}")
        table.add_column("Metric", style="bold")
        table.add_column("Count", justify="right")
        table.add_row("Documents added", str(stats["added"]))
        table.add_row("Documents replaced", str(stats["replaced"]))
        table.add_row("Documents skipped (unchanged)", str(stats["skipped"]))
        table.add_row("Documents removed (file deleted)", str(stats["removed"]))
        table.add_row("Total chunks upserted", str(stats["total_chunks"]))
        console.print(table)
        if stats["failed"]:
            raise typer.Exit(1)  # so a script or CI step notices

    asyncio.run(_run())


if __name__ == "__main__":
    app()
