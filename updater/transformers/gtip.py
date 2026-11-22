"""
GTIP Transformer - TÜİK verisinden rates.json üretir.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import yaml

from .base import BaseTransformer


class GTIPTransformer(BaseTransformer):
    """
    TÜİK GTIP verisini rates.json formatına dönüştürür.
    Mevcut rates.json ile merge eder, yenileri ekler.
    """

    def __init__(self, config: Dict = None, mapping_config: Dict = None):
        super().__init__(config, mapping_config)
        self.output_path = Path(self.config.get("outputs", {}).get("rates_json", "rates.json"))

    def transform(self, raw_data: Dict) -> List[Dict]:
        """Ham GTIP verisini rates.json formatına çevir"""
        gtip_list = raw_data.get("gtip_list", [])
        existing_rates = self._load_existing_rates()

        # Yeni GTIP'leri işle
        new_entries = []
        updated_count = 0

        for item in gtip_list:
            gtip = item.get("gtip")
            if not gtip:
                continue

            # 6, 8, 10 hane versiyonlarını oluştur
            gtip_6 = gtip[:6]
            gtip_8 = gtip[:8] if len(gtip) >= 8 else None
            gtip_10 = gtip if len(gtip) == 10 else None

            # Mevcut rate varsa koru, yoksa yeni oluştur
            existing = existing_rates.get(gtip) or existing_rates.get(gtip_8) or existing_rates.get(gtip_6)

            entry = {
                "gtip": gtip,
                "rate": existing.get("rate", 0) if existing else 0,
                "unit": item.get("unit") or (existing.get("unit") if existing else ""),
                "note": item.get("note") or (existing.get("note") if existing else ""),
                "source": "tuik",
                "updated_at": datetime.now().isoformat(),
            }

            if existing:
                updated_count += 1
            else:
                new_entries.append(entry)

        # Mevcut rates.json'daki entry'leri de koru (TÜİK'te olmayabilir)
        all_entries = list(existing_rates.values())

        # Yeni entry'leri ekle
        for entry in new_entries:
            all_entries.append(entry)

        # GTIP koduna göre sırala
        all_entries.sort(key=lambda x: x.get("gtip", ""))

        self.stats["new_entries"] = len(new_entries)
        self.stats["updated_entries"] = updated_count
        self.stats["total_entries"] = len(all_entries)

        return all_entries

    def _load_existing_rates(self) -> Dict:
        """Mevcut rates.json'ı yükle"""
        if self.output_path.exists():
            try:
                with open(self.output_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {item.get("gtip", ""): item for item in data if item.get("gtip")}
            except Exception as e:
                self.logger.error(f"Failed to load existing rates.json: {e}")
        return {}

    def save(self, data: List[Dict]) -> bool:
        """rates.json olarak kaydet"""
        try:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Saved {len(data)} GTIP entries to {self.output_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save rates.json: {e}")
            return False