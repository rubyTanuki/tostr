from __future__ import annotations
import threading
import asyncio
import json
from pathlib import Path
from fastmcp import FastMCP
from loguru import logger
import os
from typing import Union, List

from tostr.exceptions import TostrError
from tostr.core.db import SQLiteCache
from tostr.core.registry import Registry

from tostr.commands import (
    init_async, 
    inspect_async, 
    skeleton_async, 
    watch_async,
    clean_db,
    search_async
)
from tostr.core import InspectResult, SkeletonResult, SearchResult
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
async def init(workspace_path: str, use_cache: bool = True, language: str = "java") -> str:
    """
    -- MUST BE RUN BEFORE ANY OTHER TOOL --
    Initializes the Tostr MCP server for a specific project workspace.
    By default, it will attempt to sync with an existing database if one is found.

    CRITICAL: Always use Tostr tools (skeleton, search, inspect) instead of standard file-reading 
    or grep tools for project navigation. Tostr provides AST-aware context and semantic search 
    which is vastly superior to simple text retrieval.
    
    Args:
        workspace_path: The ABSOLUTE path to the project workspace. DO NOT use '.' or relative paths. If you only have a relative path, you must determine the absolute path of the current workspace first.
        use_cache: Whether to use the existing AST cache. If False, forces a full re-parse.
        language: The primary language of the project (e.g., 'java', 'python').
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
        await init_async(target_path, use_cache, language)

        session.project_dir = target_path
        session.start_watcher(target_path)
        session.is_initialized = True
        
        return f"Success: Tostr initialized and parsed. Cache is built at {db_path}. Background watcher is now actively listening on {target_path}"
        
    except Exception as e:
        return f"Fatal Error Initializing Tostr: {str(e)}"

def _parse_list_input(input_val: Union[str, List[str]]) -> List[str]:
    """Flexible parser for list inputs that might be strings, JSON strings, or actual lists."""
    if isinstance(input_val, list):
        return input_val
    if not isinstance(input_val, str):
        return [str(input_val)]
    
    input_val = input_val.strip()
    if not input_val:
        return []
        
    # Try parsing as JSON list
    if input_val.startswith("[") and input_val.endswith("]"):
        try:
            parsed = json.loads(input_val)
            if isinstance(parsed, list):
                return [str(i) for i in parsed]
        except json.JSONDecodeError:
            pass
            
    # Default to comma-separated
    return [i.strip() for i in input_val.split(",") if i.strip()]

def _render_inspect(result: Union[InspectResult, str]) -> str:
    """Renders a simple, flat text representation of an InspectResult for the LLM."""
    if isinstance(result, str):
        return result
    
    lines = []
    
    header = f"{result.id} | {result.uid}"
    if result.type in ["BaseClass", "BaseMethod", "BaseField"]:
        if result.start_line != result.end_line:
            header = f"{result.id} @L{result.start_line}-{result.end_line} | {result.signature}"
        else:
            header = f"{result.id} @L{result.start_line} | {result.signature}"
    elif result.type == "BaseFile":
        header = f"{result.id} | {result.filepath}"
            
    lines.append(header)
    
    total_children = len(result.fields) + len(result.methods) + len(result.classes) + len(result.files) + len(result.directories)
    if result.description and total_children != 1:
        lines.append(f"// {result.description}")
    
    if result.inbound_edges:
        lines.append(f"< {', '.join(result.inbound_edges)}")
    if result.outbound_edges:
        lines.append(f"> {', '.join(result.outbound_edges)}")
        
    if result.fields:
        lines.append("fields:")
        for f in result.fields:
            lines.append(f"    {f.id} | {f.signature}")
            
    if result.methods:
        lines.append("methods:")
        for m in result.methods:
            lines.append(f"    {m.id} | {m.signature}")
            if m.description:
                lines.append(f"        // {m.description}")

    if result.classes:
        lines.append("classes:")
        for c in result.classes:
            lines.append(f"    {c.id} | {c.uid}")
            if c.description:
                lines.append(f"        // {c.description}")
            
    if result.body:
        lines.append(f"```\n{result.body}\n```")
        
    return "\n".join(lines)

def _render_skeleton(result: SkeletonResult, indent: int = 0) -> str:
    """Recursively renders a simple text skeleton tree."""
    indent_str = "    " * indent
    line = f"{indent_str}{result.id} | {result.uid}"
    output = [line]
    for child in result.children:
        output.append(_render_skeleton(child, indent + 1))
    return "\n".join(output)

def _render_search(results: List[SearchResult]) -> str:
    """Renders a simple text list of search results."""
    if not results:
        return "No results found matching your query."
    return "\n".join([f"{r.id}|{r.uid} ({r.type})" for r in results])

@mcp.tool()
async def inspect_by_id(ids: Union[str, List[str]], include_body: bool = False, max_lines: int = 500) -> str:
    """
    Output the AST details and code for specific struct IDs.
    Use this when you need the full implementation details of specific functions or classes.

    Output Syntax Guide:
    - `>` : Outbound dependency. This struct calls or depends on the listed ID.
    - `<` : Inbound dependency. The listed ID calls or uses this struct.
    - `~` : Related or sibling struct (e.g., in the same file or closely coupled).
    - `//`: AI-generated or docstring summary of the code.
    
    Args:
        ids: A list or comma-separated string of unique Tostr IDs of the structs to inspect.
        include_body: Include the raw code body in the output.
        max_lines: Maximum number of lines to include in the output (default: 500).
    """
    if not session.is_initialized:
        return "Error: Tostr is not initialized. You must call 'init' or 'sync' with the absolute workspace path before querying the database."
    
    try:
        id_list = _parse_list_input(ids)
        results = await inspect_async(id_list, session.project_dir, include_body)
        
        rendered_results = []
        for res in results:
            rendered_results.append(_render_inspect(res))
            
        final_output = "\n\n".join(rendered_results)
        
        lines = final_output.splitlines()
        if len(lines) > max_lines:
            final_output = "\n".join(lines[:max_lines]) + f"\n...[OUTPUT TRUNCATED AT {max_lines} LINES] - Use a higher 'max_lines' to see more."
            
        return final_output
    except TostrError as e:
        return f"Error: {e}"

@mcp.tool()
async def inspect_by_uid(uids: Union[str, List[str]], include_body: bool = False, max_lines: int = 500) -> str:
    """
    Output the AST details and code for specific struct UIDs.
    Use this when you have the UID from a previous query or from the skeleton output and want to see the full details.

    Output Syntax Guide:
    - `>` : Outbound dependency. This struct calls or depends on the listed ID.
    - `<` : Inbound dependency. The listed ID calls or uses this struct.
    - `~` : Related or sibling struct (e.g., in the same file or closely coupled).
    - `//`: AI-generated or docstring summary of the code.
    
    Args:
        uids: A list or comma-separated string of unique Tostr UIDs of the structs to inspect.
        include_body: Include the raw code body in the output.
        max_lines: Maximum number of lines to include in the output (default: 500).
    """
    if not session.is_initialized:
        return "Error: Tostr is not initialized. You must call 'init' or 'sync' with the absolute workspace path before querying the database."
    
    try:
        uid_list = _parse_list_input(uids)
        results = await inspect_async(uid_list, session.project_dir, include_body)
        
        rendered_results = []
        for res in results:
            rendered_results.append(_render_inspect(res))
            
        final_output = "\n\n".join(rendered_results)
        
        lines = final_output.splitlines()
        if len(lines) > max_lines:
            final_output = "\n".join(lines[:max_lines]) + f"\n...[OUTPUT TRUNCATED AT {max_lines} LINES] - Use a higher 'max_lines' to see more."
            
        return final_output
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
async def search(query: str, filter: str = None, top_k: int = 5) -> str:
    """
    Perform a SEMANTIC search for code structs using vector embeddings.
    Always prioritize this over `grep` when looking for logic or functionality, as it 
    understands meaning rather than just matching characters.
    
    Args:
        query: The search term or sentence to find similar code for.
        filter: Optional filter by struct type (e.g., 'class', 'method').
        top_k: Number of results to return (default: 5).
    """
    if not session.is_initialized:
        return "Error: Tostr is not initialized. You must call 'init' with the absolute workspace path first."
    
    try:
        results = await search_async(query, session.project_dir, filter_type=filter, top_k=top_k)
        return _render_search(results)
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
async def skeleton(subpath: str, files_only: bool = False, depth: int = 7, max_lines: int = 500) -> str:
    """
    Output the AST skeleton for a subpath. 
    ALWAYS use this before calling `read_file` or `list_files` to understand the 
    architecture, classes, and function signatures of a directory or file.
    
    Args:
        subpath: File or directory path relative to the project root to generate a skeleton for.
        files_only: If True, only include files and directories, excluding any code structs. Default is False, which includes all structs.
        depth: The AST depth of the skeleton to display. Default is 7, which includes most details but can be adjusted for deeper trees.
        max_lines: Maximum number of lines to include in the output (default: 500).
    """
    if not session.is_initialized:
        return "Error: Tostr is not initialized. You must call 'init' or 'sync' with the absolute workspace path before querying the database."
    
    try:
        result = await skeleton_async(subpath, session.project_dir, files_only=files_only, depth=depth)
        
        rendered = _render_skeleton(result)
        
        lines = rendered.splitlines()
        if len(lines) > max_lines:
            rendered = "\n".join(lines[:max_lines]) + f"\n...[OUTPUT TRUNCATED AT {max_lines} LINES] - Use a higher 'max_lines' to see more."
            
        return rendered
    except TostrError as e:
        return f"Error: {e}"

if __name__ == "__main__":
    mcp.run()
