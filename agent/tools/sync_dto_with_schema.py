"""sync_dto_with_schema tool — regenerate DTOs from schema."""
from langchain.tools import tool


@tool
def sync_dto_with_schema(model_name: str) -> str:
    """Regenerate CreateDto + UpdateDto for a Prisma model from the current
    schema. This is the DETERMINISTIC sync — always prefer this for DTOs
    over manually generating TypeScript."""
    from main import sync_dto_for_model
    ok, msg = sync_dto_for_model(model_name)
    return msg
