# ORM AI-Agent

> **Change your schema. Run this agent. Move on.**  
> DTOs regenerated. Business logic updated. Migration SQL generated. Zero manual steps.

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/nestjs-11-red" alt="NestJS 11">
  <img src="https://img.shields.io/badge/prisma-7.8-2D3748" alt="Prisma 7.8">
  <img src="https://img.shields.io/badge/llm-deepseek%20%7C%20ollama-green" alt="LLM: DeepSeek | Ollama">
</p>

## One command. Six steps. Carefree.

You renamed a field in `schema.prisma`. Normally you'd:

1. Manually update the DTO
2. Hunt down every reference in the service
3. Check if the controller is affected
4. Run `prisma generate`
5. Run `prisma migrate dev`
6. Hope you didn't miss anything

**ORM Agent does all six in a single command.**

```bash
uv run main.py
```

```
schema.prisma change
       │
       ▼
  ① Detect        git diff HEAD                      ← Python (0 API calls)
  ② Parse         extract models & fields            ← Python
  ③ Regenerate    DTOs from schema                   ← Python (lookup table)
  ④ Fix code      search → read → reason → edit      ← LLM Agent
       └── finds every cascading reference in
           service, controller, module
  ⑤ Generate      npx prisma generate                 ← Python
  ⑥ Migrate       npx prisma migrate dev --create-only ← Python (SQL for review)
       │
       ▼
   ✅ Done. Schema, DTOs, code — all in sync.
   Migration SQL generated for human review.
```

**The carefree part:** step ④ is where the Agent earns its keep. It doesn't just grep-and-replace — it reads the code, understands which matches are DB field references and which are coincidental, and applies only the right changes. You don't review a diff wondering "did the script mess something up?"

**The safe part:** step ⑥ generates migration SQL via `--create-only` — it does **not** auto-apply. You review the SQL, then apply it manually with `npx prisma migrate dev`. No surprise data loss.

## The problem it solves

Rename `stock` → `quantity` in your Prisma schema:

| File                    | Change needed                                                    | Can a script do it?                                             |
| ----------------------- | ---------------------------------------------------------------- | --------------------------------------------------------------- |
| `create-product.dto.ts` | `stock` → `quantity`                                             | ✅ type→decorator lookup                                        |
| `product.service.ts`    | `where: { stock: { gt: 0 } }` → `where: { quantity: { gt: 0 } }` | ❌ must understand _this is a field reference, not a local var_ |
| `product.controller.ts` | Nothing (pass-through)                                           | ❌ must understand _no action needed_                           |
| Database                | Apply migration SQL                                              | ✅ fixed shell command                                          |

A `sed` script gets the first right and silently breaks the second. The Agent distinguishes field references from identically-named variables and handles them correctly. **That's the difference between "automation" and "carefree."**

## Quick start

```bash
# 1. Start PostgreSQL
cd demo-nestjs && docker compose up -d && npm install

# 2. Install agent
cd ../agent
uv sync          # or: pip install langchain langchain-openai langgraph python-dotenv

# 3. Pick your LLM
#    Cloud (DeepSeek, ~$0.01/run):
echo 'LLM_PROVIDER=deepseek' >> .env
echo 'DEEPSEEK_API_KEY=sk-xxx' >> .env

#    Local (Ollama, free, fully offline):
#    ollama pull qwen2.5:7b
#    echo 'LLM_PROVIDER=ollama' >> .env
#    uv pip install langchain-ollama

# 4. Change schema.prisma, then:
uv run main.py          # auto-sync: all 6 steps, zero interaction
```

## Try it

The demo already has business logic that references specific schema fields:

```typescript
// product.service.ts — these reference real DB columns
findInStock()      →  where: { quantity: { gt: 0 } }
restockProduct()   →  data: { quantity: { increment: amount } }
findByCategory()   →  where: { category }
findByPriceRange() →  where: { price: { gte, lte } }
```

1. Rename a field in `prisma/schema.prisma` (try `quantity` → `stock`, or `category` → `tags`)
2. `uv run main.py`
3. Watch the Agent search, find, and fix only the affected methods — then generate migration SQL for review

## When AI earns its keep (and when it doesn't)

| Task                                         | Script | Agent | Why                                          |
| -------------------------------------------- | :----: | :---: | -------------------------------------------- |
| Regenerate DTO from schema                   |   ✅   |  ❌   | Fixed mapping table — don't pay for it       |
| Run prisma generate / migrate                |   ✅   |  ❌   | Shell commands — don't pay for it            |
| Rename a field → update business logic       |   ❌   |  ✅   | Must understand code, not just match strings |
| Type change (Boolean→Int) → fix conditionals |   ❌   |  ✅   | `if (x.inStock)` ≠ `if (x.quantity)`         |
| New model + relation → create service files  |   ❌   |  ✅   | Too many decisions for a template            |
| Natural language → schema + implementation   |   ❌   |  ✅   | "Add a Review model with rating and comment" |

**Bottom line: don't throw an LLM at a lookup table. Use it where reasoning is actually required.**

## How it works

### Change detection: git-based

The agent uses `git diff HEAD` to detect schema changes — no cache files, no state to manage. The previous schema version is retrieved via `git show HEAD:<path>` for diff comparison.

### Tools architecture

The agent's capabilities are split into focused tool modules:

```
agent/tools/
├── __init__.py                # Exports all tools + ALL_TOOLS / CROSS_FILE_TOOLS
├── _paths.py                  # Shared path constants + path resolver
├── search_in_product.py       # grep across src/product/
├── read_product_file.py       # Read a file under src/product/
├── write_product_file.py      # Write a file under src/product/
├── detect_schema_changes.py   # Check if schema.prisma changed
├── read_prisma_schema.py      # Parse & summarize schema.prisma
├── sync_dto_with_schema.py    # Regenerate DTOs from schema
└── run_npm_script.py          # Run prisma generate / migrate / studio
```

**Cross-file tools** (used in auto-sync mode): `search_in_product`, `read_product_file`, `write_product_file`

### Migration: review before apply

Migration SQL is generated via `prisma migrate dev --create-only` — the agent **never auto-applies** migrations. After the agent runs, you review the generated SQL in `prisma/migrations/<timestamp>_auto_sync/migration.sql`, then apply it:

```bash
cd demo-nestjs && npx prisma migrate dev
```

## Project structure

```
orm-agent/
├── agent/                        # Python pipeline + LLM Agent
│   ├── main.py                   #   Pipeline: detect → DTO → agent → prisma
│   ├── tools/                    #   Modular @tool functions
│   │   ├── _paths.py             #   Path constants + resolver
│   │   ├── search_in_product.py  #   grep src/product/
│   │   ├── read_product_file.py  #   Read source files
│   │   ├── write_product_file.py #   Write source files
│   │   ├── detect_schema_changes #   git diff HEAD detection
│   │   ├── read_prisma_schema    #   Parse schema.prisma
│   │   ├── sync_dto_with_schema  #   Regenerate DTOs
│   │   └── run_npm_script        #   Run prisma commands
│   └── .env                      #   LLM_PROVIDER, API keys
├── demo-nestjs/                  # NestJS + Prisma + PostgreSQL demo
│   ├── prisma/
│   │   ├── schema.prisma         #   source of truth
│   │   └── migrations/           #   generated migration SQL
│   └── src/product/              #   DTOs, Service, Controller, Module
└── README.md
```

## Tech stack

| Layer           | Technology                        |
| --------------- | --------------------------------- |
| Agent framework | LangChain + LangGraph             |
| LLM             | DeepSeek (cloud) / Ollama (local) |
| ORM             | Prisma 7.8                        |
| Backend         | NestJS 11                         |
| Database        | PostgreSQL                        |
| Runtime         | Python 3.10+ / uv                 |
