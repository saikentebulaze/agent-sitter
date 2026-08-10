"""Codex runtime provider package.

Keep package initialization side-effect free. The registry imports the concrete
provider lazily so legacy modules can import provider-local profile types
without pulling in attestation code and creating circular imports.
"""
