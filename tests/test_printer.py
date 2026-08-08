from print_mcp.printer import redact_uri


def test_redacts_credentials_from_printer_uri() -> None:
    assert redact_uri("ipps://user:secret@printer.example:631/ipp/print") == (
        "ipps://printer.example:631/ipp/print"
    )


def test_keeps_uri_without_credentials() -> None:
    uri = "ipp://printer.example/ipp/print"
    assert redact_uri(uri) == uri
