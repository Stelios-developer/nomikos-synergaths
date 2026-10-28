"""Mechanical migration of NOMIKOS SYNERGATHS workflows; preserves unrelated workflows."""
import argparse
import json
from pathlib import Path
import uuid

TARGET_IDS = {"nexusAgentOrchestrator", "manualPdfUploadAnalysis"}


def harden(workflow: dict) -> dict:
    if workflow.get("id") not in TARGET_IDS:
        raise ValueError("Only the two NOMIKOS SYNERGATHS workflows may be migrated")
    workflow.setdefault("settings", {}).update({
        "saveDataSuccessExecution": "none", "saveDataErrorExecution": "none",
        "saveManualExecutions": False, "saveExecutionProgress": False,
    })
    if workflow["id"] != "nexusAgentOrchestrator":
        return workflow
    nodes = workflow["nodes"]
    connections = workflow["connections"]
    success = "Respond with analysis result"
    rejected = "Reject missing integration header"
    terminal_nodes = [node for node in nodes if node["type"] == "n8n-nodes-base.httpRequest" and not connections.get(node["name"])]
    for name, body, status, position in (
        (success, "={{ $json }}", 200, [1760, 420]),
        (rejected, '{"error":"An integration header is required."}', 401, [520, 980]),
    ):
        if not any(node["name"] == name for node in nodes):
            nodes.append({
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "nexus/" + name)),
                "name": name, "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.4,
                "position": position,
                "parameters": {"respondWith": "json", "responseBody": body, "options": {"responseCode": status}},
            })
    for node in nodes:
        if node["type"] == "n8n-nodes-base.webhook":
            node["parameters"]["responseMode"] = "responseNode"
        if node["type"] == "n8n-nodes-base.if" and "header" in node["name"].lower():
            branches = connections[node["name"]]["main"]
            while len(branches) < 2:
                branches.append([])
            branches[1] = [{"node": rejected, "type": "main", "index": 0}]
    for node in terminal_nodes:
        connections[node["name"]] = {"main": [[{"node": success, "type": "main", "index": 0}]]}
    return workflow


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    data = json.loads(args.source.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        result = [harden(workflow) for workflow in data if workflow.get("id") in TARGET_IDS]
        if not result:
            raise ValueError("No NOMIKOS SYNERGATHS workflows found")
    else:
        result = harden(data)
    args.destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
