import threading
import asyncio
from pathlib import Path
from fastmcp import FastMCP
from loguru import logger
import os

from tostr.exceptions import ToasterError

from tostr.commands import (
    init_async, 
    inspect_async, 
    skeleton_async, 
    watch_async,
    clean_db
)
from tostr.core.utils.logger import configure_mcp_logging

_is_initialized = False
_current_project_dir = None

mcp = FastMCP("Toaster")

# --- THE SYNCHRONOUS BRIDGE ---
def _run_watcher_thread(target_path: Path):
    """
    Sets up an isolated async environment for the background thread,
    then runs your watch_async loop inside it.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # This calls your exact watch_async function!
        loop.run_until_complete(watch_async(target_path))
    except Exception as e:
        logger.exception(f"Fatal error in background watcher: {e}")
    finally:
        loop.close()
        logger.info("Background watcher shut down cleanly.")

@mcp.tool()
async def init(workspace_path: str, use_cache: bool = True, ignore: str = None) -> str:
    """
    -- MUST BE RUN BEFORE ANY OTHER TOOL --
    Initializes the Toaster MCP server for a specific project workspace. 
    
    Args:
        workspace_path: The ABSOLUTE path to the project workspace. DO NOT use '.' or relative paths. If you only have a relative path, you must determine the absolute path of the current workspace first.
        use_cache: Whether to use the existing AST cache.
        ignore: Add a default ignore template to the project folder (e.g., 'java', 'default').
    """
    
    target_path = Path(workspace_path)
    
    if not target_path.is_absolute():
        return (f"Error: workspace_path must be an absolute path. You provided '{workspace_path}'. "
                f"Please determine the absolute path of the current workspace and try again.")
    
    target_path = target_path.resolve()
    
    try:
        os.chdir(target_path)
    except FileNotFoundError:
        return f"Fatal Error: Workspace path does not exist: {target_path}"
    
    global _is_initialized, _current_project_dir
    project_dir = target_path
    
    if _is_initialized and _current_project_dir == project_dir:
        return f"Status: Already initialized for {project_dir}."
        
    try:
        configure_mcp_logging(project_dir)
        
        await init_async(project_dir, use_cache, ignore)

        watcher_thread = threading.Thread(
            target=_run_watcher_thread,
            args=(project_dir,),
            daemon=True
        )
        watcher_thread.start()
        
        _is_initialized = True
        _current_project_dir = project_dir
        
        return f"Success: Toaster initialized. Cache is built at {project_dir}/.tostr/cache.db. Background watcher is now actively listening on {project_dir}"
        
    except Exception as e:
        return f"Fatal Error Initializing Toaster: {str(e)}"

@mcp.tool()
async def inspect(id: str, include_body: bool = False) -> str:
    """
    Output the AST details and code for a specific struct ID.
    Use this when you need the full implementation details of a specific function or class.
    
    Args:
        id: The unique Toaster ID of the struct to inspect.
        include_body: Include the raw code body in the output.
    """
    global _is_initialized, _current_project_dir
    
    if not _is_initialized:
        return "Error: Toaster is not initialized. You must call 'init' with the absolute workspace path before querying the database."
    
    try:
        result = await inspect_async(id, _current_project_dir, include_body, pretty=False)
        return str(result)
    except ToasterError as e:
        return f"Error: {e}"


@mcp.tool()
async def clean(workspace_path: str) -> str:
    """
    Clean the SQLite database for a specific workspace.
    """
    try:
        project_dir = Path(workspace_path).resolve()
        clean_db(project_dir)
        return f"Success: Database cleaned for {project_dir}."
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
async def skeleton(subpath: str) -> str:
    """
    Output the .tost skeleton format for all files matching a specific subpath.
    Use this to understand the high-level architecture, classes, and function signatures of a file or directory without reading the full code.
    
    Args:
        subpath: File or directory path relative to the project root to generate a skeleton for.
    """
    global _is_initialized, _current_project_dir
    
    if not _is_initialized:
        return "Error: Toaster is not initialized. You must call 'init' with the absolute workspace path before querying the database."
    
    try:
        result = await skeleton_async(subpath, _current_project_dir, pretty=False)
        return str(result)
    except ToasterError as e:
        return f"Error: {e}"

if __name__ == "__main__":
    mcp.run()