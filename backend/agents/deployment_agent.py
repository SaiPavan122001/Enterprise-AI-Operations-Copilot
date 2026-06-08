import json


def investigate_deployments(incidents):

    with open("data/deployments.json", "r") as f:
        deployments = json.load(f)

    services = {
        incident["service"]
        for incident in incidents
    }

    relevant_deployments = []

    for deployment in deployments:

        if deployment["service"] in services:
            relevant_deployments.append(deployment)

    return relevant_deployments