"""
Make Python trust the certificates Windows already trusts.

WHY

Antivirus suites with HTTPS scanning (Norton Web/Mail Shield, Kaspersky,
Avast, ESET...) and corporate proxies decrypt and re-sign every HTTPS
connection with their own root certificate. They install that root into the
Windows certificate store, so browsers and curl keep working. Python does
not read that store: requests uses certifi's bundled list and yfinance's
curl_cffi uses its own, so every download fails with

    CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate

and the run silently produces "prices 0/5 fundamentals 0/5" for everyone.

WHAT THIS DOES

On Windows only, it writes .cache/ca_bundle.pem = certifi's list + every
certificate in the Windows ROOT and CA stores, and points REQUESTS_CA_BUNDLE,
CURL_CA_BUNDLE and SSL_CERT_FILE at it. Verification stays fully ON; Python
simply trusts the same authorities the rest of the machine already does.

It never overrides a bundle the user has already set, and does nothing when
config.USE_SYSTEM_CERTS is False or on any other platform.
"""

import os
import ssl
import sys

import config

_ENV_VARS = ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE")


def install():
    """-> path of the bundle in use, or None when nothing was changed."""
    if not getattr(config, "USE_SYSTEM_CERTS", True) or not sys.platform.startswith("win"):
        return None
    if any(os.environ.get(v) for v in _ENV_VARS):
        return None
    try:
        import certifi

        pem = open(certifi.where(), encoding="utf-8").read()
        for store in ("ROOT", "CA"):
            for der, encoding, _trust in ssl.enum_certificates(store):
                if encoding == "x509_asn":
                    pem += ssl.DER_cert_to_PEM_cert(der)

        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = config.CACHE_DIR / "ca_bundle.pem"
        path.write_text(pem, encoding="utf-8")
    except Exception:
        # Never let a convenience stop the program; the download errors that
        # follow will say what went wrong.
        return None

    for v in _ENV_VARS:
        os.environ[v] = str(path)
    return path
