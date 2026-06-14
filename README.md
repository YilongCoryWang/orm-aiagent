# ORM Agent

> **Change your schema. Run this agent. Move on.**  
> DTOs regenerated. Business logic updated. Migration applied. Zero manual steps.

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
python main.py
```

```
schema.prisma change
       │
       ▼
  ① Detect        cache diff + git diff              ← Python (0 API calls)
  ② Parse         extract models & fields            ← Python
  ③ Regenerate    DTOs from schema                   ← Python (lookup table)
  ④ Fix code      search → read → reason → edit      ← LLM Agent
       └── finds every cascading reference in
           service, controller, module
  ⑤ Generate      npx prisma generate                 ← Python
  ⑥ Migrate       npx prisma migrate dev              ← Python
       │
       ▼
   ✅ Done. Schema, DTOs, code, DB — all in sync.
```

**The carefree part:** steps ④ is where the Agent earns its keep. It doesn't just grep-and-replace — it reads the code, understands which matches are DB field references and which are coincidental, and applies only the right changes. You don't review a diff wondering "did the script mess something up?"

## The problem it solves

Rename `stock` → `quantity` in your Prisma schema:

| File | Change needed | Can a script do it? |
|------|--------------|---------------------|
| `create-product.dto.ts` | `stock` → `quantity` | ✅ type→decorator lookup |
| `product.service.ts` | `where: { stock: { gt: 0 } }` → `where: { quantity: { gt: 0 } }` | ❌ must understand *this is a field reference, not a local var* |
| `product.controller.ts` | Nothing (pass-through) | ❌ must understand *no action needed* |
| Database | Apply migration SQL | ✅ fixed shell command |

A `sed` script gets the first right and silently breaks the second. The Agent distinguishes field references from identically-named variables and handles them correctly. **That's the difference between "automation" and "carefree."**

## Quick start

```bash
# 1. Start PostgreSQL
cd nestjs-proj && docker compose up -d && npm install

# 2. Install agent
cd ../agent
python -m venv .venv && source .venv/bin/activate
pip install langchain langchain-openai langgraph python-dotenv

# 3. Pick your LLM
#    Cloud (DeepSeek, ~$0.01/run):
echo 'LLM_PROVIDER=deepseek' >> .env
echo 'DEEPSEEK_API_KEY=sk-xxx' >> .env

#    Local (Ollama, free, fully offline):
#    ollama pull qwen2.5:7b
#    echo 'LLM_PROVIDER=ollama' >> .env
#    pip install langchain-ollama

# 4. Change schema.prisma, then:
python main.py          # auto-sync: all 6 steps, zero interaction
python main.py --agent  # interactive chat mode with approval gates
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
2. `python main.py`
3. Watch the Agent search, find, and fix only the affected methods — then run the migration

## When AI earns its keep (and when it doesn't)

| Task | Script | Agent | Why |
|------|:---:|:---:|------|
| Regenerate DTO from schema | ✅ | ❌ | Fixed mapping table — don't pay for it |
| Run prisma generate / migrate | ✅ | ❌ | Shell commands — don't pay for it |
| Rename a field → update business logic | ❌ | ✅ | Must understand code, not just match strings |
| Type change (Boolean→Int) → fix conditionals | ❌ | ✅ | `if (x.inStock)` ≠ `if (x.quantity)` |
| New model + relation → create service files | ❌ | ✅ | Too many decisions for a template |
| Natural language → schema + implementation | ❌ | ✅ | "Add a Review model with rating and comment" |

**Bottom line: don't throw an LLM at a lookup table. Use it where reasoning is actually required.**

## Project structure

```
orm-agent/
├── agent/                    # Python pipeline + LLM Agent
│   ├── main.py               #   create_llm() → deepseek | ollama
│   └── .env                  #   LLM_PROVIDER, API keys
├── nestjs-proj/              # NestJS + Prisma + PostgreSQL demo
│   ├── prisma/schema.prisma  #   source of truth
│   └── src/product/          #   DTOs, Service, Controller
└── README.md
```
