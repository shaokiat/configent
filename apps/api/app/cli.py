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

_REPO_ROOT = Path(__file__).parents[4]


@app.command()
def ingest(
    client: str = typer.Option(..., "--client", "-c", help="client_id to ingest"),
    force: bool = typer.Option(False, "--force", help="Re-ingest even unchanged docs"),
):
    """Parse, chunk, embed, and upsert corpus documents for a client."""

    async def _run():
        import os

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.config.registry import ConfigRegistry
        from app.ingest import ingest_client

        registry = ConfigRegistry(config_dir=_REPO_ROOT / "config")
        try:
            cfg = registry.get(client)
        except KeyError:
            console.print(f"[red]Unknown client_id: {client!r}[/red]")
            raise typer.Exit(1)

        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/configent",
        )
        engine = create_async_engine(db_url, echo=False)
        AsyncSession = async_sessionmaker(engine, expire_on_commit=False)

        console.print(f"[bold]Ingesting corpus for [cyan]{client}[/cyan]...[/bold]")

        async with AsyncSession() as db:
            stats = await ingest_client(db, cfg, repo_root=_REPO_ROOT, force=force)

        await engine.dispose()

        table = Table(title=f"Ingest summary: {client}")
        table.add_column("Metric", style="bold")
        table.add_column("Count", justify="right")
        table.add_row("Documents added", str(stats["added"]))
        table.add_row("Documents replaced", str(stats["replaced"]))
        table.add_row("Documents skipped (unchanged)", str(stats["skipped"]))
        table.add_row("Total chunks upserted", str(stats["total_chunks"]))
        console.print(table)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
