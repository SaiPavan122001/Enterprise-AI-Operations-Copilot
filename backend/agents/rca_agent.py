def generate_rca(
    incidents,
    deployments,
    logs
):

    root_cause = "Unknown"

    evidence = []

    resolution = []

    risk = "Medium"

    # Incident evidence
    for incident in incidents:

        evidence.append(
            f"Incident {incident['incident_id']} - "
            f"{incident['title']}"
        )

        if incident.get("root_cause"):
            root_cause = incident["root_cause"]

    # Deployment evidence
    for deployment in deployments:

        evidence.append(
            f"Deployment {deployment['deployment_id']} - "
            f"{deployment['change']}"
        )

    # Log evidence
    if "migration failed" in logs.lower():

        evidence.append(
            "Log pattern detected: migration failed"
        )

        risk = "High"

        resolution = [
            "Rollback deployment",
            "Validate schema migration",
            "Re-run migration"
        ]

    return {
        "root_cause": root_cause,
        "evidence": evidence,
        "resolution": resolution,
        "risk": risk
    }