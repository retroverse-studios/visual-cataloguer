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
    "--ai-identify",
    is_flag=True,
    help="Use AI (Claude/Ollama) to identify all items",
)
@click.option(
    "--ai-fallback",
    is_flag=True,
    help="Use AI only when OCR fails to extract a title",
)
@click.option(
    "--ai-provider",
    type=click.Choice(["claude", "ollama"]),
    default="claude",
    help="AI provider to use (default: claude)",
)
@click.option(
    "--ai-model",
    type=str,
    default=None,
    help="AI model name (default: claude-3-haiku-20240307 for Claude, llava for Ollama)",
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
    ai_identify: bool,
    ai_fallback: bool,
    ai_provider: str,
    ai_model: str | None,
    verbose: bool,
) -> None:
    """Process images from input directory (including subdirectories)."""
    console.print(f"[bold]Visual Cataloguer v{__version__}[/bold]")
    console.print("=" * 40)

    # Determine AI mode
    if ai_identify:
        ai_mode = "all"
    elif ai_fallback:
        ai_mode = "fallback"
    else:
        ai_mode = "none"

    # Initialize identifier if AI is enabled
    identifier = None
    if ai_mode != "none":
        from cataloguer.processor.identifier import ItemIdentifier

        try:
            identifier = ItemIdentifier(provider=ai_provider, model=ai_model)
            console.print(f"  AI: {ai_provider} ({identifier.model})")
            console.print(f"  AI mode: {ai_mode}")
        except ValueError as e:
            console.print(f"[red]AI setup failed: {e}[/red]")
            console.print("[yellow]Falling back to OCR-only mode[/yellow]")
            ai_mode = "none"

    # Initialize database and pipeline
    db = Database(database)
    pipeline = ProcessingPipeline(db, identifier=identifier, ai_mode=ai_mode)

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
    table.add_row("Total locations", str(db_stats["total_locations"]))
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
@click.option("--locations", is_flag=True, help="List all locations")
@click.option("--location", type=str, help="List items in a specific location")
@click.option("--needs-review", is_flag=True, help="List items needing review")
@click.option("--unknown", is_flag=True, help="List items with unknown title")
@click.option("--low-confidence", is_flag=True, help="List items with low confidence (<50%)")
@click.option(
    "--item-type",
    type=click.Choice(
        ["game", "console", "controller", "accessory", "peripheral", "book", "vinyl", "cd", "trading_card", "other"]
    ),
    help="Filter by item type",
)
@click.option("--limit", type=int, default=20, help="Maximum items to show")
def list_items(
    database: Path,
    locations: bool,
    location: str | None,
    needs_review: bool,
    unknown: bool,
    low_confidence: bool,
    item_type: str | None,
    limit: int,
) -> None:
    """List items or locations in the catalogue."""
    db = Database(database)

    with db.connection() as conn:
        if locations:
            # List all locations
            rows = conn.execute(
                """
                SELECT l.location_id, l.label, COUNT(i.item_id) as item_count
                FROM locations l
                LEFT JOIN items i ON l.location_id = i.location_id
                GROUP BY l.location_id
                ORDER BY l.location_id
                """
            ).fetchall()

            table = Table(title="Locations")
            table.add_column("Location ID", style="cyan")
            table.add_column("Label", style="white")
            table.add_column("Items", style="green")

            for row in rows:
                table.add_row(row["location_id"], row["label"] or "", str(row["item_count"]))

            console.print(table)

        else:
            # List items with filters
            query = """
                SELECT item_id, location_id, title_guess, platform_guess, completeness,
                       item_type, title_confidence, needs_review
                FROM items
            """
            conditions: list[str] = []
            params: list[str | float] = []

            if location:
                conditions.append("location_id = ?")
                params.append(location)
            if needs_review:
                conditions.append("needs_review = 1")
            if unknown:
                conditions.append("(title_guess IS NULL OR title_guess = '')")
            if low_confidence:
                conditions.append("(title_confidence IS NULL OR title_confidence < 0.5)")
            if item_type:
                conditions.append("item_type = ?")
                params.append(item_type)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += f" ORDER BY item_id DESC LIMIT {limit}"
            rows = conn.execute(query, params).fetchall()

            # Determine title based on filters
            title = "Items"
            if unknown:
                title = "Unknown Items"
            elif low_confidence:
                title = "Low Confidence Items"
            elif needs_review:
                title = "Items Needing Review"
            elif item_type:
                title = f"{item_type.title()} Items"

            table = Table(title=title)
            table.add_column("ID", style="cyan")
            table.add_column("Title", style="white")
            table.add_column("Platform", style="yellow")
            table.add_column("Type", style="magenta")
            table.add_column("Status", style="green")
            table.add_column("Conf", style="dim")
            table.add_column("Location", style="blue")

            for row in rows:
                conf = ""
                if row["title_confidence"]:
                    conf = f"{row['title_confidence']:.0%}"
                elif row["title_guess"]:
                    conf = "?"

                # Add review marker to title if needed
                title_display = (row["title_guess"] or "Unknown")[:35]
                if row["needs_review"]:
                    title_display = f"⚠ {title_display}"

                table.add_row(
                    str(row["item_id"]),
                    title_display,
                    row["platform_guess"] or "?",
                    row["item_type"] or "game",
                    row["completeness"],
                    conf,
                    row["location_id"] or "-",
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
@click.option("--location", type=str, help="Filter by location")
@click.option("--limit", type=int, default=20, help="Maximum items to show")
def search(
    query: str,
    database: Path,
    platform: str | None,
    location: str | None,
    limit: int,
) -> None:
    """Search items in the catalogue."""
    db = Database(database)

    with db.connection() as conn:
        sql = """
            SELECT item_id, location_id, title_guess, platform_guess, completeness
            FROM items
            WHERE (title_guess LIKE ? OR ocr_text_raw LIKE ? OR notes LIKE ?)
        """
        params: list[str] = [f"%{query}%", f"%{query}%", f"%{query}%"]

        if platform:
            sql += " AND platform_guess = ?"
            params.append(platform)
        if location:
            sql += " AND location_id = ?"
            params.append(location)

        sql += f" LIMIT {limit}"
        rows = conn.execute(sql, params).fetchall()

        table = Table(title=f'Search results for "{query}"')
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Platform", style="yellow")
        table.add_column("Status", style="green")
        table.add_column("Location", style="blue")

        for row in rows:
            table.add_row(
                str(row["item_id"]),
                (row["title_guess"] or "Unknown")[:40],
                row["platform_guess"] or "?",
                row["completeness"],
                row["location_id"] or "UNASSIGNED",
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


@main.command()
@click.argument("item_id", type=int)
@click.option(
    "--database",
    "-d",
    type=click.Path(exists=True, path_type=Path),
    default="collection.db",
    help="Path to SQLite database",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show(item_id: int, database: Path, as_json: bool) -> None:
    """Show detailed information for an item."""
    import json

    db = Database(database)
    item = db.get_item(item_id)

    if not item:
        console.print(f"[red]Item {item_id} not found[/red]")
        raise SystemExit(1)

    if as_json:
        # Output as JSON for scripting
        import dataclasses

        data = dataclasses.asdict(item)
        # Convert datetime objects to strings
        for k, v in data.items():
            if hasattr(v, "isoformat"):
                data[k] = v.isoformat() if v else None
        console.print(json.dumps(data, indent=2, default=str))
        return

    # Rich formatted output
    console.print(f"\n[bold cyan]Item #{item.item_id}[/bold cyan]")
    console.print("=" * 50)

    # Title section
    title = item.title_manual or item.title_guess or "[Unknown]"
    console.print(f"[bold]Title:[/bold] {title}")
    if item.title_manual and item.title_guess:
        console.print(f"  [dim](AI guess: {item.title_guess})[/dim]")
    if item.title_confidence:
        console.print(f"  [dim]Confidence: {item.title_confidence:.0%}[/dim]")

    # Platform & Type
    platform = item.platform_manual or item.platform_guess or "?"
    console.print(f"[bold]Platform:[/bold] {platform}")
    console.print(f"[bold]Item Type:[/bold] {item.item_type}")
    console.print(f"[bold]Completeness:[/bold] {item.completeness}")

    # Additional details
    if item.brand:
        console.print(f"[bold]Brand:[/bold] {item.brand}")
    if item.region:
        console.print(f"[bold]Region:[/bold] {item.region}")
    if item.year:
        console.print(f"[bold]Year:[/bold] {item.year}")
    if item.language and item.language != "en":
        console.print(f"[bold]Language:[/bold] {item.language}")

    # Condition notes from AI
    if item.condition_notes:
        console.print(f"\n[bold]Condition Notes:[/bold] {item.condition_notes}")

    # Location
    console.print(f"\n[bold]Location:[/bold] {item.location_id or 'UNASSIGNED'}")

    # AI Identification
    console.print(f"\n[bold]AI Identified:[/bold] {'Yes' if item.ai_identified else 'No'}")
    if item.ai_description:
        try:
            ai_data = json.loads(item.ai_description)
            console.print(f"  [dim]Description: {ai_data.get('description', '')[:100]}...[/dim]")
        except json.JSONDecodeError:
            console.print(f"  [dim]{item.ai_description[:100]}...[/dim]")

    # Review status
    if item.needs_review:
        console.print("\n[yellow]⚠ Needs Review[/yellow]")
        if item.review_reason:
            console.print(f"  Reason: {item.review_reason}")

    # eBay status
    if item.ebay_listed:
        console.print("\n[green]✓ Listed on eBay[/green]")
        if item.ebay_listing_id:
            console.print(f"  Listing ID: {item.ebay_listing_id}")

    # Notes
    if item.notes:
        console.print(f"\n[bold]Notes:[/bold] {item.notes}")

    # Source info
    console.print(f"\n[dim]Source: {item.source_filename or 'Unknown'}[/dim]")
    if item.source_camera:
        console.print(f"[dim]Camera: {item.source_camera}[/dim]")

    # Images
    images = db.get_item_images_info(item_id)
    if images:
        console.print(f"\n[bold]Images:[/bold] {len(images)}")
        for img in images:
            cover = " [green](cover)[/green]" if img["is_cover"] else ""
            console.print(
                f"  - {img['image_type']}: {img['width']}x{img['height']} "
                f"({int(img['file_size']) // 1024}KB){cover}"
            )

    # OCR text preview
    if item.ocr_text_raw:
        console.print("\n[bold]OCR Text:[/bold]")
        console.print(f"  [dim]{item.ocr_text_raw[:200]}{'...' if len(item.ocr_text_raw) > 200 else ''}[/dim]")


@main.command()
@click.argument("item_id", type=int)
@click.option(
    "--database",
    "-d",
    type=click.Path(exists=True, path_type=Path),
    default="collection.db",
    help="Path to SQLite database",
)
@click.option("--title", type=str, help="Set title (manual override)")
@click.option("--platform", type=str, help="Set platform (manual override)")
@click.option(
    "--completeness",
    type=click.Choice(["unknown", "loose", "boxed", "partial", "complete_set"]),
    help="Set completeness status",
)
@click.option("--region", type=str, help="Set region (NTSC-U, PAL, NTSC-J)")
@click.option("--year", type=str, help="Set release year")
@click.option("--brand", type=str, help="Set brand/manufacturer")
@click.option("--notes", type=str, help="Set notes")
@click.option("--location", type=str, help="Set location ID")
@click.option(
    "--item-type",
    type=click.Choice(
        ["game", "console", "controller", "accessory", "peripheral", "book", "vinyl", "cd", "trading_card", "other"]
    ),
    help="Set item type",
)
@click.option("--clear-review", is_flag=True, help="Clear needs_review flag")
def edit(
    item_id: int,
    database: Path,
    title: str | None,
    platform: str | None,
    completeness: str | None,
    region: str | None,
    year: str | None,
    brand: str | None,
    notes: str | None,
    location: str | None,
    item_type: str | None,
    clear_review: bool,
) -> None:
    """Edit item fields manually."""
    db = Database(database)

    # Check item exists
    item = db.get_item(item_id)
    if not item:
        console.print(f"[red]Item {item_id} not found[/red]")
        raise SystemExit(1)

    # Build update dict
    updates: dict[str, str | bool | None] = {}
    if title is not None:
        updates["title_manual"] = title
    if platform is not None:
        updates["platform_manual"] = platform
    if completeness is not None:
        updates["completeness"] = completeness
    if region is not None:
        updates["region"] = region
    if year is not None:
        updates["year"] = year
    if brand is not None:
        updates["brand"] = brand
    if notes is not None:
        updates["notes"] = notes
    if location is not None:
        updates["location_id"] = location
    if item_type is not None:
        updates["item_type"] = item_type
    if clear_review:
        updates["needs_review"] = False
        updates["review_reason"] = None

    if not updates:
        console.print("[yellow]No changes specified. Use --help to see options.[/yellow]")
        return

    # Apply updates
    if db.update_item(item_id, **updates):
        console.print(f"[green]✓ Updated item {item_id}[/green]")
        for key, value in updates.items():
            console.print(f"  {key}: {value}")
    else:
        console.print(f"[red]Failed to update item {item_id}[/red]")
        raise SystemExit(1)


@main.command()
@click.argument("item_id", type=int)
@click.option(
    "--database",
    "-d",
    type=click.Path(exists=True, path_type=Path),
    default="collection.db",
    help="Path to SQLite database",
)
@click.option(
    "--provider",
    type=click.Choice(["claude", "ollama"]),
    default="claude",
    help="AI provider (default: claude)",
)
@click.option("--model", type=str, help="AI model name")
@click.option(
    "--image",
    type=click.Path(exists=True, path_type=Path),
    help="Use this image instead of stored image (will be added to item)",
)
def reidentify(
    item_id: int,
    database: Path,
    provider: str,
    model: str | None,
    image: Path | None,
) -> None:
    """Re-run AI identification on an item."""
    from cataloguer.processor.identifier import ItemIdentifier

    db = Database(database)

    # Check item exists
    item = db.get_item(item_id)
    if not item:
        console.print(f"[red]Item {item_id} not found[/red]")
        raise SystemExit(1)

    # Get image data
    image_data: bytes
    if image:
        # Use provided image file
        image_data = image.read_bytes()
        console.print(f"Using image: {image}")

        # Determine media type
        suffix = image.suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(suffix, "image/jpeg")
    else:
        # Get stored image
        stored_image = db.get_item_image(item_id, "full")
        if not stored_image:
            console.print(f"[red]No image found for item {item_id}[/red]")
            console.print("Use --image to provide an image file")
            raise SystemExit(1)
        image_data = stored_image
        media_type = "image/jpeg"
        console.print("Using stored image")

    # Initialize identifier
    try:
        identifier = ItemIdentifier(provider=provider, model=model)
        console.print(f"Provider: {provider} ({identifier.model})")
    except ValueError as e:
        console.print(f"[red]AI setup failed: {e}[/red]")
        raise SystemExit(1) from None

    # Run identification
    console.print("\n[bold]Running identification...[/bold]")
    try:
        result = identifier.identify_bytes(image_data, media_type)
    except Exception as e:
        console.print(f"[red]Identification failed: {e}[/red]")
        raise SystemExit(1) from None

    # Show results
    console.print("\n[green]✓ Identification complete[/green]")
    console.print(f"  Item Type: {result.item_type.value}")
    console.print(f"  Title: {result.title or 'Unknown'}")
    console.print(f"  Platform: {result.platform or 'N/A'}")
    console.print(f"  Brand: {result.brand or 'Unknown'}")
    console.print(f"  Region: {result.region or 'Unknown'}")
    console.print(f"  Completeness: {result.completeness or 'unknown'}")
    console.print(f"  Confidence: {result.confidence or 'unknown'}")
    if result.condition_notes:
        console.print(f"  Condition Notes: {result.condition_notes}")

    # Update item
    import json

    updates: dict[str, str | float | bool | None] = {
        "item_type": result.item_type.value,
        "title_guess": result.title,
        "platform_guess": result.platform,
        "brand": result.brand,
        "region": result.region,
        "year": result.year,
        "condition_notes": result.condition_notes,
        "ai_identified": True,
        "ai_description": json.dumps(result.raw_response),
    }

    # Map confidence to numeric
    confidence_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
    if result.confidence and result.confidence in confidence_map:
        updates["title_confidence"] = confidence_map[result.confidence]

    # Map completeness
    if result.completeness:
        completeness_map = {
            "loose": "loose",
            "boxed": "boxed",
            "complete": "complete_set",
            "sealed": "complete_set",
        }
        updates["completeness"] = completeness_map.get(result.completeness, "unknown")

    if db.update_item(item_id, **updates):
        console.print(f"\n[green]✓ Item {item_id} updated[/green]")
    else:
        console.print(f"[red]Failed to update item {item_id}[/red]")

    # Add new image if provided
    if image:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
        db.add_image(item_id, "full", image_data, width, height, is_cover=True)
        console.print("[green]✓ Added image to item[/green]")


@main.command()
@click.argument("item_id", type=int)
@click.option(
    "--database",
    "-d",
    type=click.Path(exists=True, path_type=Path),
    default="collection.db",
    help="Path to SQLite database",
)
@click.option("--done", is_flag=True, help="Mark as reviewed (clear needs_review)")
@click.option("--flag", is_flag=True, help="Flag for review")
@click.option("--reason", type=str, help="Reason for flagging (use with --flag)")
def review(
    item_id: int,
    database: Path,
    done: bool,
    flag: bool,
    reason: str | None,
) -> None:
    """Mark an item as reviewed or flag for review."""
    db = Database(database)

    # Check item exists
    item = db.get_item(item_id)
    if not item:
        console.print(f"[red]Item {item_id} not found[/red]")
        raise SystemExit(1)

    if done and flag:
        console.print("[red]Cannot use both --done and --flag[/red]")
        raise SystemExit(1)

    if not done and not flag:
        console.print("[yellow]Specify --done or --flag[/yellow]")
        return

    if done:
        if db.update_item(item_id, needs_review=False, review_reason=None):
            console.print(f"[green]✓ Item {item_id} marked as reviewed[/green]")
        else:
            console.print(f"[red]Failed to update item {item_id}[/red]")
    elif flag:
        if db.update_item(item_id, needs_review=True, review_reason=reason):
            console.print(f"[yellow]⚠ Item {item_id} flagged for review[/yellow]")
            if reason:
                console.print(f"  Reason: {reason}")
        else:
            console.print(f"[red]Failed to update item {item_id}[/red]")


if __name__ == "__main__":
    main()
