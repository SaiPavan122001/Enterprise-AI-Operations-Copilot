def investigate_logs(incidents):

    with open("data/logs.txt", "r") as f:
        logs = f.readlines()

    services = {
        incident["service"]
        for incident in incidents
    }

    relevant_logs = []

    for line in logs:

        for service in services:

            if service in line:
                relevant_logs.append(line)

    return "\n".join(relevant_logs[:50])