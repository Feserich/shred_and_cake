"""Ski Basar web application."""

try:
    # Written by packaging/skibasar.spec from the git tag (e.g. "v0.3.0-beta")
    from ._version import __version__
except ImportError:
    __version__ = "dev"
