"""Runs the workflow and activities. Kill it (Ctrl+C) mid-incident and start it
again: the workflow continues from the step where it stopped."""
import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from activities import (analyse_incident, execute_action, notify_on_call,
                        plan_remediation, record_knowledge, verify_resolution)
from shared import TASK_QUEUE
from workflows import SelfHealingWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[SelfHealingWorkflow],
        activities=[analyse_incident, plan_remediation, execute_action,
                    verify_resolution, record_knowledge, notify_on_call],
    )
    print(f"Worker listening on task queue '{TASK_QUEUE}'. Ctrl+C to stop.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
