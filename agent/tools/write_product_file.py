"""write_product_file tool — write a file under src/product/."""
from langchain.tools import tool

from ._paths import _resolve_product_path, NESTJS_PROJ_DIR


@tool
def write_product_file(relative_path: str, content: str) -> str:
    """Write content to a file under demo-nestjs/src/product/.

    ⚠ IMPORTANT: Write the COMPLETE file content, not a diff.
    The tool overwrites the entire file.

    Before calling this:
    1. Call read_product_file to get the current content
    2. Make your modifications
    3. Call this tool with the FULL updated content
    """
    full = _resolve_product_path(relative_path)
    if not str(full).startswith(str(NESTJS_PROJ_DIR.resolve())):
        return f"❌ Refusing to write outside project: {full}"
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    return f"✅ Wrote {len(content)} bytes to {full.relative_to(NESTJS_PROJ_DIR)}"
