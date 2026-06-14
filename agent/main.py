"""
ORM Schema Watcher — auto-detects prisma/schema.prisma changes,
syncs NestJS DTOs (deterministic), then uses an LLM Agent to analyze
and fix cross-file impacts in Service / Controller / Module.

Usage:
    python main.py              # Auto-sync: detect → DTO → agent cross-file → migrate
    python main.py --agent      # Interactive LangChain agent mode

Architecture:
    ┌─ Deterministic ──────────────────────────────────────────┐
    │  detect_changes()  →  sync_dto_for_model()               │
    │  (cache diff)         (Prisma type → class-validator map)│
    └──────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
    Schema diff                   DTOs regenerated
                                        │
    ┌─ Agent-driven ────────────────────▼──────────────────────┐
    │  run_cross_file_analysis()                               │
    │  - Reads schema diff                                     │
    │  - Searches src/product/ for affected field references   │
    │  - Reads service/controller files                        │
    │  - Determines what needs changing (semantic reasoning)   │
    │  - Applies fixes                                         │
    └──────────────────────────────────────────────────────────┘
         │
         ▼
    prisma generate  →  prisma migrate dev  (deterministic)
"""

from dotenv import load_dotenv
import os
import subprocess
import re
import sys
import pathlib
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
load_dotenv()

AGENT_DIR = pathlib.Path(__file__).resolve().parent
NESTJS_PROJ_DIR = AGENT_DIR.parent / "nestjs-proj"
SCHEMA_PATH = NESTJS_PROJ_DIR / "prisma" / "schema.prisma"
PRODUCT_SRC = NESTJS_PROJ_DIR / "src" / "product"
DTO_DIR = PRODUCT_SRC / "dto"
CACHE_DIR = AGENT_DIR / ".schema_cache"


def create_llm():
    """Factory: returns the configured LLM instance.

    Controlled by environment variables:

    ┌─────────────────┬──────────────────────────────────────────────┐
    │ LLM_PROVIDER    │ deepseek (default)  → DeepSeek API           │
    │                 │ ollama              → local Ollama server    │
    ├─────────────────┼──────────────────────────────────────────────┤
    │ DeepSeek:                                                      │
    │   DEEPSEEK_API_KEY  (required)                                 │
    │   DEEPSEEK_MODEL    (default: deepseek-v4-flash)               │
    ├─────────────────┼──────────────────────────────────────────────┤
    │ Ollama:                                                        │
    │   OLLAMA_BASE_URL   (default: http://localhost:11434)          │
    │   OLLAMA_MODEL      (default: qwen2.5:7b)                      │
    └─────────────────┴──────────────────────────────────────────────┘
    """
    provider = os.getenv("LLM_PROVIDER", "deepseek").lower()

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError(
                "langchain-ollama is not installed. "
                "Run: pip install langchain-ollama"
            )
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=0,
        )

    # Default: DeepSeek (OpenAI-compatible)
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY not set. "
            "Set it in .env or switch to LLM_PROVIDER=ollama."
        )
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        api_key=api_key,
        base_url="https://api.deepseek.com/v1",
        extra_body={"thinking": {"type": "disabled"}},
    )

# ---------------------------------------------------------------------------
# Prisma schema → class-validator decorator mapping
# ---------------------------------------------------------------------------
PRISMA_TYPE_MAP = {
    "String":   ("IsString",     []),
    "Int":      ("IsInt",        []),
    "Float":    ("IsNumber",     ["Type(() => Number)"]),
    "Boolean":  ("IsBoolean",    ["Type(() => Boolean)"]),
    "DateTime": ("IsDateString", []),
}


def _has_attr(attributes: str, name: str) -> bool:
    return bool(re.search(rf"@{re.escape(name)}\b", attributes))


# ---------------------------------------------------------------------------
# Schema parser
# ---------------------------------------------------------------------------

def parse_prisma_schema(schema_text: str) -> dict[str, list[dict]]:
    """Parse a Prisma schema string → {model_name: [field_dict, ...]}.

    Each field dict: {name, type, optional, attributes, is_id, is_updated_at, has_default}
    """
    models: dict[str, list[dict]] = {}
    current_model: Optional[str] = None
    brace_depth = 0

    for raw_line in schema_text.splitlines():
        line = raw_line.strip()

        if m := re.match(r"^model\s+(\w+)\s*\{", line):
            current_model = m.group(1)
            models[current_model] = []
            brace_depth = 1
            continue

        if current_model is not None:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                current_model = None
                continue

            fm = re.match(r"^(\w+)\s+(\w+)(\?)?\s*(.*?)$", line)
            if not fm:
                continue

            name, ftype, optional, attrs = fm.groups()
            attrs = (attrs or "").strip()
            models[current_model].append({
                "name":          name,
                "type":          ftype,
                "optional":      bool(optional),
                "attributes":    attrs,
                "is_id":         _has_attr(attrs, "id"),
                "is_updated_at": _has_attr(attrs, "updatedAt"),
                "has_default":   _has_attr(attrs, "default"),
            })

    return models


def prisma_type_to_ts(ptype: str) -> str:
    return {
        "String": "string", "Int": "number", "Float": "number",
        "Boolean": "boolean", "DateTime": "string",
    }.get(ptype, "string")


# ---------------------------------------------------------------------------
# DTO generator (deterministic)
# ---------------------------------------------------------------------------

def build_dto_class_body(model_name: str, fields: list[dict]) -> tuple[str, str]:
    """Generate (import_block, class_block) for a Create{Model}Dto."""
    used_validators: set[str] = set()
    used_transformer = False
    prop_lines: list[str] = []
    comment_lines: list[str] = []

    for f in fields:
        if f["is_id"] or f["is_updated_at"]:
            continue

        prisma_type = f["type"]
        is_optional = f["optional"] or f["has_default"]

        validator, extras = PRISMA_TYPE_MAP.get(prisma_type, ("IsString", []))
        used_validators.add(validator)
        if "Type" in str(extras):
            used_transformer = True

        decorators: list[str] = []
        if is_optional:
            decorators.append("@IsOptional()")
            used_validators.add("IsOptional")
        decorators.append(f"@{validator}()")
        if validator == "IsString":
            used_validators.update(["MinLength", "MaxLength"])
            decorators.extend(["@MinLength(2)", "@MaxLength(200)"])
        if validator in ("IsInt", "IsNumber"):
            used_validators.add("Min")
            decorators.append("@Min(0)")
        for e in extras:
            decorators.append(f"@{e}")

        ts_type = prisma_type_to_ts(prisma_type)
        optional_mark = "?" if is_optional else "!"
        comment_lines.append(
            f" * - {f['name']}: {prisma_type}"
            f"{' (optional)' if is_optional else ''}"
        )

        for d in decorators:
            prop_lines.append(f"  {d}")
        prop_lines.append(f"  {f['name']}{optional_mark}: {ts_type};")
        prop_lines.append("")

    validator_list = sorted(used_validators)
    import_block = f"import {{ {', '.join(validator_list)} }} from 'class-validator';"
    if used_transformer:
        import_block += "\nimport { Type } from 'class-transformer';"

    class_name = f"Create{model_name}Dto"
    class_block = (
        f"/**\n"
        f" * {class_name} — generated from prisma/schema.prisma\n"
        f" *\n"
        f" * Fields:\n"
        + "\n".join(comment_lines) +
        f" */\n"
        f"export class {class_name} {{\n"
        + "\n".join(prop_lines) +
        f"}}"
    )

    return import_block, class_block


# ---------------------------------------------------------------------------
# Change detection (deterministic)
# ---------------------------------------------------------------------------

def get_cached_schema() -> Optional[str]:
    cache_file = CACHE_DIR / "schema_cache.txt"
    if cache_file.exists():
        return cache_file.read_text()
    return None


def save_schema_cache(schema_text: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "schema_cache.txt").write_text(schema_text)


def detect_changes() -> Optional[str]:
    """Check if schema.prisma changed vs the cached snapshot.

    Returns a diff summary string if changed, None if unchanged or first run.
    """
    if not SCHEMA_PATH.exists():
        print(f"❌ Schema file not found: {SCHEMA_PATH}")
        return None

    current = SCHEMA_PATH.read_text()
    cached = get_cached_schema()

    if cached is None:
        save_schema_cache(current)
        print("📝 First run — schema cached as baseline. No changes to process.")
        return None

    if current == cached:
        print("✅ No schema changes detected (cache comparison).")
        return None

    diff_lines = ["--- cached schema", "+++ current schema"]
    for line in cached.splitlines():
        diff_lines.append(f"-{line}")
    for line in current.splitlines():
        diff_lines.append(f"+{line}")
    diff_summary = "\n".join(diff_lines)

    # Enrich with git diff if available
    git_info = ""
    try:
        git_diff = subprocess.run(
            ["git", "diff", "--", str(SCHEMA_PATH)],
            capture_output=True, text=True, cwd=str(NESTJS_PROJ_DIR),
        )
        if git_diff.returncode == 0 and git_diff.stdout.strip():
            git_info = f"\n\n[Git diff]\n{git_diff.stdout.strip()}"
        else:
            staged = subprocess.run(
                ["git", "diff", "--cached", "--", str(SCHEMA_PATH)],
                capture_output=True, text=True, cwd=str(NESTJS_PROJ_DIR),
            )
            if staged.returncode == 0 and staged.stdout.strip():
                git_info = f"\n\n[Git diff --cached]\n{staged.stdout.strip()}"
    except FileNotFoundError:
        pass

    return f"⚠ Schema changed vs cached baseline.\n\n{diff_summary}{git_info}"


def build_schema_diff_summary(cached: str, current: str) -> str:
    """Build a human-readable summary of WHAT changed between two schema versions.

    Reports: fields added, fields removed, fields with type changes, fields renamed.
    """
    old_models = parse_prisma_schema(cached)
    new_models = parse_prisma_schema(current)

    lines: list[str] = []
    all_models = set(old_models.keys()) | set(new_models.keys())

    for mn in sorted(all_models):
        old_fields = {f["name"]: f for f in old_models.get(mn, [])}
        new_fields = {f["name"]: f for f in new_models.get(mn, [])}

        added = set(new_fields) - set(old_fields)
        removed = set(old_fields) - set(new_fields)
        common = set(new_fields) & set(old_fields)

        type_changes = []
        for name in common:
            if old_fields[name]["type"] != new_fields[name]["type"]:
                type_changes.append(
                    f"  {name}: {old_fields[name]['type']} → {new_fields[name]['type']}"
                )
            elif old_fields[name]["optional"] != new_fields[name]["optional"]:
                type_changes.append(
                    f"  {name}: {'optional' if old_fields[name]['optional'] else 'required'}"
                    f" → {'optional' if new_fields[name]['optional'] else 'required'}"
                )

        if added or removed or type_changes:
            lines.append(f"Model '{mn}' changes:")
            for a in sorted(added):
                f = new_fields[a]
                lines.append(f"  + added:   {a} ({f['type']}{'?' if f['optional'] else ''}"
                             f"{' @default' if f['has_default'] else ''}"
                             f"{' @id' if f['is_id'] else ''})")
            for r in sorted(removed):
                f = old_fields[r]
                lines.append(f"  - removed: {r} ({f['type']}{'?' if f['optional'] else ''})")
            for tc in type_changes:
                lines.append(f"  ~ changed: {tc}")

    return "\n".join(lines) if lines else "No structural changes detected."


# ---------------------------------------------------------------------------
# DTO sync (deterministic)
# ---------------------------------------------------------------------------

def sync_dto_for_model(model_name: str) -> tuple[bool, str]:
    """Generate & write CreateDto + UpdateDto for a given Prisma model."""
    if not SCHEMA_PATH.exists():
        return False, f"❌ Schema not found: {SCHEMA_PATH}"

    text = SCHEMA_PATH.read_text()
    models = parse_prisma_schema(text)

    if model_name not in models:
        return False, f"❌ Model '{model_name}' not found. Available: {list(models.keys())}"

    fields = models[model_name]
    import_block, class_block = build_dto_class_body(model_name, fields)

    kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", model_name).lower()
    class_name = f"Create{model_name}Dto"

    create_path = DTO_DIR / f"create-{kebab}.dto.ts"
    create_content = f"{import_block}\n\n{class_block}\n"
    DTO_DIR.mkdir(parents=True, exist_ok=True)
    create_path.write_text(create_content)

    update_path = DTO_DIR / f"update-{kebab}.dto.ts"
    update_content = (
        f"import {{ PartialType }} from '@nestjs/mapped-types';\n"
        f"import {{ {class_name} }} from './create-{kebab}.dto';\n"
        f"\n"
        f"/**\n"
        f" * Update{model_name}Dto — all fields optional.\n"
        f" * Inherits validation from {class_name} via PartialType.\n"
        f" */\n"
        f"export class Update{model_name}Dto extends PartialType({class_name}) {{}}\n"
    )
    update_path.write_text(update_content)

    msg = (
        f"✅ DTO synced for model '{model_name}':\n"
        f"   → {create_path}\n"
        f"   → {update_path}"
    )
    return True, msg


def run_prisma_command(cmd: list[str], label: str) -> tuple[bool, str]:
    """Run a prisma CLI command. Returns (success, output)."""
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(NESTJS_PROJ_DIR), timeout=120,
    )
    output = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()
    if result.returncode == 0:
        return True, f"✅ {label}\n{output}"
    else:
        return False, f"❌ {label} (exit {result.returncode})\n{output}"

# ===========================================================================
#  Agent-based cross-file impact analysis
# ===========================================================================
#  Why an Agent HERE (and not for DTO sync)?
#
#  DTO sync is a mechanical type→decorator mapping. Deterministic code is
#  faster and more reliable for that.
#
#  Cross-file impact analysis is DIFFERENT. A schema change like
#  "inStock Boolean → stock Int" requires:
#    - Understanding the SEMANTICS of the rename ("inStock" is a boolean
#      flag → "stock" is a quantity counter)
#    - Searching for ALL references to the old field across service,
#      controller, module
#    - Deciding WHICH references are affected (a variable might happen to
#      be named "inStock" without being the DB field)
#    - Determining the CORRECT fix for each reference (a boolean flag usage
#      can't just be replaced with an integer — the surrounding logic may
#      need to change too)
#
#  This "understand → search → reason → fix" loop is exactly what LLMs
#  are good at, and what scripts are bad at.
# ===========================================================================

# --- Cross-file tools ---

def _resolve_product_path(relative_path: str) -> pathlib.Path:
    """Resolve a path relative to src/product/."""
    # Strip leading src/product/ if the agent included it
    p = relative_path.replace("\\", "/")
    for prefix in ["src/product/", "./", "/"]:
        if p.startswith(prefix):
            p = p[len(prefix):]
    return (PRODUCT_SRC / p).resolve()


@tool
def search_in_product(query: str) -> str:
    """Search for a pattern (string literal or field name) across ALL files
    under nestjs-proj/src/product/ (excluding node_modules).

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


@tool
def read_product_file(relative_path: str) -> str:
    """Read the full content of a file under nestjs-proj/src/product/.

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


@tool
def write_product_file(relative_path: str, content: str) -> str:
    """Write content to a file under nestjs-proj/src/product/.

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

# --- Cross-file agent system prompt ---

CROSS_FILE_SYSTEM_PROMPT = """\
You are a code-analysis agent specializing in NestJS + Prisma projects.

## Your job

Given a Prisma schema change summary and the fact that DTOs have already been
regenerated, search for and fix ALL remaining references to changed fields in
the NestJS source files under src/product/.

## Workflow

1. **Understand the change** — read the schema diff/summary in the user message.
   Identify: fields added, fields removed, fields renamed, type changes.

2. **Search for references** — for EACH changed or removed field name, call
   `search_in_product` with the field name. Also search for related terms
   (camelCase variants, getter/setter patterns).

3. **Read affected files** — for each file with matches, call `read_product_file`
   to see the full context. DO NOT skip this step — you need surrounding code
   to understand whether a match is actually a field reference or an unrelated
   variable with the same name.

4. **Determine what needs changing** — for each match, decide:
   - Is this a direct reference to the DB field? → needs updating
   - Is it an unrelated variable? → skip
   - Does the surrounding logic depend on the OLD type/semantics? → may need
     a larger refactor (explain in your report, don't silently break logic)

5. **Apply fixes** — call `write_product_file` with the complete updated content.
   Make minimal, targeted changes — don't reformat or restructure unrelated code.

## Rules

- DO NOT modify DTO files (create-*.dto.ts, update-*.dto.ts). Those are already
  handled deterministically. Focus on: service, controller, module.
- When a field is RENAMED, update ALL references (variable names, destructuring,
  log messages) to use the new name.
- When a field TYPE changes (e.g., Boolean → Int), check if any logic assumes
  the old type (e.g., `if (product.inStock)` won't work with `stock: number`).
  Flag these as potential issues.
- Write COMPLETE file content to `write_product_file`, not diffs.
- Be concise in your final report: list each file changed and what you did.

## Output format

At the end of your analysis, output a summary:

```
## Cross-file impact analysis

### Files changed
- path/to/file.ts: description of change
- ...
### No changes needed in
- path/to/unchanged.ts: reason
### Warnings (things to check manually)
- potential issue description
```
"""

# --- Run the cross-file agent ---

def run_cross_file_analysis(diff: str, cached_schema: str, current_schema: str) -> None:
    """Run the LLM agent to analyze cross-file impact of schema changes.

    The agent searches src/product/ for affected code in Service, Controller,
    and Module files, then applies necessary fixes.
    """
    # Build a structured summary of what changed
    change_summary = build_schema_diff_summary(cached_schema, current_schema)

    cross_file_tools = [search_in_product, read_product_file, write_product_file]

    cross_file_agent = create_agent(
        create_llm(),
        cross_file_tools,
        system_prompt=CROSS_FILE_SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )

    # Build the task prompt with full context
    task_prompt = f"""The Prisma schema has changed. DTOs have already been regenerated.

## Schema change summary

{change_summary}

## Full diff

{diff}

## Your task

Search src/product/ for all code affected by these schema changes.
Focus on product.service.ts, product.controller.ts, and product.module.ts.
DO NOT modify DTO files (they are already updated).

For each affected file: read it, determine what needs changing, and apply the fix.
Report what you changed and any issues that need manual review."""

    config = {"configurable": {"thread_id": "cross-file-1"}}

    print("-" * 60)
    print("  🤖 Agent: Cross-file impact analysis")
    print("-" * 60)
    print()

    stream_input: dict = {"messages": [{"role": "user", "content": task_prompt}]}

    while True:
        interrupted = False
        for step in cross_file_agent.stream(stream_input, config, stream_mode="values"):
            if "__interrupt__" in step:
                interrupted = True
                interrupt = step["__interrupt__"][0]
                print(f"\n  🔧 Agent wants to call:")
                for req in interrupt.value["action_requests"]:
                    name = req["name"]
                    args = req["args"]
                    # Truncate long content in display
                    display_args = {}
                    for k, v in args.items():
                        if isinstance(v, str) and len(v) > 300:
                            display_args[k] = v[:150] + f"\n... ({len(v)} chars total) ...\n" + v[-150:]
                        else:
                            display_args[k] = v
                    print(f"     {name}({display_args})")
                # Auto-approve in auto-sync mode
                decisions = [{"type": "approve"} for _ in interrupt.value["action_requests"]]
                stream_input = Command(resume={"decisions": decisions})
            elif "messages" in step:
                msg = step["messages"][-1]
                # Print agent's text output (final report) nicely
                if hasattr(msg, "content") and isinstance(msg.content, str):
                    print(msg.content)
            else:
                pass

        if not interrupted:
            break

    print()
    print("-" * 60)
    print("  ✅ Cross-file analysis complete.")
    print("-" * 60)

# ===========================================================================
#  Auto-sync pipeline
# ===========================================================================

def auto_sync_all() -> None:
    """Full automated pipeline:
    detect → DTO sync (deterministic) → cross-file analysis (agent) → prisma commands
    """
    print("=" * 60)
    print("  ORM Schema Watcher — auto-sync mode")
    print(f"  Schema:  {SCHEMA_PATH}")
    print(f"  Product: {PRODUCT_SRC}")
    print("=" * 60)
    print()

    # Step 1: Detect changes
    diff = detect_changes()
    if diff is None:
        return  # No changes, or first run

    print(diff)
    print()

    # Remember old schema before we update the cache
    cached_schema = get_cached_schema() or ""
    current_schema = SCHEMA_PATH.read_text()

    # Step 2: Parse schema and identify models
    models = parse_prisma_schema(current_schema)
    print(f"📄 Found {len(models)} model(s) in schema: {list(models.keys())}")
    print()

    # Step 3: Deterministic DTO sync
    print("-" * 60)
    print("  ⚙  Step 1/3: DTO sync (deterministic)")
    print("-" * 60)
    for model_name in models:
        ok, msg = sync_dto_for_model(model_name)
        print(msg)
        print()

    # Update cache AFTER DTO sync succeeds
    save_schema_cache(current_schema)

    # Step 4: Agent-based cross-file impact analysis
    print("-" * 60)
    print("  🤖 Step 2/3: Cross-file analysis (Agent)")
    print("-" * 60)
    run_cross_file_analysis(diff, cached_schema, current_schema)

    # Step 5: prisma generate
    print("-" * 60)
    print("  ⚙  Step 3/3: Prisma commands")
    print("-" * 60)
    ok, msg = run_prisma_command(
        ["npx", "prisma", "generate"], "prisma generate"
    )
    print(msg)
    print()
    if not ok:
        print("⚠ Prisma generate failed — skipping migration.")
        return

    # Step 6: prisma migrate dev
    ok, msg = run_prisma_command(
        ["npx", "prisma", "migrate", "dev", "--name", "auto_sync"],
        "prisma migrate dev --name auto_sync",
    )
    print(msg)
    print()

    if ok:
        print("=" * 60)
        print("  ✅ Auto-sync complete.")
        print("     Review changes above and migration SQL in prisma/migrations/")
        print("=" * 60)
    else:
        print("=" * 60)
        print("  ⚠ Migration step had issues. Check output above.")
        print("=" * 60)

# ===========================================================================
#  Interactive agent mode (--agent flag)
# ===========================================================================

# Unified tools for interactive mode — includes both schema + cross-file tools
ALL_TOOLS = []

def _init_all_tools():
    """Lazily build the full tool list (needed because @tool decorator
    creates new objects each call with unique names — we define them once)."""
    global ALL_TOOLS
    if ALL_TOOLS:
        return ALL_TOOLS

    # These are the same @tool functions defined above; we wrap the core
    # helpers with @tool for the interactive agent.

    @tool
    def detect_schema_changes(_unused: str = "") -> str:
        """Detect whether schema.prisma has changed. Call this FIRST."""
        result = detect_changes()
        return result or "✅ No changes detected."

    @tool
    def read_prisma_schema(_unused: str = "") -> str:
        """Read & parse schema.prisma — returns structured model/field info."""
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

    @tool
    def sync_dto_with_schema(model_name: str) -> str:
        """Regenerate CreateDto + UpdateDto for a Prisma model from the current
        schema. This is the DETERMINISTIC sync — always prefer this for DTOs
        over manually generating TypeScript."""
        ok, msg = sync_dto_for_model(model_name)
        return msg

    @tool
    def run_npm_script(script_name: str) -> str:
        """Run an npm script in nestjs-proj/.
        Allowed: prisma:generate, prisma:migrate:dev, prisma:migrate:deploy, prisma:studio."""
        allowed = {"prisma:generate", "prisma:migrate:dev", "prisma:migrate:deploy", "prisma:studio"}
        if script_name not in allowed:
            return f"❌ Not allowed. Choices: {sorted(allowed)}"
        ok, msg = run_prisma_command(["npm", "run", script_name], script_name)
        return msg

    ALL_TOOLS = [
        detect_schema_changes,
        read_prisma_schema,
        sync_dto_with_schema,
        run_npm_script,
        search_in_product,       # cross-file
        read_product_file,       # cross-file
        write_product_file,      # cross-file
    ]
    return ALL_TOOLS


INTERACTIVE_SYSTEM_PROMPT = """\
You are an ORM Agent for a NestJS + Prisma project.

## Your capabilities

1. **Schema change detection** — `detect_schema_changes` to see if schema.prisma
   changed, `read_prisma_schema` to get the current model structure.

2. **DTO sync** — `sync_dto_with_schema('Product')` to deterministically
   regenerate the Create DTO from the Prisma schema. ALWAYS use this for DTO
   updates — never write DTOs manually.

3. **Cross-file impact analysis** — when schema fields change, use
   `search_in_product` to find all references, `read_product_file` to see
   context, and `write_product_file` to apply fixes to service/controller.

4. **Prisma commands** — `run_npm_script('prisma:generate')` and
   `run_npm_script('prisma:migrate:dev')`.

## Workflow for a full sync

1. `detect_schema_changes` — check what changed
2. `read_prisma_schema` — get current model structure
3. `sync_dto_with_schema` — regenerate DTOs (deterministic)
4. For each changed field: `search_in_product` → `read_product_file` → fix → `write_product_file`
5. `run_npm_script('prisma:generate')` — rebuild Prisma client
6. `run_npm_script('prisma:migrate:dev')` — create migration (only if structural changes)

Be concise. Explain each change before making it.
"""


def run_agent_mode() -> None:
    """Interactive LangChain agent with HumanInTheLoopMiddleware."""
    tools = _init_all_tools()

    agent = create_agent(
        create_llm(), tools, system_prompt=INTERACTIVE_SYSTEM_PROMPT,
        middleware=[
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "sync_dto_with_schema": True,
                    "write_product_file": True,
                    "run_npm_script": True,
                },
                description_prefix="Tool execution pending approval",
            ),
        ],
        checkpointer=InMemorySaver(),
    )

    print("\n" + "=" * 60)
    print("  ORM Agent — interactive mode")
    print("  Type 'quit' to exit")
    print("  Try: 'check for schema changes and sync everything'")
    print("=" * 60 + "\n")

    config = {"configurable": {"thread_id": "orm-agent-1"}}

    while True:
        try:
            user_input = input("\n🧑 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye.")
            break
        if user_input.lower() in ("quit", "exit"):
            print("👋 Goodbye.")
            break
        if not user_input:
            continue

        stream_input: dict = {"messages": [{"role": "user", "content": user_input}]}
        while True:
            interrupted = False
            for step in agent.stream(stream_input, config, stream_mode="values"):
                if "__interrupt__" in step:
                    interrupted = True
                    print("\n" + "=" * 60)
                    print("  ⏸  INTERRUPTED — Tool pending approval")
                    print("=" * 60)
                    interrupt = step["__interrupt__"][0]
                    for i, req in enumerate(interrupt.value["action_requests"]):
                        display_args = {}
                        for k, v in req["args"].items():
                            s = str(v)
                            display_args[k] = (s[:200] + "...") if len(s) > 200 else s
                        print(f"\n  #{i + 1}: {req['name']}({display_args})")
                    choice = input("\n  Approve? (y/n): ").strip().lower()
                    decisions = [
                        {"type": "approve" if choice == "y" else "reject"}
                        for _ in interrupt.value["action_requests"]
                    ]
                    stream_input = Command(resume={"decisions": decisions})
                elif "messages" in step:
                    step["messages"][-1].pretty_print()
            if not interrupted:
                break


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if "--agent" in sys.argv:
        run_agent_mode()
    else:
        auto_sync_all()


if __name__ == "__main__":
    main()
