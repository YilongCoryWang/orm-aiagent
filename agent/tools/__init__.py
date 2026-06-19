"""Tools package — exports all @tool functions for the ORM Agent.

Cross-file tools (used in auto-sync mode):
  - search_in_product
  - read_product_file
  - write_product_file

Interactive tools (used in --agent mode):
  - detect_schema_changes
  - read_prisma_schema
  - sync_dto_with_schema
  - run_npm_script
"""
from .search_in_product import search_in_product
from .read_product_file import read_product_file
from .write_product_file import write_product_file
from .detect_schema_changes import detect_schema_changes
from .read_prisma_schema import read_prisma_schema
from .sync_dto_with_schema import sync_dto_with_schema
from .run_npm_script import run_npm_script

# Cross-file tools (auto-sync mode)
CROSS_FILE_TOOLS = [
    search_in_product,
    read_product_file,
    write_product_file,
]

# All tools (interactive --agent mode)
ALL_TOOLS = [
    detect_schema_changes,
    read_prisma_schema,
    sync_dto_with_schema,
    run_npm_script,
    search_in_product,
    read_product_file,
    write_product_file,
]

__all__ = [
    "search_in_product",
    "read_product_file",
    "write_product_file",
    "detect_schema_changes",
    "read_prisma_schema",
    "sync_dto_with_schema",
    "run_npm_script",
    "CROSS_FILE_TOOLS",
    "ALL_TOOLS",
]
