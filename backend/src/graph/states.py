"""
Shared state schemas for the Brand Guardian Compliance QA Pipeline.

The schemas support:
- YouTube video ingestion
- Azure Video Indexer extraction
- Transcript and OCR evidence
- Grok OCR classification
- Policy applicability assessment
- Requirement-level compliance evaluation
- Evidence verification
- Deterministic audit decisions

Python: 3.12+
Framework: LangGraph
"""

from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()
import operator

from typing import Annotated, Any, Literal, TypedDict


# ============================================================
# COMMON STATUS TYPES
# ============================================================

IndexingStatus = Literal[
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
]

FinalAuditStatus = Literal[
    "PENDING",
    "PASS",
    "FAIL",
    "REVIEW_REQUIRED",
]

ProcessingStatus = Literal[
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "FAILED",
    "SKIPPED",
]

ApplicabilityStatus = Literal[
    "APPLICABLE",
    "NOT_APPLICABLE",
    "UNCERTAIN",
]

RequirementEvaluationStatus = Literal[
    "COMPLIANT",
    "NON_COMPLIANT",
    "INSUFFICIENT_EVIDENCE",
    "NOT_EVALUATED",
]

OCRClassificationCategory = Literal[
    "CLAIM",
    "DISCLOSURE",
    "DISCLAIMER",
    "PROMOTIONAL",
    "IRRELEVANT",
    "UNCERTAIN",
]

EvidenceModality = Literal[
    "TRANSCRIPT",
    "OCR",
    "METADATA",
]


# ============================================================
# VIDEO EXTRACTION STATUS
# ============================================================

class ExtractionStatus(TypedDict, total=False):
    """Status of each video ingestion and extraction operation."""

    download_status: ProcessingStatus
    conversion_status: ProcessingStatus
    upload_status: ProcessingStatus
    transcription_status: ProcessingStatus
    ocr_status: ProcessingStatus


# ============================================================
# VIDEO METADATA
# ============================================================

class VideoMetadata(TypedDict, total=False):
    """Metadata returned by Azure Video Indexer."""

    video_id: str
    name: str
    duration: float
    state: str
    platform: str
    width: int
    height: int
    frame_rate: float
    language: str
    description: str
    account_id: str


# ============================================================
# TRANSCRIPT EVIDENCE
# ============================================================

class TranscriptSegment(TypedDict, total=False):
    """Timestamped transcript segment."""

    id: str
    text: str
    content: str
    start: float
    end: float
    start_time: float
    end_time: float
    timestamp: str | float | int
    confidence: float
    speaker_id: str


# ============================================================
# OCR EVIDENCE
# ============================================================

class OCRSegment(TypedDict, total=False):
    """Raw or normalized on-screen text observation."""

    id: str
    text: str
    content: str
    start: float
    end: float
    start_time: float
    end_time: float
    timestamp: str | float | int
    confidence: float


class OCREvidenceClassification(TypedDict, total=False):
    """Grok classification associated with an OCR observation."""

    segment_index: int
    category: OCRClassificationCategory
    relevance_score: float
    reasoning: str

    # Original evidence linkage
    text: str
    timestamp: str | float | int | None
    start: float | None
    end: float | None


# ============================================================
# COMPLIANCE ISSUES
# ============================================================

class ComplianceIssue(TypedDict, total=False):
    """A detected compliance issue supported by video evidence."""

    issue_id: str
    category: str
    description: str

    severity: Literal[
        "CRITICAL",
        "HIGH",
        "MEDIUM",
        "LOW",
    ] | str

    timestamp: str | float | int | None

    evidence: str
    recommendation: str
    confidence: float
    detected_by: str


# ============================================================
# REGULATORY CITATIONS
# ============================================================

class RegulatoryCitation(TypedDict, total=False):
    """Reference to a retrieved regulatory document passage."""

    source: str
    page: int | None

    # Additional traceability fields
    chunk_id: str
    excerpt: str


# ============================================================
# POLICY EVIDENCE
# ============================================================

class PolicyEvidence(TypedDict, total=False):
    """
    A retrieved policy passage.

    Each policy passage should retain enough metadata
    to identify its source and support audit traceability.
    """

    source: str
    page: int | None
    chunk_id: str
    policy_text: str
    relevance_score: float


class PolicyDomainAssessment(TypedDict, total=False):
    """Applicability decision for one supported policy domain."""

    domain: Literal[
        "ADVERTISING_DISCLOSURES",
        "YOUTUBE_AD_SPECIFICATIONS",
    ]
    applicability: ApplicabilityStatus
    confidence: float
    rationale: str
    supporting_evidence: list[str]
    missing_information: list[str]
    context_basis: list[str]


class PolicyApplicabilityCoverage(TypedDict, total=False):
    """Applicability status for each supported policy domain."""

    ADVERTISING_DISCLOSURES: ApplicabilityStatus
    YOUTUBE_AD_SPECIFICATIONS: ApplicabilityStatus


# ============================================================
# SUPPORTING VIDEO EVIDENCE
# ============================================================

class SupportingEvidence(TypedDict, total=False):
    """Source observation supporting a requirement assessment."""

    modality: EvidenceModality

    # Verbatim source observation
    text: str

    # Source location
    timestamp: str | float | int | None
    segment_id: str
    evidence_id: str
    start: str | float | int | None
    end: str | float | int | None

    # Evidence verification result
    verified: bool


# ============================================================
# REQUIREMENT-LEVEL ASSESSMENT
# ============================================================

class RequirementAssessment(TypedDict, total=False):
    """
    Evaluation of one identifiable regulatory requirement.

    Applicability and compliance are deliberately separate.

    A requirement can be applicable but have insufficient
    evidence to determine whether it was satisfied.
    """

    requirement_id: str
    requirement_name: str
    domain: Literal[
        "ADVERTISING_DISCLOSURES",
        "YOUTUBE_AD_SPECIFICATIONS",
    ]

    applicability: ApplicabilityStatus

    evaluation_status: RequirementEvaluationStatus

    reasoning: str

    absence_observation: dict[str, Any] | None
    supporting_evidence: list[SupportingEvidence]

    regulatory_references: list[PolicyEvidence]

    confidence: float


# ============================================================
# POLICY COVERAGE
# ============================================================

class PolicyCoverage(TypedDict, total=False):
    """Summary of requirement assessment coverage."""

    total_identified: int

    applicable: int
    not_applicable: int
    uncertain: int

    compliant: int
    non_compliant: int
    insufficient_evidence: int
    not_evaluated: int


# ============================================================
# AUDIT DECISION REASONS
# ============================================================

class AuditDecisionReason(TypedDict, total=False):
    """Machine-readable explanation for the final decision."""

    code: str
    description: str
    related_requirement_ids: list[str]


# ============================================================
# AUDIT ERRORS
# ============================================================

class AuditError(TypedDict, total=False):
    """Sanitized application error recorded during processing."""

    node: str
    error_type: str
    message: str
    recoverable: bool
    timestamp: str


# ============================================================
# MAIN LANGGRAPH STATE
# ============================================================

class VideoAuditState(TypedDict, total=False):
    """
    Shared state passed between LangGraph nodes.

    Existing ingestion fields are retained.

    New policy assessment fields support requirement-level
    compliance evaluation and deterministic decisions.
    """

    # --------------------------------------------------------
    # VIDEO INPUT
    # --------------------------------------------------------

    video_url: str
    video_id: str
    audit_context: dict[str, Any]
    local_file_path: str | None

    # --------------------------------------------------------
    # AZURE VIDEO INDEXER
    # --------------------------------------------------------

    azure_video_id: str

    indexing_status: IndexingStatus | str

    extraction_status: ExtractionStatus

    # --------------------------------------------------------
    # VIDEO METADATA
    # --------------------------------------------------------

    metadata: VideoMetadata

    # --------------------------------------------------------
    # TRANSCRIPT EVIDENCE
    # --------------------------------------------------------

    transcript: str

    transcript_segments: list[TranscriptSegment]

    # --------------------------------------------------------
    # OCR EVIDENCE
    # --------------------------------------------------------

    ocr_text: str

    raw_ocr_segments: list[OCRSegment]

    ocr_segments: list[OCRSegment]

    ocr_classifications: list[OCREvidenceClassification]

    # --------------------------------------------------------
    # COMPLIANCE FINDINGS
    # --------------------------------------------------------

    compliance_results: Annotated[
        list[ComplianceIssue],
        operator.add,
    ]

    # --------------------------------------------------------
    # REGULATORY REFERENCES
    # --------------------------------------------------------

    citations: list[RegulatoryCitation]

    # --------------------------------------------------------
    # POLICY APPLICABILITY ASSESSMENT
    # --------------------------------------------------------

    policy_assessments: list[PolicyDomainAssessment]

    requirement_assessments: list[RequirementAssessment]

    # --------------------------------------------------------
    # REQUIREMENT COVERAGE
    # --------------------------------------------------------

    policy_coverage: PolicyApplicabilityCoverage

    requirement_coverage: PolicyCoverage
    audit_diagnostics: dict[str, Any]

    # --------------------------------------------------------
    # FINAL DECISION EXPLANATION
    # --------------------------------------------------------

    audit_decision_reasons: list[str]

    # --------------------------------------------------------
    # FINAL AUDIT RESULT
    # --------------------------------------------------------

    final_status: FinalAuditStatus | str

    final_report: str

    # --------------------------------------------------------
    # EXECUTION TRACKING
    # --------------------------------------------------------

    current_stage: str

    processing_complete: bool

    # --------------------------------------------------------
    # ERRORS
    # --------------------------------------------------------

    errors: Annotated[
        list[AuditError],
        operator.add,
    ]


POLICY_DOMAINS = (
    "ADVERTISING_DISCLOSURES",
    "YOUTUBE_AD_SPECIFICATIONS",
)
