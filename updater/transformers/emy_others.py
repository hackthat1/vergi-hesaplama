"""
EMY, Bandrol, KKDF, Damping Transformer.
Ek mali yükümlülük oranlarını taxes.json'a işler.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import defaultdict

from .base import BaseTransformer


class EMYOthersTransformer(BaseTransformer):
    """EMY, Bandrol, KKDF, Damping oranlarını taxes.json formatına dönüştürür"""

    def __init__(self, config: Dict = None, mapping_config: Dict = None):
        super().__init__(config, mapping_config)
        self.output_path = Path(self.config.get("outputs", {}).get("taxes_json", "taxes.json"))

    def transform(self, raw_data: Dict) -> Dict[str, Dict]:
        """Ham EMY/others verisini taxes.json formatına çevir"""
        existing_taxes = self._load_existing_taxes()

        # Her vergi türü için verileri topla
        emy_by_gtip = defaultdict(list)
        bandrol_by_gtip = defaultdict(list)
        kkdf_by_gtip = defaultdict(list)
        damping_by_gtip = defaultdict(list)

        for source_name, source_data in raw_data.items():
            if not isinstance(source_data, dict):
                continue

            documents = source_data.get("documents", [])
            for doc in documents:
                search_term = doc.get("search_term", "").upper()
                data = doc.get("data", [])

                for item in data:
                    gtip = item.get("gtip")
                    if not gtip:
                        continue

                    rate = item.get("rate")
                    if rate is None:
                        continue

                    # Hangi vergi türü?
                    tax_type = self._identify_tax_type(item, search_term)

                    entry = {
                        "rate": rate,
                        "source": source_name,
                        "note": item.get("note", ""),
                        "unit": item.get("unit", ""),
                        "doc_url": doc.get("pdf_url", ""),
                        "fetched_at": doc.get("fetched_at", ""),
                    }

                    if tax_type == "EMY":
                        emy_by_gtip[gtip].append(entry)
                    elif tax_type == "BANDROL":
                        bandrol_by_gtip[gtip].append(entry)
                    elif tax_type == "KKDF":
                        kkdf_by_gtip[gtip].append(entry)
                    elif tax_type == "DAMPING":
                        damping_by_gtip[gtip].append(entry)

        # Her birini güncelle
        stats = {"emy": 0, "bandrol": 0, "kkdf": 0, "damping": 0}

        for gtip, entries in emy_by_gtip.items():
            best = self._select_best_entry(entries)
            self._update_tax_field(existing_taxes, gtip, "emy", best, stats, "emy")

        for gtip, entries in bandrol_by_gtip.items():
            best = self._select_best_entry(entries)
            self._update_tax_field(existing_taxes, gtip, "bandrol", best, stats, "bandrol")

        for gtip, entries in kkdf_by_gtip.items():
            best = self._select_best_entry(entries)
            self._update_tax_field(existing_taxes, gtip, "kkdf", best, stats, "kkdf")

        for gtip, entries in damping_by_gtip.items():
            best = self._select_best_entry(entries)
            self._update_tax_field(existing_taxes, gtip, "damping", best, stats, "damping")

        self.stats = stats
        return existing_taxes

    def _identify_tax_type(self, item: Dict, search_term: str) -> str:
        """Öğenin hangi vergi türüne ait olduğunu belirle"""
        note = item.get("note", "").upper()
        tax_type = item.get("tax_type", "").upper()

        if tax_type:
            return tax_type

        if "EMY" in search_term or "EK MALI" in search_term or "EMY" in note:
            return "EMY"
        if "BANDROL" in search_term or "BANDROL" in note:
            return "BANDROL"
        if "KKDF" in search_term or "KAYNAK KULLANIM" in search_term or "KKDF" in note:
            return "KKDF"
        if "DAMPING" in search_term or "FIYAT DESTEK" in search_term or "DAMPING" in note:
            return "DAMPING"

        # Default: note içinden tahmin et
        if "EMY" in note:
            return "EMY"
        if "BANDROL" in note:
            return "BANDROL"
        if "KKDF" in note:
            return "KKDF"
        if "DAMPING" in note:
            return "DAMPING"

        return "EMY"  # Default

    def _select_best_entry(self, entries: List[Dict]) -> Dict:
        priority = {"cumhurbaskani": 3, "resmigazete": 2, "gib": 1}

        def get_priority(e):
            source = e.get("source", "").lower()
            for k, v in priority.items():
                if k in source:
                    return v
            return 0

        sorted_entries = sorted(entries, key=lambda e: (
            -get_priority(e),
            e.get("fetched_at", ""),
        ), reverse=True)

        return sorted_entries[0] if sorted_entries else {"rate": 0}

    def _update_tax_field(self, taxes: Dict, gtip: str, field: str, best: Dict, stats: Dict, stat_key: str):
        """Vergi alanını güncelle"""
        gtip_key = gtip

        if gtip_key in taxes:
            taxes[gtip_key][field] = best["rate"]
            taxes[gtip_key][f"{field}_note"] = best.get("note", "")
            taxes[gtip_key][f"{field}_source"] = best.get("source", "")
            taxes[gtip_key][f"{field}_updated"] = datetime.now().isoformat()
            stats[stat_key] += 1
        else:
            new_entry = self._create_default_tax_entry(gtip_key)
            new_entry[field] = best["rate"]
            new_entry[f"{field}_note"] = best.get("note", "")
            new_entry[f"{field}_source"] = best.get("source", "")
            new_entry[f"{field}_updated"] = datetime.now().isoformat()
            taxes[gtip_key] = new_entry

    def _create_default_tax_entry(self, gtip: str) -> Dict:
        defaults = self.mapping_config.get("defaults", {})
        return {
            "gtip": gtip,
            "gv": defaults.get("gv", 0),
            "kdv": defaults.get("kdv", 20),
            "otv": defaults.get("otv", 0),
            "otv_type": defaults.get("otv_type", "ORANALI"),
            "igv": defaults.get("igv", 0),
            "emy": defaults.get("emy", 0),
            "bandrol": defaults.get("bandrol", 0),
            "kkdf": defaults.get("kkdf", 0),
            "damping": defaults.get("damping", 0),
            "kultur": defaults.get("kultur", 0),
            "note": "",
            "source": "auto_generated",
            "created_at": datetime.now().isoformat(),
        }

    def _load_existing_taxes(self) -> Dict:
        if self.output_path.exists():
            try:
                with open(self.output_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {item.get("gtip", ""): item for item in data if item.get("gtip")}
                    elif isinstance(data, dict):
                        return data
            except Exception as e:
                self.logger.error(f"Failed to load existing taxes.json: {e}")
        return {}

    def save(self, data: Dict) -> bool:
        try:
            tax_list = list(data.values())
            tax_list.sort(key=lambda x: x.get("gtip", ""))

            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_path, "w", encoding="utf-8") as f:
                json.dump(tax_list, f, ensure_ascii=False, indent=2)

            self.logger.info(f"Saved {len(tax_list)} tax entries to {self.output_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save taxes.json: {e}")
            return False