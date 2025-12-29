"""Command-line interface for visual-cataloguer."""

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from cataloguer import __version__
from cataloguer.database.models import Database
from cataloguer.processor.pipeline import ProcessingPipeline

console = Console()


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """Visual Cataloguer - Batch catalogue physical collections."""
    pass


@main.command()
@click.option(
    "--input-dir",
    "-i",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Input directory (scans recursively for images)",
)
@click.option(
    "--database",
    "-d",
    type=click.Path(path_type=Path),
    default="collection.db",
    help="Path to SQLite database (default: collection.db)",
)
@click.option(
    "--done-dir",
    type=click.Path(path_type=Path),
    help="Directory to move processed files to",
)
@click.option(
    "--resume/--no-resume",
    default=True,
    help="Skip already-processed files (default: true)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be processed without executing",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Verbose output",
)
def process(
    input_dir: Path,
    database: Path,
    done_dir: Path | None,
    resume: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Process images from input directory (including subdirectories)."""
    console.print(f"[bold]Visual Cataloguer v{__version__}[/bold]")
    console.print("=" * 40)

    # Initialize database and pipeline
    db = Database(database)
    pipeline = ProcessingPipeline(db)

    # Scan directory recursively
    console.print("\n[bold]Scanning directories...[/bold]")
    files = pipeline.scan_directory(input_dir)

    # Show breakdown by format
    by_ext: dict[str, int] = {}
    for f in files:
        ext = f.path.suffix.lower()
        by_ext[ext] = by_ext.get(ext, 0) + 1
    for ext, count in sorted(by_ext.items()):
        console.print(f"  {ext}: {count} files")

    console.print(f"  [bold]Total: {len(files)} files[/bold]")

    if not files:
        console.print("[yellow]No files found to process[/yellow]")
        return

    # Check for already processed
    if resume:
        skip_count = sum(1 for f in files if db.is_processed(f.file_hash))
        if skip_count > 0:
            console.print(f"  Already processed (will skip): {skip_count} files")
            console.print(f"  New files to process: {len(files) - skip_count} files")

    if dry_run:
        console.print("\n[yellow]Dry run - no files will be processed[/yellow]")
        return

    # Process files
    console.print("\n[bold]Processing...[/bold]")
    results = pipeline.process_files(files, done_dir=done_dir, resume=resume)

    # Show results
    console.print("\n[bold]Processing complete![/bold]")
    console.print("=" * 40)

    # Statistics table
    table = Table(show_header=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    stats = {
        "Total images": len(results),
        "Successful": sum(1 for r in results if r.status == "success"),
        "Skipped": sum(1 for r in results if r.status == "skipped"),
        "Failed": sum(1 for r in results if r.status == "failed"),
        "Items catalogued": sum(r.items_created for r in results),
    }

    for key, value in stats.items():
        table.add_row(key, str(value))

    console.print(table)
    console.print(f"\nDatabase: {database}")

    if done_dir:
        console.print(f"Originals moved to: {done_dir}")

    # Show failures if any
    failures = [r for r in results if r.status == "failed"]
    if failures and verbose:
        console.print("\n[red]Failed files:[/red]")
        for failure in failures[:10]:  # Show first 10
            console.print(f"  {failure.source_path}: {failure.error_message}")
        if len(failures) > 10:
            console.print(f"  ... and {len(failures) - 10} more")


@main.command()
@click.option(
    "--database",
    "-d",
    type=click.Path(exists=True, path_type=Path),
    default="collection.db",
    help="Path to SQLite database",
)
def stats(database: Path) -> None:
    """Show collection statistics."""
    db = Database(database)
    db_stats = db.get_stats()

    table = Table(title="Collection Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total items", str(db_stats["total_items"]))
    table.add_row("Total boxes", str(db_stats["total_boxes"]))
    table.add_row("Needs review", str(db_stats["needs_review"]))
    table.add_row("eBay listed", str(db_stats["ebay_listed"]))
    table.add_row("Processed files", str(db_stats["processed_files"]))
    table.add_row("Failed files", str(db_stats["failed_files"]))

    console.print(table)


@main.command("list")
@click.option(
    "--database",
    "-d",
    type=click.Path(exists=True, path_type=Path),
    default="collection.db",
    help="Path to SQLite database",
)
@click.option("--boxes", is_flag=True, help="List all boxes")
@click.option("--box", type=str, help="List items in a specific box")
@click.option("--needs-review", is_flag=True, help="List items needing review")
@click.option("--limit", type=int, default=20, help="Maximum items to show")
def list_items(
    database: Path,
    boxes: bool,
    box: str | None,
    needs_review: bool,
    limit: int,
) -> None:
    """List items or boxes in the catalogue."""
    db = Database(database)

    with db.connection() as conn:
        if boxes:
            # List all boxes
            rows = conn.execute(
                """
                SELECT b.box_id, b.label, COUNT(i.item_id) as item_count
                FROM boxes b
                LEFT JOIN items i ON b.box_id = i.box_id
                GROUP BY b.box_id
                ORDER BY b.box_id
                """
            ).fetchall()

            table = Table(title="Boxes")
            table.add_column("Box ID", style="cyan")
            table.add_column("Label", style="white")
            table.add_column("Items", style="green")

            for row in rows:
                table.add_row(row["box_id"], row["label"] or "", str(row["item_count"]))

            console.print(table)

        else:
            # List items
            query = "SELECT item_id, box_id, title_guess, platform_guess, completeness FROM items"
            params: list[str] = []

            if box:
                query += " WHERE box_id = ?"
                params.append(box)
            elif needs_review:
                query += " WHERE needs_review = 1"

            query += f" LIMIT {limit}"
            rows = conn.execute(query, params).fetchall()

            table = Table(title="Items")
            table.add_column("ID", style="cyan")
            table.add_column("Title", style="white")
            table.add_column("Platform", style="yellow")
            table.add_column("Status", style="green")
            table.add_column("Box", style="blue")

            for row in rows:
                table.add_row(
                    str(row["item_id"]),
                    (row["title_guess"] or "Unknown")[:40],
                    row["platform_guess"] or "?",
                    row["completeness"],
                    row["box_id"] or "UNASSIGNED",
                )

            console.print(table)
            console.print(f"\n{len(rows)} items shown. Use --limit to show more.")


@main.command()
@click.argument("query")
@click.option(
    "--database",
    "-d",
    type=click.Path(exists=True, path_type=Path),
    default="collection.db",
    help="Path to SQLite database",
)
@click.option("--platform", type=str, help="Filter by platform")
@click.option("--box", type=str, help="Filter by box")
@click.option("--limit", type=int, default=20, help="Maximum items to show")
def search(
    query: str,
    database: Path,
    platform: str | None,
    box: str | None,
    limit: int,
) -> None:
    """Search items in the catalogue."""
    db = Database(database)

    with db.connection() as conn:
        sql = """
            SELECT item_id, box_id, title_guess, platform_guess, completeness
            FROM items
            WHERE (title_guess LIKE ? OR ocr_text_raw LIKE ? OR notes LIKE ?)
        """
        params: list[str] = [f"%{query}%", f"%{query}%", f"%{query}%"]

        if platform:
            sql += " AND platform_guess = ?"
            params.append(platform)
        if box:
            sql += " AND box_id = ?"
            params.append(box)

        sql += f" LIMIT {limit}"
        rows = conn.execute(sql, params).fetchall()

        table = Table(title=f'Search results for "{query}"')
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Platform", style="yellow")
        table.add_column("Status", style="green")
        table.add_column("Box", style="blue")

        for row in rows:
            table.add_row(
                str(row["item_id"]),
                (row["title_guess"] or "Unknown")[:40],
                row["platform_guess"] or "?",
                row["completeness"],
                row["box_id"] or "UNASSIGNED",
            )

        console.print(table)
        console.print(f"\n{len(rows)} items found.")


@main.command()
@click.option(
    "--database",
    "-d",
    type=click.Path(exists=True, path_type=Path),
    default="collection.db",
    help="Path to SQLite database",
)
@click.option(
    "--host",
    default="0.0.0.0",
    help="Host to bind to (default: 0.0.0.0)",
)
@click.option(
    "--port",
    "-p",
    default=8000,
    help="Port to bind to (default: 8000)",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development",
)
def serve(database: Path, host: str, port: int, reload: bool) -> None:
    """Start the web interface server."""
    import uvicorn

    from cataloguer.api.deps import configure_database

    # Configure the database path
    configure_database(database.absolute())

    console.print(f"[bold]Visual Cataloguer v{__version__}[/bold]")
    console.print("=" * 40)
    console.print(f"Database: {database.absolute()}")
    console.print(f"Server: http://{host}:{port}")
    console.print("\nPress Ctrl+C to stop")

    uvicorn.run(
        "cataloguer.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
