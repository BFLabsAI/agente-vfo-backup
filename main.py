from __future__ import annotations

"""
CLI entry point for local development and testing.
Run: python main.py
"""
import asyncio

from app.agent_factory import create_vanessa_agent


async def main() -> None:
    agent = create_vanessa_agent(session_id="vanessa-cli-dev")
    print("Vanessa CLI — digite sua mensagem. Ctrl+C para sair.\n")
    while True:
        try:
            user_input = input("Você: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nEncerrando.")
            break
        if not user_input:
            continue
        result = await agent.arun(user_input)
        reply = result.content if hasattr(result, "content") else str(result)
        print(f"Vanessa: {reply}\n")


if __name__ == "__main__":
    asyncio.run(main())
