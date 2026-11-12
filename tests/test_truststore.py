"""HTTPS is checked against the OS certificate store, so a company network that re-signs
sites with its own root (installed by IT in that store) does not break every fetch (2026-11-12)."""
import ssl

import app  # noqa: F401  (importing the package is what switches it on)


def test_ssl_contexts_use_the_system_store():
    import truststore
    assert ssl.SSLContext is truststore.SSLContext
    assert isinstance(ssl.create_default_context(), truststore.SSLContext)
