"""
JSON Şema Doğrulayıcı.
taxes.json ve rates.json için şema doğrulama.
"""
import json
import jsonschema
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


# taxes.json şeması
TAXES_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["gtip", "gv", "kdv", "otv"],
        "properties": {
            "gtip": {"type": "string", "pattern": "^\\d{6,10}$"},
            "gv": {"type": "number", "minimum": 0, "maximum": 100},
            "kdv": {"type": "number", "minimum": 0, "maximum": 25},
            "otv": {"type": "number", "minimum": 0},
            "otv_type": {"type": "string", "enum": ["ORANALI", "MUKTESEP", "KARMA"]},
            "igv": {"type": "number", "minimum": 0, "maximum": 100},
            "emy": {"type": "number", "minimum": 0, "maximum": 100},
            "bandrol": {"type": "number", "minimum": 0, "maximum": 100},
            "kkdf": {"type": "number", "minimum": 0, "maximum": 10},
            "damping": {"type": "number", "minimum": 0, "maximum": 100},
            "kultur": {"type": "number", "minimum": 0, "maximum": 100},
            "note": {"type": "string"},
            "source": {"type": "string"},
            "created_at": {"type": "string", "format": "date-time"},
            # Metadata alanları
            "gv_note": {"type": "string"},
            "gv_source": {"type": "string"},
            "gv_updated": {"type": "string"},
            "kdv_note": {"type": "string"},
            "kdv_source": {"type": "string"},
            "kdv_updated": {"type": "string"},
            "otv_note": {"type": "string"},
            "otv_source": {"type": "string"},
            "otv_updated": {"type": "string"},
            "emy_note": {"type": "string"},
            "emy_source": {"type": "string"},
            "emy_updated": {"type": "string"},
            "bandrol_note": {"type": "string"},
            "bandrol_source": {"type": "string"},
            "bandrol_updated": {"type": "string"},
            "kkdf_note": {"type": "string"},
            "kkdf_source": {"type": "string"},
            "kkdf_updated": {"type": "string"},
            "damping_note": {"type": "string"},
            "damping_source": {"type": "string"},
            "damping_updated": {"type": "string"},
        },
    },
    "minItems": 1,
}


# rates.json şeması
RATES_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["gtip"],
        "properties": {
            "gtip": {"type": "string", "pattern": "^\\d{6,10}$"},
            "rate": {"type": "number", "minimum": 0},
            "unit": {"type": "string"},
            "note": {"type": "string"},
            "source": {"type": "string"},
            "updated_at": {"type": "string", "format": "date-time"},
        },
    },
    "minItems": 1,
}


class TaxSchemaValidator:
    """Vergi verileri için şema doğrulayıcı"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.validation_config = self.config.get("validation", {})

    def validate_taxes(self, data: List[Dict]) -> Dict[str, Any]:
        """taxes.json verisini doğrula"""
        errors = []
        warnings = []

        # Şema doğrulama
        try:
            jsonschema.validate(instance=data, schema=TAXES_SCHEMA)
        except jsonschema.ValidationError as e:
            errors.append(f"Schema validation: {e.message} at {e.json_path}")

        # İş kuralları doğrulama
        gtip_set = set()
        for i, item in enumerate(data):
            gtip = item.get("gtip", "")

            # Duplicate GTIP kontrolü
            if gtip in gtip_set:
                warnings.append(f"Row {i}: Duplicate GTIP {gtip}")
            gtip_set.add(gtip)

            # Oran aralıkları
            self._validate_rate_ranges(item, i, warnings)

            # GTIP hiyerarşisi (10 hane varsa 8 ve 6 haneli de var mı?)
            # Bu bilgi rates.json'dan gelir, burada sadece uyarı

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "record_count": len(data),
        }

    def validate_rates(self, data: List[Dict]) -> Dict[str, Any]:
        """rates.json verisini doğrula"""
        errors = []
        warnings = []

        try:
            jsonschema.validate(instance=data, schema=RATES_SCHEMA)
        except jsonschema.ValidationError as e:
            errors.append(f"Schema validation: {e.message} at {e.json_path}")

        gtip_set = set()
        for i, item in enumerate(data):
            gtip = item.get("gtip", "")

            if gtip in gtip_set:
                warnings.append(f"Row {i}: Duplicate GTIP {gtip}")
            gtip_set.add(gtip)

            # Rate 0 olanları uyar
            if item.get("rate", 0) == 0:
                warnings.append(f"Row {i} (GTIP {gtip}): Rate is 0")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "record_count": len(data),
        }

    def _validate_rate_ranges(self, item: Dict, index: int, warnings: List[str]):
        """Oran aralıklarını kontrol et"""
        ranges = self.validation_config.get("rate_ranges", {})

        checks = [
            ("gv", "gv", 0, 100),
            ("kdv", "kdv", 0, 25),
            ("otv_oranli", "otv", 0, 100),  # OTV oranlı için
            ("otv_muktessep", "otv", 0, 10000),  # OTV müktesep için (TL/birim)
            ("igv", "igv", 0, 100),
            ("emy", "emy", 0, 100),
            ("bandrol", "bandrol", 0, 100),
            ("kkdf", "kkdf", 0, 10),
            ("damping", "damping", 0, 100),
        ]

        for config_key, field, min_val, max_val in checks:
            if field in item:
                value = item[field]
                if value is not None:
                    # Liste ise (eski format), ilk elemanı al veya atla
                    if isinstance(value, list):
                        if len(value) > 0 and isinstance(value[0], (int, float)):
                            value = value[0]
                        else:
                            continue  # Listeyse atla

                    # OTV için tür kontrolü
                    if field == "otv":
                        otv_type = item.get("otv_type", "ORANALI")
                        if otv_type == "MUKTESEP":
                            max_val = ranges.get("otv_muktessep", [0, 10000])[1]
                        else:
                            max_val = ranges.get("otv_oranli", [0, 100])[1]

                    if isinstance(value, (int, float)):
                        if value < min_val or value > max_val:
                            warnings.append(
                                f"Row {index} (GTIP {item.get('gtip')}): "
                                f"{field}={value} out of range [{min_val}, {max_val}]"
                            )


def _normalize_taxes_data(data: Any) -> List[Dict]:
    """taxes.json verisini liste formatına normalize et"""
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        # {"taxes": {...}} formatı
        if "taxes" in data and isinstance(data["taxes"], dict):
            result = []
            for gtip, entry in data["taxes"].items():
                if isinstance(entry, dict):
                    entry = entry.copy()
                    entry["gtip"] = gtip
                    result.append(entry)
            return result
        # {gtip: {...}} formatı
        elif all(isinstance(v, dict) for v in data.values()):
            result = []
            for gtip, entry in data.items():
                entry = entry.copy()
                entry["gtip"] = gtip
                result.append(entry)
            return result
    return []


def validate_files(taxes_path: str = "taxes.json", rates_path: str = "rates.json", config_path: str = "updater/config/sources.yaml") -> Dict:
    """Dosyaları doğrula ve rapor döndür"""
    import yaml

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    validator = TaxSchemaValidator(config)

    results = {}

    # taxes.json
    if Path(taxes_path).exists():
        with open(taxes_path, "r", encoding="utf-8") as f:
            taxes_raw = json.load(f)
        taxes_data = _normalize_taxes_data(taxes_raw)
        results["taxes"] = validator.validate_taxes(taxes_data)
    else:
        results["taxes"] = {"valid": False, "errors": ["File not found"], "warnings": [], "record_count": 0}

    # rates.json
    if Path(rates_path).exists():
        with open(rates_path, "r", encoding="utf-8") as f:
            rates_data = json.load(f)
        results["rates"] = validator.validate_rates(rates_data)
    else:
        results["rates"] = {"valid": False, "errors": ["File not found"], "warnings": [], "record_count": 0}

    return results


if __name__ == "__main__":
    import sys
    import logging
    logging.basicConfig(level=logging.INFO)

    result = validate_files()
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # Exit code
    if not result["taxes"]["valid"] or not result["rates"]["valid"]:
        sys.exit(1)