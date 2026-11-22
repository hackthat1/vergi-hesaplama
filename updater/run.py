#!/usr/bin/env python3
"""
Ana Orchestrasyon Script'i - Vergi Oranları Güncelleme Pipeline'ı

Kullanım:
    python updater/run.py                    # Tüm pipeline'ı çalıştır
    python updater/run.py --fetch-only       # Sadece veri çek
    python updater/run.py --transform-only   # Sadece dönüştür (cache'den)
    python updater/run.py --validate-only    # Sadece doğrula
    python updater/run.py --diff             # Diff raporu oluştur
"""

import argparse
import json
import logging
import sys
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

import yaml

# Updater modüllerini import et
sys.path.insert(0, str(Path(__file__).parent))

from fetchers import (
    ResmiGazeteFetcher,
    GIBFetcher,
    TUIKFetcher,
    CumhurbaskaniFetcher,
)
from transformers.merge import DataMerger
from validators.schema import validate_files
from validators.diff import DiffReporter, load_json_safe

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class PipelineRunner:
    """Pipeline'ı koordine eden ana sınıf"""

    def __init__(self, config_path: str = "updater/config/sources.yaml"):
        self.config_path = Path(config_path)
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.sources = self.config.get("sources", {})
        self.cache_dir = Path("updater/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Fetcher'ları başlat
        self.fetchers = {
            "resmigazete": ResmiGazeteFetcher(self.sources.get("gv_resmigazete", {}), self.cache_dir),
            "gib_kdv": GIBFetcher(self.sources.get("kdv_gib", {}), self.cache_dir),
            "gib_otv": GIBFetcher(self.sources.get("otv_gib", {}), self.cache_dir),
            "tuik": TUIKFetcher(self.sources.get("gtip_tuik", {}), self.cache_dir),
            "cumhurbaskani": CumhurbaskaniFetcher(self.sources.get("cumhurbaskani_kararlari", {}), self.cache_dir),
            "emy": ResmiGazeteFetcher(self.sources.get("emy_others", {}), self.cache_dir),
        }

    def run_fetch(self) -> Dict[str, Any]:
        """Tüm kaynaklardan veri çek"""
        logger.info("=" * 60)
        logger.info("VERİ ÇEKME AŞAMASI BAŞLIYOR")
        logger.info("=" * 60)

        raw_data = {}

        for name, fetcher in self.fetchers.items():
            if not self.sources.get(f"{name}_enabled", True):
                logger.info(f"  ⏭ {name} devre dışı, atlanıyor")
                continue

            logger.info(f"  📥 {name} çekiliyor...")
            try:
                result = fetcher.fetch()
                raw_data[name] = result.data if result.success else {}
                if result.success:
                    logger.info(f"  ✓ {name}: {result.metadata.get('documents_count', 0)} belge")
                else:
                    logger.warning(f"  ✗ {name}: {result.error}")
            except Exception as e:
                logger.error(f"  ✗ {name}: Hata - {e}")
                raw_data[name] = {}

        # Cache'e kaydet
        cache_file = self.cache_dir / f"raw_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            # FetchResult objelerini serialize edilebilir hale getir
            serializable = {}
            for k, v in raw_data.items():
                serializable[k] = v
            json.dump(serializable, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"  💾 Ham veri cache'e kaydedildi: {cache_file}")
        return raw_data

    def run_transform(self, raw_data: Dict = None) -> Dict[str, Any]:
        """Veriyi dönüştür ve kaydet"""
        logger.info("=" * 60)
        logger.info("VERİ DÖNÜŞTÜRME AŞAMASI BAŞLIYOR")
        logger.info("=" * 60)

        if raw_data is None:
            # Cache'den en son veriyi yükle
            cache_files = sorted(self.cache_dir.glob("raw_data_*.json"))
            if not cache_files:
                logger.error("Cache'de veri yok! Önce --fetch-only çalıştırın.")
                return {}

            with open(cache_files[-1], "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            logger.info(f"  📂 Cache'den yüklendi: {cache_files[-1].name}")

        # Merger ile dönüştür
        merger = DataMerger(str(self.config_path))
        result = merger.run(raw_data)

        return result

    def run_validate(self) -> Dict[str, Any]:
        """Mevcut dosyaları doğrula"""
        logger.info("=" * 60)
        logger.info("DOĞRULAMA AŞAMASI BAŞLIYOR")
        logger.info("=" * 60)

        result = validate_files(
            taxes_path="taxes.json",
            rates_path="rates.json",
            config_path=str(self.config_path),
        )

        for key, res in result.items():
            status = "✓ GEÇERLİ" if res["valid"] else "✗ HATALI"
            logger.info(f"  {key}: {status} ({res['record_count']} kayıt)")
            for err in res["errors"]:
                logger.error(f"    HATA: {err}")
            for warn in res["warnings"][:5]:  # İlk 5 uyarı
                logger.warning(f"    UYARI: {warn}")
            if len(res["warnings"]) > 5:
                logger.warning(f"    ... ve {len(res['warnings']) - 5} uyarı daha")

        return result

    def run_diff(self) -> Dict[str, Any]:
        """Diff raporu oluştur"""
        logger.info("=" * 60)
        logger.info("DIFF RAPORU OLUŞTURULUYOR")
        logger.info("=" * 60)

        # Backup dosyalarını kontrol et
        old_taxes = load_json_safe("taxes.json.backup") if Path("taxes.json.backup").exists() else load_json_safe("taxes.json")
        new_taxes = load_json_safe("taxes.json")
        old_rates = load_json_safe("rates.json.backup") if Path("rates.json.backup").exists() else load_json_safe("rates.json")
        new_rates = load_json_safe("rates.json")

        reporter = DiffReporter(self.config)
        taxes_diff = reporter.compare_taxes(old_taxes, new_taxes)
        rates_diff = reporter.compare_rates(old_rates, new_rates)

        report_path = reporter.save_report(taxes_diff, rates_diff)

        logger.info(f"  📊 Diff raporu: {report_path}")
        logger.info(f"  Taxes: +{taxes_diff['summary']['added']} -{taxes_diff['summary']['removed']} ~{taxes_diff['summary']['changed']}")
        logger.info(f"  Rates: +{rates_diff['summary']['added']} -{rates_diff['summary']['removed']} ~{rates_diff['summary']['changed']}")

        if taxes_diff["suspicious"]:
            logger.warning(f"  ⚠️ {len(taxes_diff['suspicious'])} şüpheli büyük değişiklik tespit edildi!")

        return {"taxes": taxes_diff, "rates": rates_diff}

    def run_full(self) -> Dict[str, Any]:
        """Tam pipeline: fetch -> transform -> validate -> diff"""
        logger.info("🚀 TAM PIPELINE BAŞLIYOR")

        # 1. Fetch
        raw_data = self.run_fetch()

        # 2. Transform
        transform_result = self.run_transform(raw_data)

        # 3. Validate
        validate_result = self.run_validate()

        # 4. Diff (eğer backup varsa)
        if Path("taxes.json.backup").exists() or Path("rates.json.backup").exists():
            diff_result = self.run_diff()
        else:
            logger.info("  ℹ️ Backup dosyası yok, diff atlanıyor")
            diff_result = None

        # Backup oluştur (sonraki çalışma için)
        self._create_backups()

        return {
            "fetch": {"sources_count": len(raw_data)},
            "transform": transform_result,
            "validate": validate_result,
            "diff": diff_result,
        }

    def _create_backups(self):
        """Mevcut dosyaların backup'ını al"""
        for fname in ["taxes.json", "rates.json"]:
            src = Path(fname)
            if src.exists():
                backup = Path(f"{fname}.backup")
                shutil.copy2(src, backup)
                logger.debug(f"  💾 Backup: {backup}")


def main():
    parser = argparse.ArgumentParser(description="Vergi Oranları Güncelleme Pipeline'ı")
    parser.add_argument("--fetch-only", action="store_true", help="Sadece veri çek")
    parser.add_argument("--transform-only", action="store_true", help="Sadece dönüştür (cache'den)")
    parser.add_argument("--validate-only", action="store_true", help="Sadece doğrula")
    parser.add_argument("--diff", action="store_true", help="Diff raporu oluştur")
    parser.add_argument("--config", default="updater/config/sources.yaml", help="Config dosyası")
    parser.add_argument("--verbose", "-v", action="store_true", help="Detaylı log")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    runner = PipelineRunner(args.config)

    try:
        if args.fetch_only:
            runner.run_fetch()
        elif args.transform_only:
            runner.run_transform()
        elif args.validate_only:
            runner.run_validate()
        elif args.diff:
            runner.run_diff()
        else:
            runner.run_full()

        logger.info("✅ Pipeline başarıyla tamamlandı!")
        return 0

    except Exception as e:
        logger.exception(f"❌ Pipeline hatası: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())