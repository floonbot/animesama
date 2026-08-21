
class AnimeDownloaderError(Exception):
    pass

class DownloadError(AnimeDownloaderError):
    pass

class DownloadCancelled(AnimeDownloaderError, RuntimeError):

    def __init__(self, message: str = "Annulé par l'utilisateur"):
        super().__init__(message)

class RateLimitError(DownloadError):

    def __init__(self, message: str = "", domain: str = ""):
        super().__init__(message)
        self.domain = domain

class SecurityError(AnimeDownloaderError):
    pass

class UnsafeUrlError(SecurityError):
    pass
