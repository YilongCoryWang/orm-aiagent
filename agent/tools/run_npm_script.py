"""run_npm_script tool — run an npm script in demo-nestjs/."""
from langchain.tools import tool


@tool
def run_npm_script(script_name: str) -> str:
    """Run an npm script in demo-nestjs/.
    Allowed: prisma:generate, prisma:migrate:dev, prisma:migrate:deploy, prisma:studio."""
    from main import run_prisma_command

    allowed = {"prisma:generate", "prisma:migrate:dev", "prisma:migrate:deploy", "prisma:studio"}
    if script_name not in allowed:
        return f"❌ Not allowed. Choices: {sorted(allowed)}"
    ok, msg = run_prisma_command(["npm", "run", script_name], script_name)
    return msg
