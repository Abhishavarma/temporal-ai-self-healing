"""Human-in-the-loop: approve or reject the AI's proposed action.

    python approve.py <workflow_id> --by Abhisha
    python approve.py <workflow_id> --reject --by Abhisha --comment "too risky during peak"
"""
import argparse
import asyncio

from temporalio.client import Client
from temporalio.service import RPCError

from shared import Approval
from workflows import SelfHealingWorkflow


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow_id")
    ap.add_argument("--by", default="operator")
    ap.add_argument("--reject", action="store_true")
    ap.add_argument("--comment", default="")
    a = ap.parse_args()

    client = await Client.connect("localhost:7233")
    handle = client.get_workflow_handle(a.workflow_id)
    try:
        st = await handle.query(SelfHealingWorkflow.status)
        if st["status"] != "awaiting_approval":
            print(f"Nothing to approve - workflow status is '{st['status']}'")
            return
        print(f"AI proposes: {st['waiting_for_approval_of']}  ({st['reason']})")
    except RPCError:
        # Queries need a running worker; signals do not. Temporal stores the
        # signal and the workflow receives it as soon as a worker is back.
        print("Worker is down - sending the decision anyway; it will be applied when the worker restarts.")
    await handle.signal(SelfHealingWorkflow.approve,
                        Approval(approved=not a.reject, by=a.by, comment=a.comment))
    print("Rejected." if a.reject else f"Approved by {a.by}.")


if __name__ == "__main__":
    asyncio.run(main())
