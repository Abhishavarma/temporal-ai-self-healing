"""The self-healing workflow: Monitor -> Analyse -> Plan -> (Approve) -> Execute -> Verify.

Temporal keeps this code deterministic and durable: every step is recorded in
the workflow history, so if the worker crashes the workflow resumes at the
exact step where it stopped. AI calls (non-deterministic) live in activities.
"""
from datetime import timedelta
from typing import List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import (analyse_incident, execute_action, notify_on_call,
                            plan_remediation, record_knowledge, verify_resolution)
    from shared import PROMPT_VERSION, Alert, Approval, IncidentResult, Plan

MAX_ATTEMPTS = 2
AI_STEP = dict(start_to_close_timeout=timedelta(seconds=60),
               retry_policy=RetryPolicy(maximum_attempts=3))
INFRA_STEP = dict(start_to_close_timeout=timedelta(seconds=60),
                  retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), maximum_attempts=5))


@workflow.defn
class SelfHealingWorkflow:
    def __init__(self) -> None:
        self._approval: Optional[Approval] = None
        self._status = "started"
        self._pending_plan: Optional[Plan] = None

    # ----- signals & queries: how humans interact with a running workflow -----
    @workflow.signal
    def approve(self, approval: Approval) -> None:
        self._approval = approval

    @workflow.query
    def status(self) -> dict:
        p = self._pending_plan
        return {"status": self._status,
                "waiting_for_approval_of": p.action if p and self._status == "awaiting_approval" else None,
                "reason": p.reason if p else None}

    # ----- main logic -----
    @workflow.run
    async def run(self, alert: Alert, approval_timeout_minutes: float = 60) -> IncidentResult:
        actions: List[str] = []
        approved_by: Optional[str] = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            # ANALYSE (AI)
            self._status = f"analysing (attempt {attempt})"
            diagnosis = await workflow.execute_activity(analyse_incident, alert, **AI_STEP)

            # PLAN (AI, restricted to golden-path actions)
            self._status = "planning"
            plan = await workflow.execute_activity(plan_remediation, args=[alert, diagnosis, attempt], **AI_STEP)
            self._pending_plan = plan

            # HUMAN-IN-THE-LOOP: wait, possibly for hours or days, at no cost
            if plan.needs_approval:
                self._status = "awaiting_approval"
                self._approval = None
                workflow.logger.info(f"Waiting for approval of {plan.action}")
                try:
                    await workflow.wait_condition(lambda: self._approval is not None,
                                                  timeout=timedelta(minutes=approval_timeout_minutes))
                except TimeoutError:
                    await workflow.execute_activity(
                        notify_on_call, f"No approval for '{plan.action}' on {alert.resource}",
                        start_to_close_timeout=timedelta(seconds=30))
                    return await self._finish(alert, "escalated", attempt, actions, approved_by, diagnosis, plan)

                if not self._approval.approved:
                    return await self._finish(alert, "rejected", attempt, actions,
                                              self._approval.by, diagnosis, plan)
                approved_by = self._approval.by

            # EXECUTE (retried automatically if the infrastructure API fails)
            self._status = f"executing {plan.action}"
            await workflow.execute_activity(execute_action, args=[alert.resource, plan.action], **INFRA_STEP)
            actions.append(plan.action)

            # VERIFY: did it actually fix the problem? If not, loop and re-plan.
            self._status = "verifying"
            if await workflow.execute_activity(verify_resolution, alert.resource, **INFRA_STEP):
                return await self._finish(alert, "resolved", attempt, actions, approved_by, diagnosis, plan)

        await workflow.execute_activity(
            notify_on_call, f"{alert.resource} still unhealthy after {MAX_ATTEMPTS} attempts",
            start_to_close_timeout=timedelta(seconds=30))
        return await self._finish(alert, "unresolved", MAX_ATTEMPTS, actions, approved_by, diagnosis, plan)

    async def _finish(self, alert, status, attempts, actions, approved_by, diagnosis, plan) -> IncidentResult:
        self._status = status
        # KNOWLEDGE: remember what happened, for future incidents and audits
        await workflow.execute_activity(record_knowledge, {
            "workflow_id": workflow.info().workflow_id,
            "resource": alert.resource, "issue": alert.issue,
            "cause": diagnosis.probable_cause, "confidence": diagnosis.confidence,
            "actions": actions, "status": status, "approved_by": approved_by,
            "prompt_version": PROMPT_VERSION,
        }, start_to_close_timeout=timedelta(seconds=30))
        return IncidentResult(resource=alert.resource, status=status, attempts=attempts,
                              actions_taken=actions, approved_by=approved_by,
                              prompt_version=PROMPT_VERSION)
