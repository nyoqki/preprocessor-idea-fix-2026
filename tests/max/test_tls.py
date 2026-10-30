from collections.abc import Mapping

from yasno.max.tls import build_ssl_context


def _common_name(cert: Mapping[str, object]) -> str | None:
    subject = cert.get("subject")
    if not isinstance(subject, tuple):
        return None
    for rdn in subject:
        for key, value in rdn:
            if key == "commonName":
                return str(value)
    return None


def test_bundled_russian_root_is_trusted() -> None:
    names = {_common_name(cert) for cert in build_ssl_context().get_ca_certs()}
    assert "Russian Trusted Root CA" in names
