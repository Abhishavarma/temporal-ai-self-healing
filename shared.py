"""Data types and constants shared by the workflow, activities and scripts."""
from dataclasses import dataclass, field
from typing import List, Optional

TASK_QUEUE = "self-healing"

# Version of the prompts used by the AI steps. It is recorded in every
# workflow run, so the history shows which prompt produced which decision.
PROMPT_VERSION = "v2"

# "Golden path" remediations: the AI may only choose from this list.
# Anything outside it is rejected and sent to a human.
ALLOWED_ACTIONS = {
    "clean_old_logs":   {"risk": "low",  "description": "Delete rotated logs older than 7 days"},
    "restart_service":  {"risk": "low",  "description": "Restart the failing service"},
    "expand_disk":      {"risk": "high", "description": "Add 50 GB to the VM disk (costs money)"},
    "reboot_vm":        {"risk": "high", "description": "Reboot the whole VM (short downtime)"},
    "scale_out_pods":   {"risk": "high", "description": "Add 2 replicas to the Kubernetes deployment"},
}


@dataclass
class Alert:
    resource: str          # e.g. "vm-app-01"
    issue: str             # e.g. "disk_full"
    message: str           # human-readable alert text
    logs: List[str] = field(default_factory=list)


@dataclass
class Diagnosis:
    probable_cause: str
    confidence: float      # 0.0 - 1.0
    evidence: List[str]
    prompt_version: str


@dataclass
class Plan:
    action: str
    reason: str
    risk: str              # "low" | "high"
    needs_approval: bool
    prompt_version: str


@dataclass
class Approval:
    approved: bool
    by: str
    comment: str = ""


@dataclass
class IncidentResult:
    resource: str
    status: str            # "resolved" | "rejected" | "escalated" | "unresolved"
    attempts: int
    actions_taken: List[str]
    approved_by: Optional[str]
    prompt_version: str
