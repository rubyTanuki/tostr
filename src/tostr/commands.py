import asyncio
import os
import shutil
import sqlite_vec
from pathlib import Path
from watchfiles import awatch, Change
from loguru import logger
from functools import lru_cache

from tostr.semantic.llm import LLMClient, GeminiStrategy
from tostr.semantic.embeddings import EmbeddingClient, EmbeddingStrategy, OnnxEmbeddingStrategy
from tostr.core import Registry, tost, Verbosity, BaseParser, SQLiteCache, BaseCodeStruct

from tostr.exceptions import APIKeyError, StructNotFoundError, DatabaseNotFoundError

def _verify_db_exists(target_path: Path):
    if not os.path.exists(target_path):
        raise DatabaseNotFoundError("Database not found. Run 'tostr init' first.")

def get_llm_client():
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if GEMINI_API_KEY is None:
        raise APIKeyError("API key not found.")
    
    strategy = GeminiStrategy(api_key=GEMINI_API_KEY)
    return LLMClient(strategy=strategy)

@lru_cache(maxsize=1)
def get_cached_embedding_client():
    """
    Guarantees the model graph is initialized exactly once 
    per long-running process lifecycle.
    """
    strategy = OnnxEmbeddingStrategy()
    return EmbeddingClient(strategy=strategy)

def clean_db(target_path: Path):
    if os.path.exists(target_path / ".tostr"):
        shutil.rmtree(target_path / ".tostr")
        logger.info("Database cleaned.")
    else:
        logger.warning("No database found to clean.")
    
    ignore_file = target_path / ".tostrignore"
    if ignore_file.exists():
        ignore_file.unlink()
        logger.info(f"Deleted {ignore_file}")

def get_status(target_path: Path) -> dict:
    db_path = target_path / ".tostr" / "cache.db"
    status = {
        "project_path": str(target_path.absolute()),
        "db_exists": db_path.exists(),
        "db_path": str(db_path) if db_path.exists() else None,
        "db_size_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "last_updated": db_path.stat().st_mtime if db_path.exists() else None,
        "counts": {}
    }

    if status["db_exists"]:
        db = SQLiteCache(db_path)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT type, COUNT(*) as count FROM structs GROUP BY type")
            rows = cursor.fetchall()
            for row in rows:
                status["counts"][row["type"]] = row["count"]
            
            cursor.execute("SELECT COUNT(*) FROM edges")
            status["counts"]["edges"] = cursor.fetchone()[0]

    return status

async def _build_ast_async(target_path: Path, use_cache: bool = True) -> BaseParser:
    llm = get_llm_client()
    embedder = get_cached_embedding_client()
    db = SQLiteCache(target_path / ".tostr" / "cache.db")
    registry = Registry(use_cache=use_cache, db=db, project_path=target_path)
    logger.info("Building AST...")
    
    parser = BaseParser(target_path, llm, embedder, registry)
    logger.info("Parsing files...")
    await parser.parse()
    logger.success("✅ Parsed files")
    return parser

def _write_default_ignore(target_path: Path, ignore_type: str):
    base_path = Path(__file__).parent / "languages"
    if ignore_type == "default":
        template_path = base_path / "default.tostrignore"
    else:
        template_path = base_path / ignore_type / "default.tostrignore"
    
    if template_path.exists():
        ignore_file = target_path / ".tostrignore"
        with open(template_path, 'r') as f:
            content = f.read()
        
        mode = 'a' if ignore_file.exists() else 'w'
        with open(ignore_file, mode) as f:
            if mode == 'a':
                f.write("\n")
            f.write(content)
        logger.info(f"Written default ignore for {ignore_type} to {ignore_file}")
    else:
        logger.warning(f"No default ignore template found for {ignore_type} at {template_path}")

async def init_async(target_path: Path, use_cache: bool = True, ignore: str = None):
    """Core asynchronous logic for scraping and parsing."""
    
    if ignore:
        _write_default_ignore(target_path, ignore)

    # Parse and resolve AST
    parser = await _build_ast_async(target_path, use_cache=use_cache)
        
    # Write Cache
    parser.registry.save_to_cache()

def resolve_uid_to_id(uid: str, project_path: Path) -> str:
    """Simplifies UID to ID resolution by querying the database directly."""
    _verify_db_exists(project_path)
    db = SQLiteCache(project_path / ".tostr" / "cache.db")
    with db.get_connection() as conn:
        row = conn.execute("SELECT id FROM structs WHERE uid = ?", (uid,)).fetchone()
        return row[0] if row else None
    
async def inspect_async(struct_ids: list[str], project_path: Path, include_body: bool = False, pretty: bool = True):
    _verify_db_exists(project_path)
    
    db = SQLiteCache(project_path / ".tostr" / "cache.db")
    registry = Registry(db=db, use_cache=True, project_path=project_path)
    
    results = []
    for struct_id in struct_ids:
        # Check if it's a UID and needs resolution
        if not (struct_id.startswith(("S-", "C-", "M-", "V-", "F-", "D-"))):
            resolved_id = resolve_uid_to_id(struct_id, project_path)
            if resolved_id:
                struct_id = resolved_id
        
        struct_obj = registry.get_struct_by_id(struct_id)
        if struct_obj is None:
            results.append(f"Error: Struct not found with id/uid {struct_id}.")
            continue
        
        logger.debug(f"{struct_obj.uid}'s children: {[str(child) for child in struct_obj.all_children]}")
        
        tost_string = tost.dump(struct_obj, verbosity=Verbosity.VERBOSE, include_body=include_body, pretty=pretty)
        if isinstance(struct_obj, BaseCodeStruct):
            tost_string = f"{str(struct_obj.path)}\n{tost_string}"
        results.append(tost_string)
        
    return "\n\n".join(results)

async def skeleton_async(subpath: str, project_path: Path, pretty: bool = True, depth: int = 7, files_only: bool = False):
    _verify_db_exists(project_path)
    
    db = SQLiteCache(project_path / ".tostr" / "cache.db")
    registry = Registry(db=db, project_path=project_path)
    
    subpath = Path(project_path / subpath)
    logger.debug(f"Loading subtree for path: {subpath}")
    
    registry.load_filepath(subpath)
    if not registry.files:
        raise FileNotFoundError(f"No files found matching path '{subpath}'.")
    
    return tost.dump_skeleton(registry.root, pretty=pretty, depth=depth, files_only=files_only)

active_tasks = {}

async def watch_async(target_path: Path, stop_event: asyncio.Event = None):
    llm = get_llm_client()
    
    logger.info("Starting Listener")
    try:
        async for changes in awatch(target_path, stop_event=stop_event):
            for change_type, path in changes:
                path = Path(path).relative_to(target_path)
                if ".tostr" in str(path):
                    continue
                
                existing_task = active_tasks.get(path)
                if existing_task and not existing_task.done():
                    existing_task.cancel()
                
                match change_type:
                    case Change.modified:
                        logger.info(f"File modified: {path}")
                    case Change.added:
                        logger.info(f"File added: {path}")
                    case Change.deleted:
                        logger.info(f"File deleted: {path}")
                        # TODO: handle deletions in the db
                        
                new_task = asyncio.create_task(
                    process_single_file(target_path, path, llm)
                )
                active_tasks[path] = new_task
                
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("\n🛑 Stopping listener...")

async def search_async(query: str, project_path: Path, filter_type: str = None, top_k: int = 5):
    _verify_db_exists(project_path)
    embedder = get_cached_embedding_client()
    query_vector = embedder.strategy.embed_query(query)
    
    db = SQLiteCache(project_path / ".tostr" / "cache.db")
    
    # We fetch a larger k from the vector index to allow room for the JOIN filter
    k_to_fetch = top_k * 10 if filter_type else top_k
    
    with db.get_connection() as conn:
        query_vec_bytes = sqlite_vec.serialize_float32(query_vector)
        
        sql = """
            SELECT s.uid, s.id, s.type, v.distance
            FROM vec_structs v
            JOIN structs s ON s.id = v.struct_id
            WHERE v.vector MATCH ?
            AND v.k = ?
        """
        params = [query_vec_bytes, k_to_fetch]
        
        if filter_type:
            sql += " AND s.type LIKE ?"
            params.append(f"%{filter_type}%")
            
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
        
        results = []
        for row in rows:
            results.append(f"{row['id']}|{row['uid']} ({row['type']})")
            if len(results) >= top_k:
                break
                
        return "\n".join(results) if results else "No results found matching your query."

async def process_single_file(project_dir: Path, filepath: Path, llm_client: LLMClient):
    logger.info(f"Processing file {filepath}")
    try:
        db = SQLiteCache(project_dir / ".tostr" / "cache.db")
        
        registry = Registry(db=db, use_cache=True, project_path=project_dir)
        parser = BaseParser(filepath, llm_client, registry)
        
        parser.parse_path(filepath)
        
        parser.resolve_dependencies()
        
        await asyncio.to_thread(registry.save_to_cache, stale=True)
        logger.debug("Wrote Cache w/ stale descriptions")

        await asyncio.to_thread(registry.propagate_hash_update, str(filepath))
        
        # resolve the descriptions and do the second cache write
        await parser.resolve_descriptions_async()
        await asyncio.to_thread(registry.save_to_cache)
        logger.debug("Wrote Cache w/ resolved descriptions")
        
        logger.debug(f"✅ Processed file {filepath}")
        
    except asyncio.CancelledError:
        logger.warning(f"Task cancelled on {filepath}")
    except Exception as e:
        logger.warning(f"Error processing file {filepath}: {e}")
    finally:
        if active_tasks.get(filepath) == asyncio.current_task():
            del active_tasks[filepath]