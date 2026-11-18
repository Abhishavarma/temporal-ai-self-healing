"""Activities: the steps that touch the outside world (AI calls, infrastructure).

Infrastructure is simulated with a small JSON file (infra_state.json) so the
demo needs no real VM or Kubernetes cluster.
"""
import json
import os
import time
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

import llm
from shared import ALLOWED_ACTIONS, PROMPT_VERSION, Alert, Diagnosis, Plan

STATE_FILE = Path(__file__).parent / "infra_state.json"
KNOWLEDGE_FILE = Path(__file__).parent / "knowledge.jsonl"


def _load() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def _save(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _slow() -> None:
    # Optional pause so you have time to kill the worker during a demo
    time.sleep(float(os.environ.get("STEP_DELAY", "0")))


# ---------------- Analyse (AI) ----------------
@activity.defn
async def analyse_incident(alert: Alert) -> Diagnosis:
    _slow()
    activity.logger.info(f"AI analysing {alert.resource}: {alert.message}")
    out = llm.analyse(alert.issue, alert.message, alert.logs)
    return Diagnosis(
        probable_cause=out["probable_cause"],
        confidence=float(out["confidence"]),
        evidence=list(out.get("evidence", [])),
        prompt_version=PROMPT_VERSION,
    )


# ---------------- Plan (AI + guardrail) ----------------
@activity.defn
async def plan_remediation(alert: Alert, diagnosis: Diagnosis, attempt: int) -> Plan:
    _slow()
    out = llm.plan(alert.issue, diagnosis.probable_cause, attempt)
    action = out.get("action", "")

    # Guardrail: the AI can only pick a golden-path action.
    if action not in ALLOWED_ACTIONS:
        return Plan(action=action, reason=f"AI proposed a non-approved action: {out.get('reason')}",
                    risk="unknown", needs_approval=True, prompt_version=PROMPT_VERSION)

    risk = ALLOWED_ACTIONS[action]["risk"]
    # Ask a human if the action is risky OR the AI is not confident enough.
    needs_approval = risk == "high" or diagnosis.confidence < 0.6
    return Plan(action=action, reason=out.get("reason", ""), risk=risk,
                needs_approval=needs_approval, prompt_version=PROMPT_VERSION)


# ---------------- Execute ----------------
@activity.defn
async def execute_action(resource: str, action: str) -> str:
    _slow()
    # Simulate an unreliable infrastructure API: first call fails if FLAKY=1.
    # Temporal retries this step only - nothing before it is re-run.
    if os.environ.get("FLAKY") == "1" and activity.info().attempt == 1:
        raise ApplicationError("Cloud API timeout (simulated)")

    if action not in ALLOWED_ACTIONS:
        raise ApplicationError(f"Refusing to run non-approved action {action}", non_retryable=True)

    state = _load()
    r = state[resource]
    if action == "clean_old_logs":
        r["disk_used_gb"] -= r["logs_gb"]
        r["logs_gb"] = 0
    elif action == "expand_disk":
        r["disk_size_gb"] += 50
    elif action in ("restart_service", "reboot_vm"):
        r["service_up"] = True
        r["memory_pct"] = 35
    elif action == "scale_out_pods":
        r["replicas"] += 2
        r["cpu_pct"] = round(r["cpu_pct"] * (r["replicas"] - 2) / r["replicas"])
    _save(state)
    msg = f"Executed {action} on {resource} (attempt {activity.info().attempt})"
    activity.logger.info(msg)
    return msg


# ---------------- Verify ----------------
@activity.defn
async def verify_resolution(resource: str) -> bool:
    r = _load()[resource]
    disk_ok = r["disk_used_gb"] / r["disk_size_gb"] < 0.80
    return disk_ok and r["service_up"] and r["cpu_pct"] < 80


# ---------------- Knowledge (the K in MAPE-K) ----------------
@activity.defn
async def record_knowledge(entry: dict) -> None:
    with KNOWLEDGE_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


@activity.defn
async def notify_on_call(message: str) -> None:
    # In real life: Teams / Slack / PagerDuty. Here we just log it.
    activity.logger.warning(f"ESCALATION to on-call engineer: {message}")
    print(f"\n*** ESCALATION: {message} ***\n", flush=True)
