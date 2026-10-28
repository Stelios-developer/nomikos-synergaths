import json
from pathlib import Path


def test_case_intelligence_workflow_has_all_agents_and_a_mandatory_gate():
    template_path = Path(__file__).resolve().parents[2] / "n8n" / "manual-pdf-upload-workflow.template.json"
    workflow = json.loads(template_path.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}

    expected_urls = {
        "Start document case": "/integrations/n8n/cases/start",
        "Document DNA & Quality Agent": "/integrations/n8n/cases/document-dna",
        "Facts, Obligations & Deadlines Agent": "/integrations/n8n/cases/facts",
        "Risk Prioritisation Agent": "/integrations/n8n/cases/risks",
        "Decision Brief & Action Pack Agent": "/integrations/n8n/cases/draft-action-pack",
        "Mandatory Hallucination Auditor": "/integrations/n8n/cases/audit",
        "Finalize verified action pack": "/integrations/n8n/cases/finalize",
        "Finalize human-review pack": "/integrations/n8n/cases/finalize",
    }
    assert workflow["active"] is False
    assert "Analyze document" not in nodes

    for name, endpoint in expected_urls.items():
        node = nodes[name]
        assert node["type"] == "n8n-nodes-base.httpRequest"
        assert node["parameters"]["url"].endswith(endpoint)
        header_names = {
            header["name"]
            for header in node["parameters"]["headerParameters"]["parameters"]
        }
        assert {"X-N8N-API-Key", "X-Workspace-ID"} <= header_names

    assert "filename" in nodes["Start document case"]["parameters"]["jsonBody"]
    for name in (
        "Document DNA & Quality Agent",
        "Facts, Obligations & Deadlines Agent",
        "Risk Prioritisation Agent",
        "Decision Brief & Action Pack Agent",
        "Mandatory Hallucination Auditor",
        "Finalize verified action pack",
        "Finalize human-review pack",
    ):
        assert "case_id" in nodes[name]["parameters"]["jsonBody"]

    gate = nodes["IF Evidence Quality Gate"]
    condition = gate["parameters"]["conditions"]["conditions"][0]
    assert condition["leftValue"] == "={{ $json.audit.passed }}"
    branches = workflow["connections"]["IF Evidence Quality Gate"]["main"]
    assert branches[0][0]["node"] == "Finalize verified action pack"
    assert branches[1][0]["node"] == "Finalize human-review pack"
