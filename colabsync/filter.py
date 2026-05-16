"""
File filtering logic for colabsync.

Precedence (first match wins / rejects):
  1. .colabignore  – always respected, user-explicit
  2. git ignore    – global + local .gitignore chain
  3. large-dir     – directory with ≥ LARGE_DIR_THRESHOLD entries is skipped,
                     with a warning if it is NOT already covered by gitignore
  4. size          – individual files > MAX_FILE_BYTES are skipped with a warning
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import gitignore_parser
from rich.console import Console

MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
LARGE_DIR_THRESHOLD = 1_000  # entries

console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_gitignore_matcher(root: Path) -> Callable[[str], bool]:
    """
    Return a matcher function that returns True when a path should be ignored
    by git.  Combines the global gitignore (if configured) with every
    .gitignore found in the tree under *root*.
    """
    matchers: list[Callable[[str], bool]] = []

    # Global gitignore
    global_gi = _global_gitignore_path()
    if global_gi and global_gi.exists():
        try:
            matchers.append(gitignore_parser.parse_gitignore(global_gi))
        except Exception:
            pass

    # Walk the tree and collect all .gitignore files
    for dirpath, dirnames, filenames in os.walk(root):
        if ".gitignore" in filenames:
            gi_path = Path(dirpath) / ".gitignore"
            try:
                matchers.append(gitignore_parser.parse_gitignore(gi_path, base_dir=dirpath))
            except Exception:
                pass
        # Prune .git from the walk
        dirnames[:] = [d for d in dirnames if d != ".git"]

    def matches(path: str) -> bool:
        return any(m(path) for m in matchers)

    return matches


def _build_colabignore_matcher(root: Path) -> Callable[[str], bool] | None:
    colabignore = root / ".colabignore"
    if not colabignore.exists():
        return None
    try:
        return gitignore_parser.parse_gitignore(colabignore, base_dir=str(root))
    except Exception:
        return None


def _global_gitignore_path() -> Path | None:
    """Return the path configured in git's core.excludesFile, if any."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "config", "--global", "core.excludesFile"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        path_str = result.stdout.strip()
        if path_str:
            return Path(os.path.expanduser(path_str))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class FileFilter:
    """
    Decides whether a given path should be synced.

    Build once per session; the gitignore matchers are cached.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._git_matches = _build_gitignore_matcher(self.root)
        self._colab_matches = _build_colabignore_matcher(self.root)
        self._warned_large_dirs: set[Path] = set()

    def refresh(self) -> None:
        """Re-read all ignore files (call after a .gitignore/.colabignore change)."""
        self._git_matches = _build_gitignore_matcher(self.root)
        self._colab_matches = _build_colabignore_matcher(self.root)

    # ------------------------------------------------------------------

    def should_sync(self, path: Path) -> bool:
        """
        Return True if *path* should be sent to Colab.

        Side-effects: emits warnings to stderr via Rich when files are dropped
        due to the large-dir heuristic or the size limit.
        """
        path = path.resolve()
        path_str = str(path)

        # 1. .colabignore
        if self._colab_matches and self._colab_matches(path_str):
            return False

        # 2. git ignores
        if self._git_matches(path_str):
            return False

        # 3. Large-dir heuristic – check every ancestor directory
        for parent in path.parents:
            if parent == self.root or not parent.is_relative_to(self.root):
                break
            if self._is_large_dir(parent):
                return False

        # 4. File size
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                console.print(
                    f"[yellow]skip[/yellow] [dim]{path.relative_to(self.root)}[/dim] "
                    f"[dim](> 2 MB)[/dim]"
                )
                return False
        except OSError:
            return False

        return True

    def should_sync_dir(self, directory: Path) -> bool:
        """
        Return False when an entire directory should be skipped.
        Used by the watcher to avoid descending into excluded trees.
        """
        directory = directory.resolve()
        dir_str = str(directory)

        if self._colab_matches and self._colab_matches(dir_str):
            return False
        if self._git_matches(dir_str):
            return False
        if self._is_large_dir(directory):
            return False
        return True

    # ------------------------------------------------------------------
    # Internals

    def _is_large_dir(self, directory: Path) -> bool:
        try:
            entries = list(directory.iterdir())
        except OSError:
            return False

        if len(entries) < LARGE_DIR_THRESHOLD:
            return False

        # Large dir detected – warn if git doesn't already know about it
        if directory not in self._warned_large_dirs:
            self._warned_large_dirs.add(directory)
            rel = directory.relative_to(self.root)
            git_ignores_it = self._git_matches(str(directory))
            if not git_ignores_it:
                console.print(
                    f"[yellow]warn[/yellow]  [bold]{rel}[/bold] has "
                    f"{len(entries):,} entries and is not in .gitignore – "
                    f"skipping it anyway. Consider adding it to .gitignore."
                )
            else:
                console.print(
                    f"[dim]skip[/dim]  [dim]{rel}[/dim] "
                    f"[dim](large dir, {len(entries):,} entries)[/dim]"
                )
        return True
