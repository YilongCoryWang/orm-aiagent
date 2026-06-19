"""detect_schema_changes tool — check if schema.prisma changed."""
from langchain.tools import tool


@tool
def detect_schema_changes(_unused: str = "") -> str:
    """Detect whether schema.prisma has changed. Call this FIRST."""
    from main import detect_changes
    result = detect_changes()
    return result or "✅ No changes detected."
