import json
from llama_index.core import Document


def load_incidents():
    with open("data/incidents.json", "r") as f:
        incidents = json.load(f)

    docs = []

    for incident in incidents:
        docs.append(
            Document(
                text=f"""
Incident ID: {incident['id']}
Service: {incident['service']}
Severity: {incident['severity']}
Title: {incident['title']}
Root Cause: {incident['root_cause']}
Status: {incident['status']}
"""
            )
        )

    return docs


def load_deployments():
    with open("data/deployments.json", "r") as f:
        deployments = json.load(f)

    docs = []

    for dep in deployments:
        docs.append(
            Document(
                text=f"""
Deployment ID: {dep['deployment_id']}
Service: {dep['service']}
Time: {dep['time']}
Change: {dep['change']}
"""
            )
        )

    return docs


def load_logs():
    with open("data/logs.txt", "r") as f:
        logs = f.readlines()

    chunks = []

    chunk_size = 50

    for i in range(0, len(logs), chunk_size):
        chunk = "".join(logs[i:i + chunk_size])

        chunks.append(
            Document(text=chunk)
        )

    return chunks