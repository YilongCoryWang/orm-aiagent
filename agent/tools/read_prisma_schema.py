"""read_prisma_schema tool — read & parse schema.prisma."""
from langchain.tools import tool

from ._paths import SCHEMA_PATH


@tool
def read_prisma_schema(_unused: str = "") -> str:
    """Read & parse schema.prisma — returns structured model/field info."""
    from main import parse_prisma_schema

    if not SCHEMA_PATH.exists():
        return f"❌ Schema not found: {SCHEMA_PATH}"
    models = parse_prisma_schema(SCHEMA_PATH.read_text())
    if not models:
        return "⚠ No models found."
    lines = [f"📄 {SCHEMA_PATH}", ""]
    for mn, fields in models.items():
        lines.append(f"model {mn} {{")
        for f in fields:
            flags = []
            if f["is_id"]:         flags.append("id")
            if f["is_updated_at"]: flags.append("updatedAt")
            if f["has_default"]:   flags.append("has_default")
            opt = "?" if f["optional"] else ""
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            lines.append(f"  {f['name']}: {f['type']}{opt}{flag_str}")
        lines.append("}")
    return "\n".join(lines)
