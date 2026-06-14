# ORM Agent — Prisma Schema → NestJS full-stack auto-sync

Hybrid architecture: **deterministic code for mechanical tasks + LLM Agent for semantic reasoning**.

## Project layout

```
orm_agent/
├── agent/                          # Python auto-sync + LLM Agent
│   ├── main.py                     # Entry point (auto-sync default, --agent for interactive)
│   ├── pyproject.toml              # Deps: langchain[openai], langgraph, python-dotenv
│   │                               #   Optional: langchain-ollama (for local LLM)
│   ├── .env                        # LLM_PROVIDER (deepseek|ollama) + API keys
│   └── .schema_cache/              # Cached schema snapshot for change detection
│
├── nestjs-proj/                    # Demo NestJS app (the "managed" project)
│   ├── prisma/
│   │   ├── schema.prisma           # Source of truth — Product model
│   │   └── migrations/             # Prisma migration history
│   ├── src/
│   │   ├── product/
│   │   │   ├── dto/
│   │   │   │   ├── create-product.dto.ts   # Auto-generated from schema (deterministic)
│   │   │   │   └── update-product.dto.ts   # PartialType of Create — auto-follows
│   │   │   ├── product.service.ts          # CRUD + business logic (Agent-updated)
│   │   │   │                               #   Methods reference individual fields:
│   │   │   │                               #   findInStock, restockProduct (→ stock)
│   │   │   │                               #   findByCategory (→ category)
│   │   │   │                               #   findByPriceRange (→ price)
│   │   │   ├── product.controller.ts       # REST endpoints (Agent-updated)
│   │   │   │                               #   GET /products/in-stock
│   │   │   │                               #   GET /products/category/:category
│   │   │   │                               #   GET /products/price-range
│   │   │   │                               #   PATCH /products/:id/restock
│   │   │   └── product.module.ts
│   │   ├── prisma/
│   │   │   ├── prisma.service.ts           # PrismaClient + PrismaPg adapter
│   │   │   └── prisma.module.ts            # @Global() module
│   │   ├── app.module.ts
│   │   └── main.ts                         # Bootstrap, global ValidationPipe
│   ├── docker-compose.yml                  # PostgreSQL 16 on :5432
│   ├── prisma.config.ts                    # Datasource URL from env
│   └── package.json                        # Scripts: prisma:generate, prisma:migrate:dev
```

## Core architecture: Hybrid Deterministic + Agent

```
schema.prisma change
        │
        ▼
┌── DETERMINISTIC (Python logic, no LLM) ────────────────┐
│  detect_changes()    → cache diff + git diff             │
│  parse_prisma_schema() → extract models & fields via regex│
│  sync_dto_for_model() → Prisma type → class-validator    │
│                         via lookup table (see below)     │
│  ✅ DTOs regenerated                                     │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌── AGENT-DRIVEN (LLM via DeepSeek v4 Flash) ────────────┐
│  build_schema_diff_summary() → structured change report  │
│  Agent receives:                                         │
│    - Schema diff (unified format)                        │
│    - Structured summary (added/removed/changed fields)   │
│  Agent tools:                                            │
│    - search_in_product(query)    → grep across src/product/│
│    - read_product_file(path)     → read full file         │
│    - write_product_file(path, c) → write updated file    │
│  Agent workflow:                                         │
│    1. Understand change semantics (rename? type change?) │
│    2. Search for old field references                    │
│    3. Read affected files for context                    │
│    4. Determine what needs changing (semantic reasoning) │
│    5. Apply fixes to Service / Controller / Module       │
│  ✅ Cross-file impact resolved                           │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌── DETERMINISTIC ───────────────────────────────────────┐
│  npx prisma generate     → regenerate Prisma client     │
│  npx prisma migrate dev  → create & apply migration     │
│  ✅ Complete                                            │
└─────────────────────────────────────────────────────────┘
```

### Why this split?

| Task | Deterministic | Agent | Why |
|------|:---:|:---:|------|
| Change detection | ✅ | | Text diff against cache — no reasoning needed |
| Schema parsing | ✅ | | Regex-based — mechanical |
| DTO generation | ✅ | | Fixed type→decorator lookup table — no ambiguity |
| Service/Controller fixes | | ✅ | Must understand field *semantics* (rename? type change? side effects?) and reason about context-dependent fixes across multiple files |
| prisma commands | ✅ | | Fixed shell commands |

**Heuristic: use deterministic code for "translation" (fixed rules), use Agent for "understanding" (requires semantic reasoning about code).**

## Schema ↔ DTO field mapping (deterministic)

| Prisma type    | DTO decorator                    |
|----------------|----------------------------------|
| `String`       | `@IsString()` + `@MinLength(2)` `@MaxLength(200)` |
| `Int`          | `@IsInt()` + `@Min(0)`           |
| `Float`        | `@IsNumber()` + `@Min(0)` + `@Type(() => Number)` |
| `Boolean`      | `@IsBoolean()` + `@Type(() => Boolean)` |
| `DateTime`     | `@IsDateString()`                |
| `String?` / `@default(...)` | `@IsOptional()` + type decorators |
| `@id` / `@updatedAt` | Omitted from CreateDto       |

## Agent tools

### Schema tools (also used by the Agent in --agent mode)
- `detect_schema_changes` — git diff + cache comparison
- `read_prisma_schema` — structured model/field output
- `sync_dto_with_schema(model_name)` — deterministic DTO regenerate
- `run_npm_script(name)` — execute prisma:generate, prisma:migrate:dev, etc.

### Cross-file analysis tools (the core Agent value-add)
- `search_in_product(query)` — grep across all `.ts` files in `src/product/`
- `read_product_file(path)` — read any file under `src/product/`
- `write_product_file(path, content)` — write updated content (with path safety check)

## Common commands

### Run auto-sync (default — no user input needed)

```bash
cd orm_agent/agent
source .venv/bin/activate
python main.py
```

Runs: detect → DTO sync → Agent cross-file analysis → prisma generate → prisma migrate dev

### Run interactive agent mode

```bash
python main.py --agent
```

Agent with Human-in-the-Loop approval for all writes. Accepts natural language:
- "check for schema changes"
- "sync the Product DTO"
- "search for inStock references and update them"

### NestJS manual operations

```bash
cd orm_agent/nestjs-proj
docker compose up -d              # Start PostgreSQL
npm run prisma:generate           # Generate Prisma client
npm run prisma:migrate:dev        # Apply migrations
npm run start:dev                 # NestJS dev server on :3000
```

### Git tracking for schema changes

```bash
cd orm_agent/nestjs-proj
git diff HEAD -- prisma/schema.prisma   # Uncommitted changes
git diff HEAD~1 -- prisma/schema.prisma # Last commit diff
```

## Key details

- **Prisma adapter**: Uses `@prisma/adapter-pg` with `DATABASE_URL` from `.env`. `PrismaService` extends `PrismaClient` directly.
- **ValidationPipe**: Global pipe in `main.ts` with `transform: true`, `whitelist: true`, `forbidNonWhitelisted: true`. DTO-schema sync is critical or requests break.
- **PostgreSQL**: Docker container `nestjs_postgres`, credentials `postgres:postgres`, database `mydb`.
- **LLM model**: Configurable via `LLM_PROVIDER` in `.env`:
  - `deepseek` (default): DeepSeek v4 Flash via `https://api.deepseek.com/v1`. Requires `DEEPSEEK_API_KEY`.
  - `ollama`: Local model via Ollama server. Install `langchain-ollama`, set `OLLAMA_MODEL` (default: `qwen2.5:7b`). No API key needed — runs fully offline.
  - The LLM is only used for cross-file analysis and --agent mode. DTO sync needs no API calls.
- **Migration naming**: Auto-named `auto_sync` via `--name` flag. Review the generated SQL before committing.
- **Python 3.10+** required. Uses `uv` for package management.
- **Change detection**: Primary method is cache-based comparison (always works). Git diff provides supplementary unified-diff output when available.

## Demo: why the Agent matters

The NestJS demo has **business-logic methods that reference individual schema fields**:

```
product.service.ts:
  findInStock()       →  where: { stock: { gt: 0 } }
  restockProduct()    →  data: { stock: { increment: amount } }
  findByCategory()    →  where: { category }
  findByPriceRange()  →  where: { price: { gte, lte } }
```

**Test scenario**: rename `stock` → `quantity` in schema.prisma, run `python main.py`.

What happens:
1. **Deterministic**: DTO is regenerated (`stock` → `quantity` in the DTO class)
2. **Agent**: Searches for `stock` across `src/product/`, finds `findInStock()` and `restockProduct()`, reads the full files, understands they are DB field references (not local variables), and updates them to `quantity`
3. **Agent correctly skips**: `findByCategory` and `findByPriceRange` — they don't reference `stock`

A pure script would need to enumerate every possible code pattern for every possible field rename. The Agent handles this generically by understanding the code.
