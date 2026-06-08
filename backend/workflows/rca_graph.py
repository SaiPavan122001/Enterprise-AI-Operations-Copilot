from typing import TypedDict

from langgraph.graph import StateGraph, END

from agents.incident_agent import incident_agent
from agents.deployment_agent import investigate_deployments
from agents.log_agent import investigate_logs
from agents.gemini_rca_agent import generate_gemini_rca


class RCAState(TypedDict):
    question: str
    incidents: list
    deployments: list
    logs: str
    rca_report: str


def incident_node(state):

    print("\n[LangGraph] Incident Agent Running")

    result = incident_agent(
        state["question"]
    )

    state["incidents"] = result["incident_results"]

    return state


def deployment_node(state):

    print("\n[LangGraph] Deployment Agent Running")

    state["deployments"] = investigate_deployments(state["incidents"])

    return state


def log_node(state):

    print("\n[LangGraph] Log Agent Running")

    state["logs"] = investigate_logs(state["incidents"])

    return state


def rca_node(state):

    print("\n[LangGraph] RCA Agent Running")

    state["rca_report"] = generate_gemini_rca(
        state["incidents"],
        state["deployments"],
        state["logs"]
    )

    return state

def router_node(state):

    print("\n[LangGraph] Investigation Started")

    return state

graph = StateGraph(RCAState)
graph.add_node("router", router_node)
graph.add_node("incident", incident_node)
graph.add_node("deployment", deployment_node)
graph.add_node("logs", log_node)
graph.add_node("rca", rca_node)

graph.set_entry_point("router")

graph.add_edge("router", "incident")
graph.add_edge("incident", "deployment")
graph.add_edge("deployment", "logs")
graph.add_edge("logs", "rca")
graph.add_edge("rca", END)

app = graph.compile()


if __name__ == "__main__":

    result = app.invoke(
        {
            "question": "Why is payroll failing?"
        }
    )

    print("\n========== FINAL RCA ==========\n")

    print(result["rca_report"])