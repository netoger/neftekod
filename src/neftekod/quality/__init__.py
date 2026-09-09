"""Контроль качества входных данных."""

from .detectors import (  # noqa: F401
    ISSUE_TYPES,
    apply,
    combine,
    detect_all,
    issue_report,
)
