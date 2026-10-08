"""Compatibility exports; historical epoch retirement owns both recovery paths."""
from . import historical_retirement as epoch
from .historical_retirement import (
    journal,
    _native_prepare as prepare,
    _native_context as context,
    _native_review_source as review_source,
    _native_execute as execute,
)
