import asyncio
import time
from pathlib import Path
import typer
from typing import Annotated
from loguru import logger

from tostr.exceptions import TostrError

from tostr.commands import init_async, inspect_async, skeleton_async, watch_async, clean_db

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
def inspect(
    id: Annotated[
        str, 
        typer.Argument()
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
    ] = False
):
    """Output the AST details for a specific struct ID."""
    configure_cli_logging(debug)
    
    start_time = time.perf_counter()
    try:
        result = asyncio.run(inspect_async(id, path, include_body=include_body, pretty=pretty))
        print(result)
    except TostrError as e:
        typer.secho(f"❌ Error: {e}", fg="red", err=True)
        raise typer.Exit(code=1)
    
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    logger.debug(f"Finished in {elapsed_time:.4f} seconds.")


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
            "-d/-nd",
            help="Enable debug logging"
            )
    ] = False
    
):
    """Output the .tost skeleton format for all files matching a specific subpath."""
    configure_cli_logging(debug)
    
    start_time = time.perf_counter()
    try:
        result = asyncio.run(skeleton_async(subpath, path, pretty=pretty))
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