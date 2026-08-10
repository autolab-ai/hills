"""Exception types. Everything the CLI reports to a user is a HillsError."""


class HillsError(Exception):
    """A failure with a message meant for the person or agent running the command."""


class HillNotFound(HillsError):
    pass


class ManifestError(HillsError):
    pass


class CoreSchemaError(HillsError):
    """The dict returned by eval() does not match the evaluator contract."""


class LockMismatch(HillsError):
    """Content on disk disagrees with the lock files committed at HEAD."""


class DirtyHill(HillsError):
    pass


class EvaluatorFailed(HillsError):
    pass


class DeviceBusy(HillsError):
    pass
