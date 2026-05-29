import threading
import asyncio
from pathlib import Path
from fastmcp import FastMCP
from loguru import logger
import os

from tostr.exceptions import TostrError

from tostr.commands import (
    init_async, 
    inspect_async, 
    skeleton_async, 
    watch_async,
    clean_db
)
from tostr.core.utils.logger import configure_mcp_logging

class MCPSession:
    def __init__(self):
        self.is_initialized = False
        self.project_dir = None
        self.watcher_thread = None
        self.watcher_loop = None
        self.stop_event = None

    def stop_watcher(self):
        """Cleanly stops the background watcher thread if it exists."""
        if self.watcher_loop and self.stop_event:
            logger.info("Signaling background watcher to stop...")
            self.watcher_loop.call_soon_threadsafe(self.stop_event.set)
            
            if self.watcher_thread:
                # We wait briefly for it to shut down
                self.watcher_thread.join(timeout=2)
                if self.watcher_thread.is_alive():
                    logger.warning("Watcher thread did not shut down in time.")
        
        self.watcher_thread = None
        self.watcher_loop = None
        self.stop_event = None

    def start_watcher(self, target_path: Path):
        """Starts the background watcher thread."""
        self.stop_watcher()
        
        self.watcher_thread = threading.Thread(
            target=self._run_watcher_thread,
            args=(target_path,),
            daemon=True
        )
        self.watcher_thread.start()

    def _run_watcher_thread(self, target_path: Path):
        """
        Sets up an isolated async environment for the background thread,
        then runs your watch_async loop inside it.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.watcher_loop = loop
        self.stop_event = asyncio.Event()
        
        try:
            loop.run_until_complete(watch_async(target_path, stop_event=self.stop_event))
        except Exception as e:
            logger.exception(f"Fatal error in background watcher: {e}")
        finally:
            loop.close()
            logger.info("Background watcher shut down cleanly.")

session = MCPSession()
mcp = FastMCP("Tostr")

@mcp.tool()
async def init(workspace_path: str, use_cache: bool = True, ignore: str = None) -> str:
    """
    -- MUST BE RUN BEFORE ANY OTHER TOOL --
    Initializes the Tostr MCP server for a specific project workspace.
    By default, it will attempt to sync with an existing database if one is found.
    
    Args:
        workspace_path: The ABSOLUTE path to the project workspace. DO NOT use '.' or relative paths. If you only have a relative path, you must determine the absolute path of the current workspace first.
        use_cache: Whether to use the existing AST cache. If False, forces a full re-parse.
        ignore: Add a default ignore template to the project folder (e.g., 'java', 'default').
    """
    
    target_path = Path(workspace_path)
    
    if not target_path.is_absolute():
        return (f"Error: workspace_path must be an absolute path. You provided '{workspace_path}'. "
                f"Please determine the absolute path of the current workspace and try again.")
    
    target_path = target_path.resolve()
    
    if not target_path.exists():
        return f"Fatal Error: Workspace path does not exist: {target_path}"
    
    # Check if we are already initialized for this path
    if session.is_initialized and session.project_dir == target_path and use_cache:
        return f"Status: Already initialized for {target_path}. Set use_cache=False to force a re-parse."
        
    db_path = target_path / ".tostr" / "cache.db"
    
    try:
        configure_mcp_logging(target_path)
        
        # Auto-sync logic: If DB exists and we are using cache, just latch on.
        if db_path.exists() and use_cache:
            session.project_dir = target_path
            session.start_watcher(target_path)
            session.is_initialized = True
            return f"Success: Tostr synced with existing database at {target_path}. Background watcher active."

        # Otherwise, perform full initialization/parse
        await init_async(target_path, use_cache, ignore)

        session.project_dir = target_path
        session.start_watcher(target_path)
        session.is_initialized = True
        
        return f"Success: Tostr initialized and parsed. Cache is built at {db_path}. Background watcher is now actively listening on {target_path}"
        
    except Exception as e:
        return f"Fatal Error Initializing Tostr: {str(e)}"

@mcp.tool()
async def inspect(id: str, include_body: bool = False) -> str:
    """
    Output the AST details and code for a specific struct ID.
    Use this when you need the full implementation details of a specific function or class.
    
    Args:
        id: The unique Tostr ID of the struct to inspect.
        include_body: Include the raw code body in the output.
    """
    if not session.is_initialized:
        return "Error: Tostr is not initialized. You must call 'init' or 'sync' with the absolute workspace path before querying the database."
    
    try:
        result = await inspect_async(id, session.project_dir, include_body, pretty=False)
        return str(result)
    except TostrError as e:
        return f"Error: {e}"

@mcp.tool()
async def clean(workspace_path: str) -> str:
    """
    Clean the SQLite database for a specific workspace and reset the server state if it matches.
    """
    try:
        project_dir = Path(workspace_path).resolve()
        clean_db(project_dir)
        
        if session.project_dir == project_dir:
            session.stop_watcher()
            session.is_initialized = False
            session.project_dir = None
            
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
    if not session.is_initialized:
        return "Error: Tostr is not initialized. You must call 'init' or 'sync' with the absolute workspace path before querying the database."
    
    try:
        result = await skeleton_async(subpath, session.project_dir, pretty=False)
        return str(result)
    except TostrError as e:
        return f"Error: {e}"

if __name__ == "__main__":
    mcp.run()
