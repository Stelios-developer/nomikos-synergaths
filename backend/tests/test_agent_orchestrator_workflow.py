import json
from pathlib import Path


def _headers(node: dict) -> dict[str, str]:
    return {
        item["name"]: item["value"]
        for item in node["parameters"].get("headerParameters", {}).get("parameters", [])
    }


def test_agent_orchestrator_is_a_real_secured_workflow_definition():
    workflow_path = Path(__file__).resolve().parents[2] / "n8n" / "agent-orchestrator.workflow.json"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["name"] == "NOMIKOS SYNERGATHS · Agent Orchestrator"
    assert workflow["active"] is True
    assert workflow["settings"]["executionOrder"] == "v1"

    expected_case_endpoints = {
        "Start document case": "/integrations/n8n/cases/start",
        "Document DNA & Quality Agent": "/integrations/n8n/cases/document-dna",
        "Facts, Obligations & Deadlines Agent": "/integrations/n8n/cases/facts",
        "Risk Prioritisation Agent": "/integrations/n8n/cases/risks",
        "Decision Brief & Action Pack Agent": "/integrations/n8n/cases/draft-action-pack",
        "Mandatory Hallucination Auditor": "/integrations/n8n/cases/audit",
        "Finalize verified action pack": "/integrations/n8n/cases/finalize",
        "Finalize human-review pack": "/integrations/n8n/cases/finalize",
    }
    for name, endpoint in expected_case_endpoints.items():
        node = nodes[name]
        assert node["type"] == "n8n-nodes-base.httpRequest"
        assert node["parameters"]["url"].endswith(endpoint)
        headers = _headers(node)
        assert "x-n8n-api-key" in headers["X-N8N-API-Key"]
        assert "$env" not in headers["X-N8N-API-Key"]
        assert "X-Workspace-ID" in headers
        assert node["parameters"]["sendBody"] is True
        assert node["parameters"]["contentType"] == "json"
        assert node["parameters"]["specifyBody"] == "json"

    assert nodes["Webhook · App document ready"]["parameters"] == {
        "httpMethod": "POST",
        "path": "nexus-agent-orchestrator/case",
        "responseMode": "responseNode",
        "options": {},
    }
    app_header_gate = nodes["Require app integration header"]["parameters"]["conditions"]["conditions"][0]
    assert app_header_gate["leftValue"] == "={{ $json.headers['x-n8n-api-key'] }}"
    assert app_header_gate["operator"]["operation"] == "notEmpty"
    assert workflow["settings"]["saveDataSuccessExecution"] == "none"
    assert workflow["settings"]["saveDataErrorExecution"] == "none"
    assert workflow["settings"]["saveManualExecutions"] is False
    assert workflow["settings"]["saveExecutionProgress"] is False
    rejected = nodes["Reject missing integration header"]
    assert rejected["parameters"]["options"]["responseCode"] == 401
    for name, node in nodes.items():
        if node["type"] == "n8n-nodes-base.if" and "header" in name.lower():
            assert workflow["connections"][name]["main"][1][0]["node"] == rejected["name"]

    specialist_branches = {
        "Document Assistant (RAG)": "/integrations/n8n/analyze",
        "Supervisor Agent": "/integrations/n8n/agents/supervisor",
        "Research Agent": "/integrations/n8n/agents/research",
        "Expert Review · 3 advisors + moderator": "/integrations/n8n/agents/expert-review",
    }
    for name, endpoint in specialist_branches.items():
        node = nodes[name]
        assert node["type"] == "n8n-nodes-base.httpRequest"
        assert node["parameters"]["url"].endswith(endpoint)
        assert _headers(node)["X-N8N-API-Key"] == "={{ $json.headers['x-n8n-api-key'] }}"
        assert node["parameters"]["specifyBody"] == "json"
        assert "question" in node["parameters"]["jsonBody"]

    assert "Manual PDF upload" not in nodes
    assert "Store PDF in RAG" not in nodes

    gate = nodes["IF · Evidence quality gate"]
    assert gate["parameters"]["conditions"]["conditions"][0]["leftValue"] == "={{ $json.audit.passed }}"
    release_branches = workflow["connections"]["IF · Evidence quality gate"]["main"]
    assert release_branches[0][0]["node"] == "Finalize verified action pack"
    assert release_branches[1][0]["node"] == "Finalize human-review pack"

    all_names = set(nodes)
    for connection in workflow["connections"].values():
        for branch in connection["main"]:
            for target in branch:
                assert target["node"] in all_names
