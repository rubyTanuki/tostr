from __future__ import annotations
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
from tostr.core import Registry, tost, InspectResult, SkeletonResult, SearchResult, BaseParser, SQLiteCache, BaseCodeStruct
from tostr.core.context.config import ProjectConfig
from tostr.core.providers import LanguageProvider

from tostr.exceptions import APIKeyError, DatabaseNotFoundError

def _verify_db_exists(target_path: Path):
    """Ensure an initialized Tostr database exists for the given project path.

    target_path is the project root; the actual database lives at
    .tostr/cache.db inside it. Raising here (instead of letting SQLiteCache
    lazily create an empty schema) gives the user a clean 'run init first'
    message rather than a downstream stack trace.
    """
    db_path = Path(target_path) / ".tostr" / "cache.db"
    if not db_path.exists():
        raise DatabaseNotFoundError(
            f"No Tostr database found at {db_path}. Run 'tostr init' first."
        )

def get_llm_client(progress_tracker: "ProgressTracker" = None):
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if GEMINI_API_KEY is None:
        raise APIKeyError("API key not found.")
    
    strategy = GeminiStrategy(api_key=GEMINI_API_KEY)
    return LLMClient(strategy=strategy, progress_tracker=progress_tracker)

@lru_cache(maxsize=1)
def get_cached_embedding_client(progress_tracker: "ProgressTracker" = None):
    """
    Guarantees the model graph is initialized exactly once 
    per long-running process lifecycle.
    """
    strategy = OnnxEmbeddingStrategy()
    return EmbeddingClient(strategy=strategy, progress_tracker=progress_tracker)

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

async def _build_ast_async(target_path: Path, use_cache: bool = True, progress_tracker: "ProgressTracker" = None, no_llm: bool = False) -> BaseParser:
    llm = None if no_llm else get_llm_client(progress_tracker=progress_tracker)
    embedder = get_cached_embedding_client(progress_tracker=progress_tracker)
    db = SQLiteCache(target_path / ".tostr" / "cache.db")
    registry = Registry(use_cache=use_cache, db=db, project_path=target_path, progress_tracker=progress_tracker)
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

async def init_async(target_path: Path, use_cache: bool = True, language: str = "auto", progress_tracker: "ProgressTracker" = None, no_llm: bool = False):
    """Core asynchronous logic for scraping and parsing.

    language="auto" (the default) parses every supported language, routing builders and
    resolvers per-file by extension. Passing an explicit language restricts parsing to it.
    """

    # Ensure .tostr directory exists
    tostr_dir = target_path / ".tostr"
    tostr_dir.mkdir(exist_ok=True)

    # Save language to config.toml
    config_path = tostr_dir / "config.toml"
    config_content = f"[project]\nlanguage = \"{language}\"\n"
    with open(config_path, 'w') as f:
        f.write(config_content)

    # Write default ignores. In auto mode, lay down every supported language's
    # ignore template so things like venv/ (python) and target/ (java) are covered.
    if language == "auto":
        for lang in LanguageProvider.language_map:
            _write_default_ignore(target_path, lang)
    else:
        _write_default_ignore(target_path, language)

    # Parse and resolve AST
    parser = await _build_ast_async(target_path, use_cache=use_cache, progress_tracker=progress_tracker, no_llm=no_llm)
        
    # Write Cache
    parser.registry.save_to_cache()

def resolve_uid_to_id(uid: str, project_path: Path) -> str:
    """Simplifies UID to ID resolution by querying the database directly."""
    _verify_db_exists(project_path)
    db = SQLiteCache(project_path / ".tostr" / "cache.db")
    with db.get_connection() as conn:
        row = conn.execute("SELECT id FROM structs WHERE uid = ?", (uid,)).fetchone()
        return row[0] if row else None
    
async def inspect_async(struct_ids: list[str], project_path: Path, include_body: bool = False):
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
        
        results.append(tost.dump(struct_obj, include_body=include_body))
        
    return results

async def skeleton_async(subpath: str, project_path: Path, depth: int = 7, files_only: bool = False):
    _verify_db_exists(project_path)
    
    db = SQLiteCache(project_path / ".tostr" / "cache.db")
    registry = Registry(db=db, project_path=project_path)
    
    subpath = Path(project_path / subpath)
    logger.debug(f"Loading subtree for path: {subpath}")
    
    registry.load_filepath(subpath)
    if not registry.files:
        raise FileNotFoundError(f"No files found matching path '{subpath}'.")
    
    return tost.dump_skeleton(registry.root, depth=depth, files_only=files_only)

active_tasks = {}

async def watch_async(target_path: Path, stop_event: asyncio.Event = None):
    # Resolve up front so symlinked roots (e.g. macOS /var -> /private/var) match the
    # already-resolved paths that awatch emits; otherwise relative_to() below would raise.
    target_path = Path(target_path).resolve()
    _verify_db_exists(target_path)
    try:
        llm = get_llm_client()
    except APIKeyError:
        llm = None
        logger.warning("No API key found; watcher running in no-LLM mode (embeddings only, descriptions skipped).")
    config = ProjectConfig(target_path)

    logger.info("Starting Listener")
    try:
        async for changes in awatch(target_path, stop_event=stop_event):
            for change_type, raw_path in changes:
                # Keep the absolute path: process_single_file opens the file directly, and
                # the MCP server's cwd is not the project root, so a relative path can't be read.
                abs_path = Path(raw_path).resolve()
                if config.is_ignored(abs_path):
                    continue
                try:
                    display_path = abs_path.relative_to(target_path)
                except ValueError:
                    display_path = abs_path

                existing_task = active_tasks.get(abs_path)
                if existing_task and not existing_task.done():
                    existing_task.cancel()

                match change_type:
                    case Change.deleted:
                        logger.info(f"File deleted: {display_path}")
                        new_task = asyncio.create_task(
                            process_file_deletion(target_path, abs_path)
                        )
                    case Change.added:
                        logger.info(f"File added: {display_path}")
                        new_task = asyncio.create_task(
                            process_single_file(target_path, abs_path, llm)
                        )
                    case _:  # Change.modified
                        logger.info(f"File modified: {display_path}")
                        new_task = asyncio.create_task(
                            process_single_file(target_path, abs_path, llm)
                        )

                active_tasks[abs_path] = new_task

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
            results.append(SearchResult(id=row['id'], uid=row['uid'], type=row['type'], distance=row['distance']))
            if len(results) >= top_k:
                break
                
        return results

async def process_file_deletion(project_dir: Path, filepath: Path):
    """Watcher deletion path: purge a removed file (or directory) and everything beneath it from
    the cache, so no ghost structs/edges/vectors linger. The path is relativized the same way the
    builders store it; `delete_path_subtree` cascades for directories via a path-prefix match."""
    logger.info(f"Processing deletion {filepath}")
    try:
        db = SQLiteCache(project_dir / ".tostr" / "cache.db")
        registry = Registry(db=db, use_cache=True, project_path=project_dir)
        rel_path = str(registry.relative_to_project(Path(filepath)))
        removed = await asyncio.to_thread(registry.delete_path_subtree, rel_path)
        logger.debug(f"✅ Deleted {len(removed)} struct(s) for {rel_path}")
    except asyncio.CancelledError:
        logger.warning(f"Deletion task cancelled on {filepath}")
    except Exception as e:
        logger.warning(f"Error deleting {filepath}: {e}")
    finally:
        if active_tasks.get(filepath) == asyncio.current_task():
            del active_tasks[filepath]


async def process_single_file(project_dir: Path, filepath: Path, llm_client: LLMClient):
    logger.info(f"Processing file {filepath}")
    try:
        db = SQLiteCache(project_dir / ".tostr" / "cache.db")
        
        registry = Registry(db=db, use_cache=True, project_path=project_dir)
        embedder = get_cached_embedding_client()
        parser = BaseParser(filepath, llm=llm_client, embedder=embedder, registry=registry)
        
        parser.parse_path(filepath)

        # Nothing parsed (unsupported/ignored file) — don't prune, or we'd wipe the path's structs.
        if registry.root is None:
            logger.debug(f"No parseable struct produced for {filepath}; skipping cache write")
            return

        parser.resolve_dependencies()

        # Scope the diff-prune to exactly this file's relative path so removed/renamed members are
        # purged. Matches what the builders store (BaseFileBuilder.from_path relativizes the path).
        prune_paths = [str(registry.relative_to_project(Path(filepath)))]

        await asyncio.to_thread(registry.save_to_cache, stale=True, prune_paths=prune_paths)
        logger.debug("Wrote Cache w/ stale descriptions")

        # resolve the descriptions and do the second cache write
        await parser.resolve_descriptions_async()
        await asyncio.to_thread(registry.save_to_cache, prune_paths=prune_paths)
        logger.debug("Wrote Cache w/ resolved descriptions")
        
        logger.debug(f"✅ Processed file {filepath}")
        
    except asyncio.CancelledError:
        logger.warning(f"Task cancelled on {filepath}")
    except Exception as e:
        logger.warning(f"Error processing file {filepath}: {e}")
    finally:
        if active_tasks.get(filepath) == asyncio.current_task():
            del active_tasks[filepath]