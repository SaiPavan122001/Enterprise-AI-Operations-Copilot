from fastapi import APIRouter

from vector_store.search_service import search_incidents
from workflows.rca_graph import app as rca_graph

router = APIRouter()


@router.get("/health")
def health():

    return {
        "status": "healthy"
    }


@router.post("/search")
def search(query: str):

    results = search_incidents(
        query=query
    )

    output = []

    for point in results:

        output.append(
            point.payload
        )

    return output


@router.post("/investigate")
def investigate(question: str):

    result = rca_graph.invoke(
        {
            "question": question
        }
    )

    return {
          "report": result["rca_report"]
    }