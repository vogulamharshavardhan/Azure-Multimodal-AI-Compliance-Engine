"""Typed application exceptions with safe API-facing messages.

Never include credentials, access tokens, signed URLs, or raw request headers
in exception messages. Detailed diagnostics belong in server-side logs.
"""


class CompliancePipelineError(Exception):
    """Base class for expected compliance pipeline failures."""

    status_code = 500
    public_message = "The compliance pipeline could not complete the request."


class ConfigurationError(CompliancePipelineError):
    """Required application configuration is missing or invalid."""

    status_code = 503
    public_message = "The service is not configured correctly. Check server logs."


class IngestionError(CompliancePipelineError):
    """Video download, conversion, upload, or indexing failed."""

    status_code = 502
    public_message = "Video ingestion failed. Check server logs for details."


class YouTubeDownloadError(IngestionError):
    """YouTube video download or validation failed."""

    public_message = "The supplied YouTube video could not be downloaded."


class VideoProcessingError(IngestionError):
    """Video probing, transcoding, or media validation failed."""

    public_message = "Video processing failed. Check server logs for details."


class BlobStorageError(IngestionError):
    """Temporary Azure Blob Storage upload or cleanup failed."""

    public_message = "Temporary video storage failed. Check server logs."


class VideoIndexerError(IngestionError):
    """Azure Video Indexer authentication, upload, or extraction failed."""

    public_message = "Azure Video Indexer processing failed. Check server logs."


class RetrievalError(CompliancePipelineError):
    """Embedding generation or policy retrieval failed."""

    status_code = 502
    public_message = "Policy evidence retrieval failed. Check server logs for details."


class AuditError(CompliancePipelineError):
    """Compliance reasoning or evidence validation failed."""

    status_code = 500
    public_message = "Compliance evaluation failed. Check server logs for details."


class PipelineExecutionError(CompliancePipelineError):
    """The end-to-end LangGraph workflow failed unexpectedly."""

    status_code = 500
    public_message = (
        "The compliance workflow failed unexpectedly. "
        "Check the server logs using the request timestamp."
    )


class DocumentIndexingError(CompliancePipelineError):
    """Regulatory PDF loading, chunking, or indexing failed."""

    status_code = 500
    public_message = "Regulatory document indexing failed. Check server logs."
