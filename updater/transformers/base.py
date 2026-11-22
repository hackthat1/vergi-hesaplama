"""
Transformer base sınıfı.
"""
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional


class BaseTransformer:
    """Tüm transformer'lar için temel sınıf"""

    def __init__(self, config: Dict = None, mapping_config: Dict = None):
        self.config = config or {}
        self.mapping_config = mapping_config or {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.stats = {}

    def transform(self, raw_data: Dict) -> Any:
        """Veriyi dönüştür - alt sınıflar implement eder"""
        raise NotImplementedError

    def save(self, data: Any) -> bool:
        """Veriyi kaydet - alt sınıflar implement eder"""
        raise NotImplementedError

    def load_mapping(self, key: str) -> Any:
        """Mapping config'ten değer al"""
        return self.mapping_config.get(key)

    def get_default(self, key: str) -> Any:
        """Default değer al"""
        defaults = self.mapping_config.get("defaults", {})
        return defaults.get(key)

    def normalize_gtip(self, gtip: str) -> str:
        """GTIP kodunu normalize et"""
        import re
        digits = re.sub(r"[^\d]", "", gtip)
        return digits

    def get_gtip_variants(self, gtip: str) -> List[str]:
        """GTIP'nin 6, 8, 10 hane varyantlarını döndür"""
        variants = []
        if len(gtip) >= 6:
            variants.append(gtip[:6])
        if len(gtip) >= 8:
            variants.append(gtip[:8])
        if len(gtip) == 10:
            variants.append(gtip)
        return variants