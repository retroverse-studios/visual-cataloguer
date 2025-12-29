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
    "--input-dir-1",
    type=click.Path(exists=True, path_type=Path),
    help="First input directory (e.g., NEX-3N with .ARW files)",
)
@click.option(
    "--input-dir-2",
    type=click.Path(exists=True, path_type=Path),
    help="Second input directory (e.g., RX100 with .JPG files)",
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
    input_dir_1: Path | None,
    input_dir_2: Path | None,
    database: Path,
    done_dir: Path | None,
    resume: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Process images from input directories."""
    if not input_dir_1 and not input_dir_2:
        console.print("[red]Error:[/red] At least one input directory is required")
        raise SystemExit(1)

    console.print(f"[bold]Visual Cataloguer v{__version__}[/bold]")
    console.print("=" * 40)

    # Initialize database and pipeline
    db = Database(database)
    pipeline = ProcessingPipeline(db)

    # Scan directories
    console.print("\n[bold]Scanning directories...[/bold]")
    files = pipeline.scan_directories(input_dir_1, input_dir_2)

    if input_dir_1:
        arw_count = sum(1 for f in files if f.path.suffix.lower() == ".arw")
        console.print(f"  {input_dir_1.name}: {arw_count} files (.ARW)")
    if input_dir_2:
        jpg_count = sum(1 for f in files if f.path.suffix.lower() in [".jpg", ".jpeg"])
        console.print(f"  {input_dir_2.name}: {jpg_count} files (.JPG)")

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
        for f in failures[:10]:  # Show first 10
            console.print(f"  {f.source_path}: {f.error_message}")
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


if __name__ == "__main__":
    main()
