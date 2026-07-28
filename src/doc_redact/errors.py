class DocRedactError(Exception):
    """Expected, safe-to-show application error."""


class InputRejected(DocRedactError):
    pass


class ProcessingFailed(DocRedactError):
    pass


class VerificationFailed(ProcessingFailed):
    pass

