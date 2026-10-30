import ssl
from importlib.resources import files
from pathlib import Path

import certifi


def build_ssl_context(extra_ca_file: Path | None = None) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    bundled = files("yasno.max").joinpath("certs/russian_trusted_root_ca.pem")
    context.load_verify_locations(cadata=bundled.read_text(encoding="ascii"))
    if extra_ca_file is not None:
        context.load_verify_locations(cafile=str(extra_ca_file))
    return context
