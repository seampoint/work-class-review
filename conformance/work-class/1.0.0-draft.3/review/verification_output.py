"""Select fresh verification output without writing into guarded source trees."""
from pathlib import Path

def output_directory(path: Path, repository: Path) -> Path:
    selected, root = path.expanduser().resolve(), repository.resolve()
    if selected == root or selected in root.parents:
        raise ValueError("verification output must not be the repository or its ancestor")
    if selected.is_relative_to(root):
        relative = selected.relative_to(root)
        # runs may be a symlink to an external store; resolution above handles it.
        if not relative.parts or relative.parts[0] != "runs":
            raise ValueError("verification output inside the repository must be under runs")
    return selected


def fresh_output_file(path: Path, repository: Path) -> Path:
    """Validate the final filename too, including dangling basename symlinks.

    Callers still open with exclusive creation so validation cannot allow an
    existing evidence file to be overwritten between this check and the write.
    """
    if path.expanduser().is_symlink():
        raise ValueError("verification output file must not be a symlink")
    selected = output_directory(path, repository)
    if selected.exists() or selected.is_symlink():
        raise ValueError("verification output file must be fresh")
    return selected

