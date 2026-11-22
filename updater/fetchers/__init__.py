"""
Vergi oranı çekicileri (fetchers) paketi.
Her resmi kaynak için özel fetcher sınıfları içerir.
"""
from .base import BaseFetcher, FetchResult, FetchError
from .resmigazete import ResmiGazeteFetcher
from .gib import GIBFetcher
from .tuik import TUİKFetcher as TUIKFetcher
from .cumhurbaskani import CumhurbaskaniFetcher
from .pdf_parser import PDFTableParser

__all__ = [
    "BaseFetcher",
    "FetchResult",
    "FetchError",
    "ResmiGazeteFetcher",
    "GIBFetcher",
    "TUİKFetcher",
    "CumhurbaskaniFetcher",
    "PDFTableParser",
]