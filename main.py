"""Apero wo? — Entry point.

Runs the full pipeline: crawl sources -> extract events -> filter for food ->
score ease of entry -> deduplicate -> write data/events.json.
"""

import asyncio

from dotenv import load_dotenv

from backend.pipeline import run

load_dotenv()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
