"""
Temel Fetcher sınıfları ve yardımcı tipler.
Tüm fetcher'lar bu sınıftan türetilir.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from pathlib import Path
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Fetch işlemi sonucu"""
    source_name: str
    success: bool
    data: Any = None
    raw_content: Optional[bytes] = None
    content_hash: Optional[str] = None
    fetched_at: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "source_name": self.source_name,
            "success": self.success,
            "fetched_at": self.fetched_at.isoformat(),
            "error": self.error,
            "metadata": self.metadata,
            "content_hash": self.content_hash,
            "data_preview": str(self.data)[:200] if self.data else None,
        }


class FetchError(Exception):
    """Fetch hatası"""
    def __init__(self, source: str, message: str, original: Optional[Exception] = None):
        self.source = source
        self.original = original
        super().__init__(f"[{source}] {message}")


class BaseFetcher(ABC):
    """
    Tüm fetcher'lar için temel sınıf.
    Ortak fonksiyonları sağlar: HTTP istekleri, cache, hash, retry.
    """

    def __init__(
        self,
        source_name: str,
        config: Dict,
        cache_dir: Optional[Path] = None,
        session=None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.source_name = source_name
        self.config = config
        self.cache_dir = cache_dir or Path("updater/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = session

    @property
    def session(self):
        """Lazy session initialization"""
        if self._session is None:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            self._session = requests.Session()
            retry_strategy = Retry(
                total=self.max_retries,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS"],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)

            # Default headers
            self._session.headers.update({
                "User-Agent": "Mozilla/5.0 (compatible; VergiHesaplamaBot/1.0; +https://github.com/hackthat1/vergi-hesaplama)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            })
            # Config'den özel header'lar
            if "headers" in self.config:
                self._session.headers.update(self.config["headers"])

        return self._session

    def fetch(self, url: str, **kwargs) -> FetchResult:
        """Ana fetch metodu - alt sınıflar override eder"""
        try:
            content = self._fetch_raw(url, **kwargs)
            content_hash = hashlib.sha256(content).hexdigest()[:16]

            # Cache'e yaz
            cache_file = self.cache_dir / f"{self.source_name}_{content_hash}.bin"
            cache_file.write_bytes(content)

            data = self.parse(content, url)

            return FetchResult(
                source_name=self.source_name,
                success=True,
                data=data,
                raw_content=content,
                content_hash=content_hash,
                metadata={"url": url, "cache_file": str(cache_file)},
            )
        except Exception as e:
            logger.error(f"Fetch failed for {self.source_name}: {e}")
            return FetchResult(
                source_name=self.source_name,
                success=False,
                error=str(e),
                metadata={"url": url},
            )

    def _fetch_raw(self, url: str, **kwargs) -> bytes:
        """Ham içerik indir"""
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response.content

    @abstractmethod
    def parse(self, content: bytes, url: str) -> Any:
        """İçeriği parse et - alt sınıflar implement eder"""
        pass

    def fetch_multiple(self, urls: List[str]) -> List[FetchResult]:
        """Birden fazla URL fetch et"""
        results = []
        for url in urls:
            logger.info(f"Fetching: {url}")
            result = self.fetch(url)
            results.append(result)
            if not result.success:
                logger.warning(f"Failed: {url} - {result.error}")
        return results

    def load_cache(self, content_hash: str) -> Optional[bytes]:
        """Cache'den yükle"""
        cache_file = self.cache_dir / f"{self.source_name}_{content_hash}.bin"
        if cache_file.exists():
            return cache_file.read_bytes()
        return None

    def close(self):
        """Session kapat"""
        if self._session:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class HTMLFetcherMixin:
    """HTML parsing yardımcıları"""

    @staticmethod
    def extract_tables(html: bytes, table_index: int = 0) -> List[List[List[str]]]:
        """HTML'den tablo çıkar"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        tables = soup.find_all("table")
        if table_index >= len(tables):
            return []

        table = tables[table_index]
        rows = []
        for tr in table.find_all("tr"):
            row = []
            for td in tr.find_all(["td", "th"]):
                text = td.get_text(strip=True)
                row.append(text)
            if row:
                rows.append(row)
        return rows

    @staticmethod
    def extract_links(html: bytes, base_url: str = "") -> List[Dict[str, str]]:
        """HTML'den linkleri çıkar"""
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if base_url:
                href = urljoin(base_url, href)
            links.append({
                "url": href,
                "text": a.get_text(strip=True),
                "title": a.get("title", ""),
            })
        return links

    @staticmethod
    def find_pdf_links(html: bytes, base_url: str = "", keywords: List[str] = None) -> List[str]:
        """PDF linklerini bul"""
        links = HTMLFetcherMixin.extract_links(html, base_url)
        pdf_links = []
        for link in links:
            if link["url"].lower().endswith(".pdf"):
                if keywords:
                    text = (link["text"] + " " + link["title"]).lower()
                    if any(kw.lower() in text for kw in keywords):
                        pdf_links.append(link["url"])
                else:
                    pdf_links.append(link["url"])
        return pdf_links


class PDFFetcherMixin:
    """PDF indirme ve işleme yardımcıları"""

    @staticmethod
    def download_pdf(session, url: str, output_path: Path) -> bool:
        """PDF indir"""
        try:
            response = session.get(url, timeout=60, stream=True)
            response.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"PDF download failed: {url} - {e}")
            return False

    @staticmethod
    def extract_text_from_pdf(pdf_path: Path) -> str:
        """PDF'den metin çıkar (pdfplumber)"""
        import pdfplumber
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
        return "\n".join(text_parts)