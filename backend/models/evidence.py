"""Structured evidence and investigation models.

These types are the contract between the retrieval agents, the evidence
validation stage, the Gemini RCA generation and the API layer. Nothing in
the pipeline passes arbitrary dictionaries between stages anymore.
"""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

EvidenceStrength = Literal["HIGH", "MEDIUM", "LOW", "INSUFFICIENT"]
InvestigationStatus = Literal["success", "error"]


class IncidentEvidence(BaseModel):
    incident_id: str
    service: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    title: Optional[str] = None
    root_cause: Optional[str] = None
    deployment_id: Optional[str] = None
    relevance_score: Optional[float] = None


class DeploymentEvidence(BaseModel):
    deployment_id: str
    service: Optional[str] = None
    change: Optional[str] = None
    time: Optional[str] = None


class LogEvidence(BaseModel):
    timestamp: Optional[str] = None
    level: Optional[str] = None
    service: Optional[str] = None
    message: str
    source: str = "logs.txt"


class RunbookEvidence(BaseModel):
    name: str
    title: str
    content: str


class RetrievalMetadata(BaseModel):
    incident_count: int = 0
    deployment_count: int = 0
    log_count: int = 0
    runbook_count: int = 0
    min_relevance_score: Optional[float] = None
    retrieval_errors: list[str] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    question: str
    incident_evidence: list[IncidentEvidence] = Field(default_factory=list)
    deployment_evidence: list[DeploymentEvidence] = Field(default_factory=list)
    log_evidence: list[LogEvidence] = Field(default_factory=list)
    runbook_evidence: Optional[RunbookEvidence] = None
    retrieval_metadata: RetrievalMetadata = Field(default_factory=RetrievalMetadata)
    investigation_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EvidenceValidation(BaseModel):
    incident_found: bool = False
    deployment_found: bool = False
    logs_found: bool = False
    runbook_found: bool = False
    evidence_strength: EvidenceStrength = "INSUFFICIENT"
    notes: list[str] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    timestamp: str
    event: str
    source: Literal["deployments.json", "logs.txt"]


class InvestigationResult(BaseModel):
    """Structured RCA response - the primary API payload."""

    question: str
    status: InvestigationStatus = "success"
    summary: Optional[str] = None
    impact: Optional[str] = None
    root_cause: Optional[str] = None
    confidence: EvidenceStrength = "INSUFFICIENT"
    evidence_strength: EvidenceStrength = "INSUFFICIENT"
    contributing_factors: list[str] = Field(default_factory=list)
    recommended_remediation: list[str] = Field(default_factory=list)
    preventive_actions: list[str] = Field(default_factory=list)
    observed_evidence: list[str] = Field(default_factory=list)
    investigation_details: Optional[str] = None
    timeline: list[TimelineEvent] = Field(default_factory=list)
    evidence: EvidenceBundle
    validation: EvidenceValidation
    report_markdown: Optional[str] = None  # full markdown fallback
    message: Optional[str] = None
