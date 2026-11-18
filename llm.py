"""AI layer. Uses a real LLM if LLM_API_KEY is set, otherwise a mock.

Any OpenAI-compatible API works (OpenAI, Mistral, Azure OpenAI, a local
Ollama server...). Set:
    LLM_API_KEY   your key (any value for Ollama)
    LLM_BASE_URL  e.g. https://api.mistral.ai/v1  or  http://localhost:11434/v1
    LLM_MODEL     e.g. mistral-small-latest  or  llama3.1
"""
import json
import os

from shared import ALLOWED_ACTIONS, PROMPT_VERSION

PROMPTS = {
    "v1": {
        "analyse": "What is wrong with this resource?",
        "plan": "How should we fix it?",
    },
    # v2: stricter instructions + forced JSON output -> consistent answers
    "v2": {
        "analyse": (
            "You are an SRE assistant. Given an infrastructure alert and recent logs, "
            "identify the most probable root cause. Reply ONLY with JSON: "
            '{"probable_cause": str, "confidence": number 0-1, "evidence": [str]}. '
            "Base evidence only on the logs provided."
        ),
        "plan": (
            "You are an SRE assistant. Choose exactly ONE remediation from this list "
            "and nothing else: {actions}. Prefer the lowest-risk action likely to work. "
            'Reply ONLY with JSON: {{"action": str, "reason": str}}.'
        ),
    },
}


def _use_real_llm() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def _chat(system: str, user: str) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["LLM_API_KEY"], base_url=os.environ.get("LLM_BASE_URL"))
    resp = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return json.loads(resp.choices[0].message.content)


# ---------- mock answers, so the demo runs with no API key ----------
_MOCK_DIAGNOSIS = {
    "disk_full": {
        "probable_cause": "Application logs are not rotated and filled /var/log",
        "confidence": 0.85,
        "evidence": ["/var/log/app grew 40 GB in 3 days", "logrotate job failed"],
    },
    "disk_full_data": {
        "probable_cause": "Database data volume has grown beyond disk capacity",
        "confidence": 0.8,
        "evidence": ["/var/lib/postgres is 92% of disk", "no large log files found"],
    },
    "service_crash": {
        "probable_cause": "Service crashed after an out-of-memory error",
        "confidence": 0.75,
        "evidence": ["OOMKilled in kernel log", "service exited with code 137"],
    },
    "pod_crashloop": {
        "probable_cause": "Deployment cannot handle the traffic peak; pods are overloaded",
        "confidence": 0.7,
        "evidence": ["CPU at 98% on all replicas", "readiness probe timeouts"],
    },
}
_MOCK_PLAN = {
    "disk_full": {"action": "clean_old_logs", "reason": "Logs are the cause; cleaning them is safe and fast"},
    "disk_full_data": {"action": "expand_disk", "reason": "Data is legitimate, the disk must be bigger"},
    "service_crash": {"action": "restart_service", "reason": "A restart clears the memory state"},
    "pod_crashloop": {"action": "scale_out_pods", "reason": "More replicas will absorb the peak load"},
}


def analyse(issue: str, message: str, logs: list) -> dict:
    if _use_real_llm():
        p = PROMPTS[PROMPT_VERSION]["analyse"]
        return _chat(p, f"Alert: {message}\nLogs:\n" + "\n".join(logs))
    return _MOCK_DIAGNOSIS.get(issue, {"probable_cause": "unknown", "confidence": 0.2, "evidence": []})


def plan(issue: str, probable_cause: str, attempt: int) -> dict:
    if _use_real_llm():
        p = PROMPTS[PROMPT_VERSION]["plan"].format(actions=list(ALLOWED_ACTIONS))
        return _chat(p, f"Issue: {issue}\nProbable cause: {probable_cause}\nAttempt number: {attempt}")
    # Mock: if the first fix did not work, escalate to a stronger action
    if attempt > 1 and issue == "disk_full":
        return {"action": "expand_disk", "reason": "Cleaning logs was not enough; more space is needed"}
    return _MOCK_PLAN.get(issue, {"action": "reboot_vm", "reason": "Unknown issue"})
