"""Shared path constants and helpers for tools."""
import pathlib

AGENT_DIR = pathlib.Path(__file__).resolve().parent.parent
NESTJS_PROJ_DIR = AGENT_DIR.parent / "demo-nestjs"
SCHEMA_PATH = NESTJS_PROJ_DIR / "prisma" / "schema.prisma"
PRODUCT_SRC = NESTJS_PROJ_DIR / "src" / "product"
DTO_DIR = PRODUCT_SRC / "dto"


def _resolve_product_path(relative_path: str) -> pathlib.Path:
    """Resolve a user-provided path to a file under src/product/."""
    p = relative_path.replace("\\", "/")
    for prefix in ["src/product/", "./", "/"]:
        if p.startswith(prefix):
            p = p[len(prefix):]
    return (PRODUCT_SRC / p).resolve()
