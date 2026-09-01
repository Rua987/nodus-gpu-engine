"""Nebius / Nemotron backend for the vendored Nodus runtime.

``register.apply()`` teaches ``nodus_backends`` (and the names already imported
into ``nodus_agent``) about the ``nebius:`` model prefix, without editing a
single line of ``packages/nodus``.
"""
from nge.backends import register  # noqa: F401
