class PrintMcpError(RuntimeError):
    code = "PRINT_ERROR"

    def __init__(self, message: str):
        super().__init__(f"{self.code}: {message}")


class InvalidInput(PrintMcpError):
    code = "INVALID_INPUT"


class ImageFetchFailed(PrintMcpError):
    code = "IMAGE_FETCH_FAILED"


class RenderFailed(PrintMcpError):
    code = "RENDER_FAILED"


class PrinterUnavailable(PrintMcpError):
    code = "PRINTER_UNAVAILABLE"


class UnsupportedOption(PrintMcpError):
    code = "UNSUPPORTED_OPTION"


class SubmissionFailed(PrintMcpError):
    code = "SUBMISSION_FAILED"


class JobNotFound(PrintMcpError):
    code = "JOB_NOT_FOUND"
