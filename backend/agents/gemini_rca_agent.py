from google import genai
from dotenv import load_dotenv
import os

from observability.langfuse_client import langfuse

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


def generate_gemini_rca(
    incidents,
    deployments,
    logs
):

    incidents_summary = str(incidents)[:2000]
    deployments_summary = str(deployments)[:2000]
    logs_summary = str(logs)[:3000]

    prompt = f"""
You are a Senior Site Reliability Engineer.

Analyze the following investigation data.

Incidents:
{incidents_summary}

Deployments:
{deployments_summary}

Logs:
{logs_summary}

Generate:

1. Root Cause
2. Evidence
3. Resolution
4. Risk Assessment
5. Preventive Actions
"""

    try:

        print("\n========== GEMINI DEBUG ==========")
        print("Incidents Length:", len(incidents_summary))
        print("Deployments Length:", len(deployments_summary))
        print("Logs Length:", len(logs_summary))
        print("Total Prompt Length:", len(prompt))
        print("==================================\n")

        # Langfuse Observation
        observation = langfuse.start_observation(
            name="rca-investigation"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        report = response.text

        langfuse.create_event(
            name="gemini-rca-generated",
        )

        langfuse.flush()

        print("\n========== GEMINI SUCCESS ==========")
        print("Gemini generated RCA successfully")
        print("====================================\n")

        return report

    except Exception as e:

        print("\n========== GEMINI ERROR ==========")
        print("Error Type:", type(e))
        print("Error:", e)
        print("==================================\n")

        error_report = f"""
# RCA REPORT

Gemini analysis unavailable.

## Possible Root Cause
Deployment or infrastructure issue detected.

## Evidence
Incidents Found: {len(incidents)}
Deployments Found: {len(deployments)}
Logs Length: {len(str(logs))}

## Error
{str(e)}
"""

        return error_report