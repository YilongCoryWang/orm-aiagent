"""read_product_file tool — read a file under src/product/."""
from langchain.tools import tool

from ._paths import _resolve_product_path, NESTJS_PROJ_DIR


@tool
def read_product_file(relative_path: str) -> str:
    """Read the full content of a file under demo-nestjs/src/product/.

    Example paths: 'product.service.ts', 'product.controller.ts',
                   'dto/create-product.dto.ts', 'product.module.ts'

    Use this AFTER search_in_product to read files that contain matches
    and understand the surrounding context before making changes.
    """
    full = _resolve_product_path(relative_path)
    if not str(full).startswith(str(NESTJS_PROJ_DIR.resolve())):
        return f"❌ Path escapes project: {full}"
    if not full.exists():
        return f"❌ File not found: {full}  (tried: {relative_path})"
    return full.read_text()
