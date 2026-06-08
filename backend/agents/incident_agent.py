from vector_store.search_service import search_incidents


def incident_agent(query):
    print("[Incident Agent] Searching Qdrant...")

    results = search_incidents(
        query=query,
        limit=5
    )

    incidents = []

    for point in results:
        incidents.append(point.payload)

    return {
        "incident_results": incidents
    }