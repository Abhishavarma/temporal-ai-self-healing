"""Ask a running workflow what it is doing (a Temporal query)."""
import asyncio
import sys

from temporalio.client import Client

from workflows import SelfHealingWorkflow


async def main() -> None:
    client = await Client.connect("localhost:7233")
    print(await client.get_workflow_handle(sys.argv[1]).query(SelfHealingWorkflow.status))


if __name__ == "__main__":
    asyncio.run(main())
