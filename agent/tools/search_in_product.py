"""search_in_product tool — grep across src/product/."""
import subprocess

from langchain.tools import tool

from ._paths import PRODUCT_SRC, NESTJS_PROJ_DIR


@tool
def search_in_product(query: str) -> str:
    """Search for a pattern (string literal or field name) across ALL files
    under demo-nestjs/src/product/ (excluding node_modules).

    Returns matching file paths, line numbers, and the matching lines.

    Use this to find ALL references to a changed field or model name before
    deciding what to update.
    """
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.ts", query, str(PRODUCT_SRC)],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout.strip()
        if not output:
            return f"No matches found for '{query}' in src/product/"
        return f"Matches for '{query}' in src/product/:\n\n{output}"
    except FileNotFoundError:
        # Fallback: manual search
        results = []
        for ts_file in PRODUCT_SRC.rglob("*.ts"):
            try:
                for i, line in enumerate(ts_file.read_text().splitlines(), 1):
                    if query.lower() in line.lower():
                        rel = ts_file.relative_to(NESTJS_PROJ_DIR)
                        results.append(f"{rel}:{i}: {line.strip()}")
            except Exception:
                pass
        if not results:
            return f"No matches found for '{query}' in src/product/"
        return f"Matches for '{query}' in src/product/:\n\n" + "\n".join(results)
