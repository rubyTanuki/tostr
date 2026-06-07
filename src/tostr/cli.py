import asyncio
import time
from pathlib import Path
import typer
from typing import Annotated, List
from loguru import logger
from tostr.exceptions import TostrError

from tostr.commands import (
    init_async, 
    inspect_async, 
    skeleton_async, 
    watch_async, 
    clean_db,
    resolve_uid_to_id,
    search_async,
    get_status
)

from tostr.server import mcp

from tostr.core.utils.logger import configure_cli_logging

import multiprocessing


# Initialize the Typer app
app = typer.Typer(
    name="tostr",
    help="AST scraper for LLM RAG context generation.",
    add_completion=False # Optional: Turns off the auto-generated completion install command for cleaner help menus
)

def _run_watcher_thread(target_path: Path):
    """
    Sets up an isolated async environment for the background thread.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        logger.info(f"Background watcher started on {target_path}")
        loop.run_until_complete(watch_async(target_path))
    except Exception as e:
        logger.exception(f"Fatal error in background watcher: {e}")
    finally:
        loop.close()
        logger.info("Background watcher shut down.")

@app.command("start-mcp")
def start_mcp():
    """Start the bare MCP server. Awaits agent initialization."""
    mcp.run()

@app.command()
def status(
    path: Path = typer.Argument(
        ".", 
        help="Path to the project directory to check",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True
    ),
    debug: Annotated[
        bool, 
        typer.Option(
            "--debug/--no-debug", 
            "-d/-nd",
            help="Enable debug logging"
            )
    ] = False
):
    """Show the status of Tostr in the given path."""
    configure_cli_logging(debug)
    import datetime
    
    try:
        status_data = get_status(path)
        
        typer.secho(f"\n📊 Tostr Status for: {status_data['project_path']}", fg="cyan", bold=True)
        
        if status_data["db_exists"]:
            typer.secho("✅ Database: Found", fg="green")
            typer.echo(f"   Path: {status_data['db_path']}")
            
            size_mb = status_data['db_size_bytes'] / (1024 * 1024)
            typer.echo(f"   Size: {size_mb:.2f} MB")
            
            last_updated = datetime.datetime.fromtimestamp(status_data['last_updated']).strftime('%Y-%m-%d %H:%M:%S')
            typer.echo(f"   Last Updated: {last_updated}")
            
            typer.secho("\n📈 Statistics:", bold=True)
            for type_name, count in status_data["counts"].items():
                typer.echo(f"   {type_name}: {count}")
        else:
            typer.secho("❌ Database: Not found", fg="red")
            typer.echo("   Run 'tostr init' to initialize the database.")
        typer.echo("")
        
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg="red", err=True)
        raise typer.Exit(code=1)

@app.command()
def watch(
    path: Path = typer.Argument(
        ".", 
        help="Path to the project directory to scan",
        exists=True,       # Typer automatically checks if the path exists
        file_okay=False,   # Typer blocks files, only allowing directories
        dir_okay=True,
        resolve_path=True  # Converts relative paths to absolute paths automatically
    ),
    debug: Annotated[
        bool, 
        typer.Option(
            "--debug/--no-debug", 
            "-d/-nd",
            help="Enable debug logging"
            )
    ] = False
):
    """Watch for changes to files and update the SQLite database."""
    configure_cli_logging(debug)
    try:
        asyncio.run(watch_async(path))
    except TostrError as e:
        typer.secho(f"❌ Error: {e}", fg="red", err=True)
        raise typer.Exit(code=1)

@app.command()
def clean(
    path: Path = typer.Argument(
        ".", 
        help="Path to the project directory to scan",
        exists=True,       # Typer automatically checks if the path exists
        file_okay=False,   # Typer blocks files, only allowing directories
        dir_okay=True,
        resolve_path=True  # Converts relative paths to absolute paths automatically
    ),
    debug: Annotated[
        bool, 
        typer.Option(
            "--debug/--no-debug", 
            "-d/-nd",
            help="Enable debug logging"
            )
    ] = False
):
    """Clean the SQLite database."""
    configure_cli_logging(debug)
    try:
        clean_db(path)
    except TostrError as e:
        typer.secho(f"❌ Error: {e}", fg="red", err=True)
        raise typer.Exit(code=1)

@app.command()
def init(
    path: Path = typer.Argument(
        ".", 
        help="Path to the project directory to scan",
        exists=True,       # Typer automatically checks if the path exists
        file_okay=False,   # Typer blocks files, only allowing directories
        dir_okay=True,
        resolve_path=True  # Converts relative paths to absolute paths automatically
    ),
    use_cache: Annotated[
        bool, 
        typer.Option(
            "--use-cache/--no-cache", 
            help="Load cache if it exists"
            )
        ] = True,
    ignore: Annotated[
        str,
        typer.Option(
            "--ignore",
            "-i",
            help="Add a default ignore template to the project folder (e.g., 'java', 'default')"
        )
    ] = None,
    debug: Annotated[
        bool, 
        typer.Option(
            "--debug/--no-debug", 
            "-d/-nd",
            help="Enable debug logging"
            )
    ] = False
):
    """Parse files and setup SQLite database."""
    configure_cli_logging(debug)
    start_time = time.perf_counter()
    try:
        asyncio.run(init_async(path, use_cache, ignore))
    except TostrError as e:
        typer.secho(f"❌ Error: {e}", fg="red", err=True)
        raise typer.Exit(code=1)
    
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    logger.debug(f"Finished in {elapsed_time:.4f} seconds.")


@app.command()
def resolve(
    uid: Annotated[
        str, 
        typer.Argument(help="The UID to resolve to an ID")
    ],
    path: Path = typer.Argument(
        ".", 
        help="Path to the project directory to scan",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True
    ),
    debug: Annotated[
        bool, 
        typer.Option(
            "--debug/--no-debug", 
            "-d/-nd",
            help="Enable debug logging"
            )
    ] = False
):
    """Resolve a UID to its corresponding struct ID."""
    configure_cli_logging(debug)
    try:
        result = resolve_uid_to_id(uid, path)
        if result:
            print(result)
        else:
            typer.secho(f"❌ Error: No struct found with UID '{uid}'", fg="red", err=True)
            raise typer.Exit(code=1)
    except TostrError as e:
        typer.secho(f"❌ Error: {e}", fg="red", err=True)
        raise typer.Exit(code=1)

@app.command()
def inspect(
    ids: Annotated[
        List[str], 
        typer.Argument(help="List of struct IDs or UIDs to inspect")
    ],
    path: Path = typer.Argument(
        ".", 
        help="Path to the project directory to scan",
        exists=True,       # Typer automatically checks if the path exists
        file_okay=False,   # Typer blocks files, only allowing directories
        dir_okay=True,
        resolve_path=True  # Converts relative paths to absolute paths automatically
    ),
    include_body: Annotated[
        bool, 
        typer.Option(
            "--body/--no-body", 
            help="Include code body in output"
            )
        ] = False,
    pretty: Annotated[
        bool,
        typer.Option(
            "--pretty/--raw",
            help="Pretty format output with line wrapping and indentation (disable for raw output)"
        )
    ] = True,
    debug: Annotated[
        bool, 
        typer.Option(
            "--debug/--no-debug", 
            "-d/-nd",
            help="Enable debug logging"
            )
    ] = False,
    max_lines: Annotated[
        int,
        typer.Option(
            "--max-lines",
            "-m",
            help="Maximum number of lines to include in the output (default: 500)"
        )
    ] = 500
):
    """Output the AST details for specific struct IDs or UIDs."""
    configure_cli_logging(debug)
    
    start_time = time.perf_counter()
    try:
        result = asyncio.run(inspect_async(ids, path, include_body=include_body, pretty=pretty))
        lines = result.splitlines()
        if len(lines) > max_lines:
            result = "\n".join(lines[:max_lines]) + f"\n...[OUTPUT TRUNCATED AT {max_lines} LINES (total: {len(lines)})] - Use a higher '--max-lines <N>' to see more."
        print(result)
    except TostrError as e:
        typer.secho(f"❌ Error: {e}", fg="red", err=True)
        raise typer.Exit(code=1)
    
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    logger.debug(f"Finished in {elapsed_time:.4f} seconds.")


@app.command()
def search(
    query: Annotated[
        str,
        typer.Argument(help="The search query to embed and find similar structs for")
    ],
    path: Path = typer.Argument(
        ".", 
        help="Path to the project directory",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True
    ),
    filter: Annotated[
        str,
        typer.Option(
            "--filter",
            "-f",
            help="Filter by struct type (e.g., 'class', 'method')"
        )
    ] = None,
    top_k: Annotated[
        int,
        typer.Option(
            "--top-k",
            "-k",
            help="Number of results to return"
        )
    ] = 5,
    debug: Annotated[
        bool, 
        typer.Option(
            "--debug/--no-debug", 
            "-d/-nd",
            help="Enable debug logging"
            )
    ] = False
):
    """Search for structs by embedding a search term and finding the top K matches."""
    configure_cli_logging(debug)
    try:
        result = asyncio.run(search_async(query, path, filter_type=filter, top_k=top_k))
        print(result)
    except TostrError as e:
        typer.secho(f"❌ Error: {e}", fg="red", err=True)
        raise typer.Exit(code=1)

@app.command()
def skeleton(
    subpath: Annotated[
        str, 
        typer.Argument(help="File or directory path relative to the project root to generate a skeleton for")
    ] = ".",
    path: Path = typer.Argument(
        ".", 
        help="Path to the project directory to scan",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True
    ),
    pretty: Annotated[
        bool,
        typer.Option(
            "--pretty/--raw",
            help="Pretty format output with line wrapping and indentation (disable for raw output)"
        )
    ] = True,
    debug: Annotated[
        bool, 
        typer.Option(
            "--debug/--no-debug",
            help="Enable debug logging"
            )
    ] = False,
    depth: Annotated[
        int,
        typer.Option(
            "--depth",
            "-d",
            help="Depth to traverse for skeleton generation (default: 7)"
        )
    ] = 7, 
    files_only: Annotated[
        bool,
        typer.Option(
            "--files-only",
            "-f",
            help="Only generate skeleton for files (default: False)"
        )
    ] = False,
    max_lines: Annotated[
        int,
        typer.Option(
            "--max-lines",
            "-m",
            help="Maximum number of lines to include in the output (default: 500)"
        )
    ] = 500
    
):
    """Output the .tost skeleton format for all files matching a specific subpath."""
    configure_cli_logging(debug)
    
    start_time = time.perf_counter()
    try:
        result = asyncio.run(skeleton_async(subpath, path, pretty=pretty, depth=depth, files_only=files_only))
        lines = result.splitlines()
        if len(lines) > max_lines:
            result = "\n".join(lines[:max_lines]) + f"\n...[OUTPUT TRUNCATED AT {max_lines} LINES (total: {len(lines)})] - Use a higher '--max-lines <N>' to see more."
        print(result)
    except TostrError as e:
        typer.secho(f"❌ Error: {e}", fg="red", err=True)
        raise typer.Exit(code=1)
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    logger.debug(f"Finished in {elapsed_time:.4f} seconds.")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app()