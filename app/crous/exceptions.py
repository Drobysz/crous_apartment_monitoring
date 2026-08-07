class CrousError(RuntimeError):
    pass


class CrousUnavailable(CrousError):
    pass


class CrousParseError(CrousError):
    pass


class CrousAuthenticationRequired(CrousError):
    pass
