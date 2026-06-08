from incident_agent import investigate_incidents
from deployment_agent import investigate_deployments
from log_agent import investigate_logs
from rca_agent import generate_rca


incidents = investigate_incidents()

deployments = investigate_deployments()

logs = investigate_logs()

report = generate_rca(
    incidents,
    deployments,
    logs
)

print("\n========== RCA REPORT ==========\n")

print(report)