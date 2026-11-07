"""Expected Amazon-related failures. Messages are safe to show to end users."""


class AmazonError(Exception):
    """Base class for all expected Amazon-related failures."""


class InvalidUrlError(AmazonError):
    """The text does not contain a supported product link."""


class FetchError(AmazonError):
    """The page could not be downloaded."""


class BlockedError(FetchError):
    """Amazon answered with a CAPTCHA or throttled the request."""


class ParseError(AmazonError):
    """The page was downloaded but the price could not be read from it."""
