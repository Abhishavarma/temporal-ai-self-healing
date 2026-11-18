"""MONITOR step: simulates an alert and starts a self-healing workflow.

Usage:
    python trigger.py disk_full            # low-risk fix, runs automatically
    python trigger.py disk_full_stubborn   # first fix fails -> AI re-plans -> needs approval
    python trigger.py service_crash        # restart service automatically
    python trigger.py pod_crashloop        # scale out -> needs approval
    python trigger.py database_growth      # expand disk -> needs approval
Add --timeout 1 to escalate if nobody approves within 1 minute.
"""
import argparse
import asyncio
import json
import uuid

from temporalio.client import Client

from activities import STATE_FILE
from shared import TASK_QUEUE, Alert
from workflows import SelfHealingWorkflow

HEALTHY = {"disk_size_gb": 100, "disk_used_gb": 50, "logs_gb": 5,
           "service_up": True, "memory_pct": 40, "replicas": 2, "cpu_pct": 40}

SCENARIOS = {
    "disk_full": dict(
        resource="vm-app-01", issue="disk_full", message="Disk usage at 95% on vm-app-01",
        logs=["/var/log/app/server.log.1 ... 40G", "logrotate: error: skipping /var/log/app"],
        state={"disk_used_gb": 95, "logs_gb": 40}),
    "disk_full_stubborn": dict(
        resource="vm-app-02", issue="disk_full", message="Disk usage at 95% on vm-app-02",
        logs=["/var/log/app ... 6G", "/data/uploads ... 80G"],
        state={"disk_used_gb": 95, "logs_gb": 6}),
    "database_growth": dict(
        resource="vm-db-01", issue="disk_full_data", message="Disk usage at 92% on vm-db-01",
        logs=["/var/lib/postgres ... 88G", "no large log files"],
        state={"disk_used_gb": 92, "logs_gb": 1}),
    "service_crash": dict(
        resource="vm-api-01", issue="service_crash", message="booking-api is down on vm-api-01",
        logs=["kernel: Out of memory: Killed process 4121 (booking-api)", "systemd: exit code 137"],
        state={"service_up": False, "memory_pct": 99}),
    "pod_crashloop": dict(
        resource="k8s-search", issue="pod_crashloop", message="Pods restarting in deployment flight-search",
        logs=["Readiness probe failed: timeout", "CPU throttling 98%"],
        state={"cpu_pct": 98, "replicas": 2}),
}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=SCENARIOS)
    ap.add_argument("--timeout", type=float, default=60, help="approval timeout in minutes")
    ap.add_argument("--no-wait", action="store_true", help="start and exit without waiting for the result")
    a = ap.parse_args()
    s = SCENARIOS[a.scenario]

    # Break the simulated resource
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    state[s["resource"]] = {**HEALTHY, **s["state"]}
    STATE_FILE.write_text(json.dumps(state, indent=2))

    client = await Client.connect("localhost:7233")
    wf_id = f"incident-{s['resource']}-{uuid.uuid4().hex[:6]}"
    alert = Alert(resource=s["resource"], issue=s["issue"], message=s["message"], logs=s["logs"])
    handle = await client.start_workflow(SelfHealingWorkflow.run, args=[alert, a.timeout],
                                         id=wf_id, task_queue=TASK_QUEUE)
    print(f"ALERT: {s['message']}\nStarted workflow {wf_id}")
    print(f"  status:  python status.py {wf_id}")
    print(f"  approve: python approve.py {wf_id} --by <your name>")
    print(f"  reject:  python approve.py {wf_id} --reject --by <your name>")
    if a.no_wait:
        return
    result = await handle.result()
    print(f"\nRESULT: {result}")


if __name__ == "__main__":
    asyncio.run(main())
