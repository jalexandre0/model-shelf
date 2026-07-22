"""Command-line interface for Model Shelf."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

from pathlib import Path

from model_shelf.config import load_config, writable_config_path, write_config
from model_shelf.detect import StorageCandidate, detect_storage_candidates
from model_shelf.resolver import (
    SUPPORTED_FORMATS,
    Config,
    StorageNotAvailableError,
    check_storage_available,
    detect_format,
    init_shelf,
    list_shelf_candidates,
    resolve_model,
)
from model_shelf.import_model import ImportResult, import_model
from model_shelf.dedup import DedupGroup, DedupResult, execute_dedup, find_duplicates
from model_shelf.search import find_models


def _fmt_size(n_bytes: int) -> str:
    size = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _print_result_pretty(repo_id: str, result) -> None:
    for c in result.checks:
        marker = "HIT" if c["result"] == "hit" else "miss"
        print(f"  {c['location']:<6} {c['root']:<48} {marker}")
    if result.status == "downloaded":
        print(f"  fetch  huggingface.co/{repo_id:<33} downloaded")
    print()
    print(f"  status      {result.status}")
    print(f"  source      {result.source}")
    print(f"  format      {result.format}")
    print(f"  path        {result.path}")


def _print_import_pretty(result: ImportResult) -> None:
    for c in result.checks:
        print(f"  {c.get('step', ''):<20} {c.get('detail', '')}")
    print()
    print(f"  status      {result.status}")
    print(f"  repo_id     {result.repo_id}")
    print(f"  format      {result.format}")
    print(f"  sha256      {result.sha256[:16]}...")
    if result.path:
        print(f"  path        {result.path}")
    print(f"  message     {result.message}")


def cmd_import(args: argparse.Namespace, cfg: Config) -> int:
    check_storage_available(cfg)
    result = import_model(
        cfg,
        Path(args.path),
        format=args.format,
        org=args.org,
        repo=args.repo,
        quant=args.quant,
        hardlink=not args.no_hardlink,
        dry_run=not args.execute,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_import_pretty(result)
    return 0


def cmd_resolve(args: argparse.Namespace, cfg: Config) -> int:
    if args.no_download:
        cfg.allow_downloads = False
    fmt = args.format or detect_format(args.repo_id)
    result = resolve_model(cfg, args.repo_id, format=fmt, quant=args.quant)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_result_pretty(args.repo_id, result)
    return 0 if result.status != "missing" else 1


def _format_choice_label(c: StorageCandidate) -> str:
    tag = "existing" if c.existing else "new"
    where = "external" if c.is_external else "internal"
    return f"[{where}] {c.label} ({tag})  —  {c.path}"


def _pick_candidate_interactively(
    candidates: list[StorageCandidate],
) -> Path | None:
    import questionary

    choices = [questionary.Choice(_format_choice_label(c), value=c.path) for c in candidates]
    choices.append(questionary.Choice("Enter a custom path...", value="__custom__"))

    chosen = questionary.select(
        "Where do you want your Model Shelf?",
        choices=choices,
    ).ask()

    if chosen is None:
        return None  # user hit Ctrl-C
    if chosen == "__custom__":
        path_str = questionary.path(
            "Enter shelf path:",
            default=str(Path.home() / ".cache" / "model-shelf" / "models"),
        ).ask()
        if not path_str:
            return None
        return Path(path_str).expanduser()
    return chosen


def _resolve_shelf_path(args: argparse.Namespace) -> Path | None:
    """Decide which shelf_root to use for `init`. Returns None on user-abort."""
    if args.path:
        return Path(args.path).expanduser().resolve()

    candidates = detect_storage_candidates()
    existing_external = [c for c in candidates if c.existing and c.is_external]
    external = [c for c in candidates if c.is_external]
    internal = next((c for c in candidates if not c.is_external), None)

    # Strong signal: exactly one external drive already has a ModelShelf —
    # use it without prompting.
    if len(existing_external) == 1:
        chosen = existing_external[0]
        print(f"model-shelf: using existing shelf at {chosen.path}")
        return chosen.path

    is_tty = sys.stdin.isatty()

    # Multiple existing external shelves — prompt to disambiguate, error if non-TTY.
    if len(existing_external) > 1:
        if not is_tty:
            print("error: multiple existing external shelves; specify a path explicitly:", file=sys.stderr)
            for c in existing_external:
                print(f"  - {c.path}", file=sys.stderr)
            return None
        picked = _pick_candidate_interactively(candidates)
        if picked is None:
            print("model-shelf: cancelled", file=sys.stderr)
        return picked

    # No existing external shelves.
    # If no external drives are connected, fall back to the internal default.
    if not external:
        if internal is None:
            print("error: could not determine a shelf location", file=sys.stderr)
            return None
        print(f"model-shelf: no external drives detected; using internal storage at {internal.path}")
        return internal.path

    # External drives present but none with an existing shelf — prompt.
    if not is_tty:
        if internal is None:
            print("error: not interactive and no shelf location could be inferred", file=sys.stderr)
            return None
        print(f"model-shelf: not interactive; using internal storage at {internal.path}", file=sys.stderr)
        return internal.path

    picked = _pick_candidate_interactively(candidates)
    if picked is None:
        print("model-shelf: cancelled", file=sys.stderr)
    return picked


def cmd_init(args: argparse.Namespace, cfg: Config) -> int:
    chosen = _resolve_shelf_path(args)
    if chosen is None:
        return 1
    new_root = chosen.expanduser().resolve()
    cfg.shelf_root = new_root
    created = init_shelf(cfg)

    config_path = writable_config_path(args.config)
    if args.path:
        # Explicit path → pin it in the config.
        write_config(
            config_path,
            shelf_root=new_root,
            allow_downloads=cfg.allow_downloads,
        )
        print(f"model-shelf: wrote {config_path}")
        print(f"            shelf_root = {new_root}  (pinned)")
    else:
        # Auto-detected → don't pin. Discovery will find this shelf at runtime,
        # which means swapping drives (or renaming) Just Works.
        print(f"model-shelf: using {new_root}  (auto-discovered, not pinned in config)")

    if not created:
        print(f"model-shelf: shelf at {cfg.shelf_root} already initialized")
        return 0
    print(f"model-shelf: initialized shelf at {cfg.shelf_root}")
    for path in created:
        print(f"  + {path}")
    return 0


def cmd_manifest(args: argparse.Namespace, cfg: Config) -> int:
    """Show or rebuild the shelf manifest."""
    from model_shelf.manifest import (
        ManifestResult,
        load_manifest,
        rebuild_manifest,
    )
    if args.rebuild:
        result = rebuild_manifest(cfg)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"Rebuilt manifest: {result.models_count} models tracked")
            for err in result.errors:
                print(f"  warning: {err}", file=sys.stderr)
        return 0 if result.status == "ok" else 1
    else:
        data = load_manifest(cfg.shelf_root)
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            models = data.get("models", {})
            print(f"Manifest: {len(models)} models tracked")
            print(f"Updated:   {data.get('updated', 'never')}")
            for repo_id in sorted(models):
                entry = models[repo_id]
                sha = entry.get("sha256", "")[:8]
                print(f"  [{entry.get('format', '?')}] {repo_id}  sha256={sha}...")
        return 0


def cmd_dedup(args: argparse.Namespace, cfg: Config) -> int:
    """Find and deduplicate identical model files."""
    result = find_duplicates(
        cfg,
        include_ollama=args.include_ollama,
        include_hf_cache=args.include_hf_cache,
    )
    if not args.execute:
        # Dry-run (default)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            _print_dedup_report(result)
        return 0

    dedup_result = execute_dedup(cfg, result)
    if args.json:
        print(json.dumps(dedup_result.to_dict(), indent=2))
    else:
        _print_dedup_report(dedup_result)
    return 0


def _print_dedup_report(result: DedupResult) -> None:
    if not result.groups:
        print("No duplicates found.")
        return
    print(f"Found {len(result.groups)} duplicate group(s)")
    total_savings = result.potential_savings_bytes
    if total_savings >= 1e9:
        print(f"  Potential savings: {total_savings / 1e9:.2f} GB")
    else:
        print(f"  Potential savings: {total_savings / 1e6:.1f} MB")
    if getattr(result, 'hardlinks_created', 0):
        print(f"  Hardlinks created: {result.hardlinks_created}")
    if getattr(result, 'skipped_cross_fs', 0):
        print(f"  Skipped (cross-fs):  {result.skipped_cross_fs}")
    if getattr(result, 'skipped_external_only', 0):
        print(f"  Skipped (external-only): {result.skipped_external_only}")
    for g in result.groups:
        print(f"\n  SHA256: {g.sha256[:16]}...  copies: {len(g.files)}  "
              f"waste: {g.duplicate_bytes / 1e6:.1f} MB")
        for i, f in enumerate(g.files):
            mark = " ← KEEP" if i == 0 else ""
            print(f"    {f}{mark}")


def cmd_audit(args: argparse.Namespace, cfg: Config) -> int:
    """Cross-reference manifest against filesystem."""
    from model_shelf.audit import AuditResult, run_audit  # noqa: PLC0415

    result = run_audit(cfg)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(
            f"Audit: {len(result.missing)} missing, {len(result.stale)} stale, "
            f"{len(result.untracked)} untracked"
        )
        if result.missing:
            print("\nMissing (manifest entry, files gone):")
            for repo_id in result.missing:
                print(f"  {repo_id}")
        if result.stale:
            print("\nStale (SHA256 mismatch):")
            for repo_id in result.stale:
                print(f"  {repo_id}")
        if result.untracked:
            print("\nUntracked (on disk, not in manifest):")
            for path in result.untracked:
                print(f"  {path}")
        if not result.missing and not result.stale and not result.untracked:
            print("Shelf is clean — no issues found.")
    return 0 if (
        not result.missing and not result.stale and not result.untracked
    ) else 1


def cmd_remove(args: argparse.Namespace, cfg: Config) -> int:
    """Remove a model from the shelf."""
    from model_shelf.remove import RemoveResult, remove_model  # noqa: PLC0415

    result = remove_model(cfg, args.repo_id, dry_run=not args.execute)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        action = "Would remove" if not args.execute else "Removed"
        if result.removed:
            print(f"{action}:")
            for p in result.removed:
                print(f"  {p}")
        if result.hardlinks_warn:
            print("Hardlink warnings:")
            for w in result.hardlinks_warn:
                print(f"  {w}")
        if not result.removed and not result.hardlinks_warn:
            print("No files to remove.")
    return 0


def _print_gc_report(result, *, dry_run: bool) -> None:
    prefix = "Would clean" if dry_run else "Cleaned"
    total = (
        len(result.incomplete_downloads)
        + len(result.orphaned_files)
        + len(result.empty_dirs)
    )
    print(
        f"{prefix} {total} items "
        f"({_fmt_size(result.total_reclaimable_bytes)} reclaimable):"
    )
    if result.incomplete_downloads:
        print(
            f"\n  Incomplete downloads ({len(result.incomplete_downloads)}):"
        )
        for p in result.incomplete_downloads:
            print(f"    {p}")
    if result.orphaned_files:
        print(f"\n  Orphaned files ({len(result.orphaned_files)}):")
        for p in result.orphaned_files:
            print(f"    {p}")
    if result.empty_dirs:
        print(f"\n  Empty directories ({len(result.empty_dirs)}):")
        for p in result.empty_dirs:
            print(f"    {p}")


def cmd_gc(args: argparse.Namespace, cfg: Config) -> int:
    """Find and clean up incomplete downloads, orphans, empty dirs."""
    from model_shelf.gc import GCResult, run_gc  # noqa: PLC0415
    from model_shelf.remove import cleanup_empty_parents  # noqa: PLC0415

    result = run_gc(cfg)
    if not args.execute:
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            _print_gc_report(result, dry_run=True)
        return 0

    # --execute path
    removed_count = 0
    removed_bytes = 0

    # Remove orphaned files
    for fpath_str in result.orphaned_files:
        fpath = Path(fpath_str)
        try:
            st = fpath.stat()
            os.unlink(fpath)
            removed_count += 1
            removed_bytes += st.st_size
        except OSError:
            pass

    # Remove incomplete download dirs
    for dpath_str in result.incomplete_downloads:
        dpath = Path(dpath_str)
        try:
            shutil.rmtree(dpath)
        except OSError:
            pass

    # Remove empty dirs (post-order, deepest first)
    empty_sorted = sorted(
        result.empty_dirs, key=lambda p: -len(Path(p).parts)
    )
    for dpath_str in empty_sorted:
        dpath = Path(dpath_str)
        try:
            if dpath.is_dir() and not any(dpath.iterdir()):
                dpath.rmdir()
        except OSError:
            pass

    # Clean up empty parent dirs after orphan/incomplete removal
    for fpath_str in result.orphaned_files:
        cleanup_empty_parents(cfg.shelf_root, Path(fpath_str).parent)
    for dpath_str in result.incomplete_downloads:
        cleanup_empty_parents(cfg.shelf_root, Path(dpath_str))

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_gc_report(result, dry_run=False)
        print(
            f"Removed {removed_count} files "
            f"({_fmt_size(removed_bytes)} reclaimed)"
        )
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    """Run the standalone migration script — scan, dedup, import."""
    import runpy
    from pathlib import Path as _Path
    script = _Path(__file__).resolve().parent.parent.parent / "scripts" / "model-shelf-migrate"
    sys.argv = [
        str(script),
        *(["--json"] if args.json else []),
        *(["--execute"] if args.execute else []),
    ]
    runpy.run_path(str(script), run_name="__main__")
    return 0


def cmd_find(args: argparse.Namespace, cfg: Config) -> int:
    results = find_models(args.query, format=args.format, limit=args.limit)
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
        return 0 if results else 1
    if not results:
        print("(no results)")
        return 1
    for r in results:
        print(f"  [{r.format:<11}] {r.repo_id:<55} {r.downloads:>10,} downloads")
    return 0


def _print_shelf_contents(root: Path) -> None:
    """Walk publisher/repo nesting and list files/dirs at each level."""
    for fmt in SUPPORTED_FORMATS:
        sub = root / fmt
        print(f"\n  {fmt}/")
        if not sub.exists():
            print("    (empty)")
            continue
        publishers = sorted(
            p for p in sub.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
        if not publishers:
            print("    (empty)")
            continue
        for publisher in publishers:
            repos = sorted(
                r for r in publisher.iterdir()
                if r.is_dir() and not r.name.startswith("._")
            )
            if not repos:
                continue
            for repo in repos:
                if fmt == "gguf":
                    files = sorted(
                        f for f in repo.glob("*.gguf") if not f.name.startswith("._")
                    )
                    for f in files:
                        print(
                            f"    {publisher.name}/{repo.name}/{f.name}  "
                            f"({_fmt_size(f.stat().st_size)})"
                        )
                else:
                    print(f"    {publisher.name}/{repo.name}/")


def cmd_list(args: argparse.Namespace, cfg: Config) -> int:
    check_storage_available(cfg)
    candidates = list_shelf_candidates(cfg)
    primary = cfg.shelf_root
    for i, root in enumerate(candidates):
        tag = "primary" if root == primary or root.resolve() == primary.resolve() else "additional"
        if i > 0:
            print()
        print(f"shelf  {root}  ({tag})")
        _print_shelf_contents(root)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="model-shelf",
        description="Local-first resolver for Hugging Face models (gguf, mlx, safetensors).",
    )
    parser.add_argument(
        "--config",
        help="path to config.toml (default: $MODEL_SHELF_CONFIG or ./config.toml)",
        default=None,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_resolve = sub.add_parser("resolve", help="resolve a model to a local path")
    p_resolve.add_argument("repo_id", help='e.g. "Qwen/Qwen3-14B-GGUF"')
    p_resolve.add_argument(
        "--format",
        choices=SUPPORTED_FORMATS,
        default=None,
        help="model format (auto-detected from repo_id if omitted)",
    )
    p_resolve.add_argument(
        "--quant",
        default=None,
        help='quantization tag, required for gguf (e.g. "Q4_K_M")',
    )
    p_resolve.add_argument(
        "--no-download",
        action="store_true",
        help="never reach out to Hugging Face, even on a cache miss",
    )
    p_resolve.add_argument("--json", action="store_true", help="emit JSON")

    sub.add_parser("list", help="list models on the curated shelf")

    p_find = sub.add_parser(
        "find",
        help="search Hugging Face Hub for models matching a query",
    )
    p_find.add_argument("query", help='e.g. "qwen 3 4b mlx 4-bit"')
    p_find.add_argument(
        "--format",
        choices=SUPPORTED_FORMATS,
        default=None,
        help="filter to a single format",
    )
    p_find.add_argument("--limit", type=int, default=10, help="max results (default 10)")
    p_find.add_argument("--json", action="store_true", help="emit JSON")

    p_manifest = sub.add_parser("manifest", help="show or rebuild the shelf manifest")
    p_manifest.add_argument(
        "--rebuild", action="store_true",
        help="re-scan the shelf and rebuild manifest.json",
    )
    p_manifest.add_argument("--json", action="store_true", help="emit JSON")

    p_dedup = sub.add_parser("dedup", help="find and deduplicate identical model files")
    p_dedup.add_argument(
        "--include-ollama", action="store_true",
        help="cross-reference Ollama blobs (~/.ollama/models/blobs/)",
    )
    p_dedup.add_argument(
        "--include-hf-cache", action="store_true",
        help="cross-reference HuggingFace cache blobs",
    )
    p_dedup.add_argument(
        "--dry-run", action="store_true", default=True,
        help="scan and report without hardlinking (default)",
    )
    p_dedup.add_argument(
        "--execute", action="store_true",
        help="actually create hardlinks",
    )
    p_dedup.add_argument("--json", action="store_true", help="emit JSON")

    p_import = sub.add_parser("import", help="import a local model into the shelf")
    p_import.add_argument("path", help="path to .gguf file or model directory")
    p_import.add_argument(
        "--format", choices=SUPPORTED_FORMATS, default=None,
        help="model format (auto-detected if omitted)",
    )
    p_import.add_argument("--org", default=None, help="override publisher/org name")
    p_import.add_argument("--repo", default=None, help="override repo/model name")
    p_import.add_argument(
        "--quant", default=None,
        help="quant tag for GGUF (auto-detected if omitted)",
    )
    p_import.add_argument(
        "--no-hardlink", action="store_true",
        help="always copy, never hardlink (even on same filesystem)",
    )
    p_import.add_argument(
        "--dry-run", action="store_true", default=True,
        help="compute and report without writing (default)",
    )
    p_import.add_argument(
        "--execute", action="store_true",
        help="actually perform the import",
    )
    p_import.add_argument("--json", action="store_true", help="emit JSON")

    p_audit = sub.add_parser("audit", help="cross-check manifest vs filesystem")
    p_audit.add_argument("--json", action="store_true", help="emit JSON")

    p_remove = sub.add_parser("remove", help="remove a model from the shelf")
    p_remove.add_argument("repo_id", help='e.g. "Qwen/Qwen3-14B-GGUF"')
    p_remove.add_argument(
        "--dry-run", action="store_true", default=True,
        help="show what would be removed without deleting (default)",
    )
    p_remove.add_argument(
        "--execute", action="store_true",
        help="actually delete the model",
    )
    p_remove.add_argument("--json", action="store_true", help="emit JSON")

    p_gc = sub.add_parser(
        "gc", help="find and clean up incomplete downloads, orphans, empty dirs"
    )
    p_gc.add_argument(
        "--dry-run", action="store_true", default=True,
        help="scan and report without deleting (default)",
    )
    p_gc.add_argument(
        "--execute", action="store_true",
        help="actually delete incomplete/orphaned files",
    )
    p_gc.add_argument("--json", action="store_true", help="emit JSON")

    p_migrate = sub.add_parser(
        "migrate", help="scan, dedup, and import models from scattered locations"
    )
    p_migrate.add_argument(
        "--dry-run", action="store_true", default=True,
        help="scan and report without importing (default)",
    )
    p_migrate.add_argument(
        "--execute", action="store_true",
        help="actually import models into the shelf",
    )
    p_migrate.add_argument("--json", action="store_true", help="emit JSON")

    p_init = sub.add_parser(
        "init",
        help="create the shelf directory (optionally at a new path)",
    )
    p_init.add_argument(
        "path",
        nargs="?",
        default=None,
        help="shelf location (writes to config); omit to use existing config",
    )

    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    try:
        if args.command == "resolve":
            return cmd_resolve(args, cfg)
        if args.command == "import":
            return cmd_import(args, cfg)
        if args.command == "list":
            return cmd_list(args, cfg)
        if args.command == "init":
            return cmd_init(args, cfg)
        if args.command == "find":
            return cmd_find(args, cfg)
        if args.command == "manifest":
            return cmd_manifest(args, cfg)
        if args.command == "dedup":
            return cmd_dedup(args, cfg)
        if args.command == "audit":
            return cmd_audit(args, cfg)
        if args.command == "remove":
            return cmd_remove(args, cfg)
        if args.command == "gc":
            return cmd_gc(args, cfg)
        if args.command == "migrate":
            return cmd_migrate(args)
    except StorageNotAvailableError as e:
        print(f"model-shelf: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"model-shelf: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        # Catch HF API errors (RepositoryNotFoundError, RemoteEntryNotFoundError,
        # HTTPStatusError, etc.) and surface a one-line message instead of a
        # traceback. Last line of the message is usually the most informative.
        msg = str(e).strip().splitlines()[-1] if str(e).strip() else type(e).__name__
        print(f"model-shelf: {type(e).__name__}: {msg}", file=sys.stderr)
        return 3
    return 2


if __name__ == "__main__":
    sys.exit(main())
