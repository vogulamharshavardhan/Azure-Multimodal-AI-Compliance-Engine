"""Best-effort progress callbacks scoped to a single worker execution."""
from contextvars import ContextVar
import logging
callback = ContextVar('audit_progress', default=None)

def emit(stage):
    fn = callback.get()
    if fn:
        try:
            fn(stage)
        except Exception:
            logging.getLogger(__name__).warning('Progress persistence failed')
