# Vergi Oranları Otomatik Güncelleme Pipeline'ı

Bu modül, Türkiye resmi kaynaklarından (Resmi Gazete, GİB, TÜİK, Cumhurbaşkanı Kararları) gümrük vergisi, KDV, ÖTV ve ek mali yükümlülük oranlarını otomatik çeker, `taxes.json` ve `rates.json` dosyalarını günceller.

## Özellikler

- 📥 **Resmi kaynaklardan veri çekme**: Resmi Gazete, GİB, TÜİK, T.C. Cumhurbaşkanlığı
- 🔄 **PDF tablo çıkarma**: pdfplumber ile tabloları parse etme
- 🔀 **Akıllı birleştirme**: Çoklu kaynaklardan veri birleştirme, öncelik sıralaması
- ✅ **Şema doğrulama**: JSON Schema ile veri kalitesi kontrolü
- 📊 **Diff raporlama**: Değişiklikleri görselleştirme, şüpheli değişiklikleri işaretleme
- 🤖 **GitHub Actions entegrasyonu**: Haftalık otomatik çalışma
- 📝 **Changelog**: Otomatik değişiklik kaydı

## Kurulum

```bash
# Bağımlılıkları yükle
pip install -r updater/requirements.txt

# Sistem bağımlılıkları (Ubuntu/Debian)
sudo apt-get install poppler-utils tesseract-ocr tesseract-ocr-tur
```

## Kullanım

### Tam Pipeline (Fetch → Transform → Validate → Diff)

```bash
python updater/run.py
```

### Sadece Veri Çek (Cache'e kaydeder)

```bash
python updater/run.py --fetch-only
```

### Cache'den Dönüştür

```bash
python updater/run.py --transform-only
```

### Sadece Doğrula

```bash
python updater/run.py --validate-only
```

### Diff Raporu Oluştur

```bash
python updater/run.py --diff
```

## Yapılandırma

### `updater/config/sources.yaml`
Veri kaynakları, URL'ler, arama terimleri, zamanlayıcı ayarları.

### `updater/config/mapping.yaml`
- GTIP normalize kuralları
- Vergi türü kodları
- Birim eşleştirme
- Manual override'lar (özel GTIP kuralları)
- Default değerler

## Çıktı Dosyaları

| Dosya | Açıklama |
|-------|----------|
| `taxes.json` | GTIP başına GV, KDV, ÖTV, EMY, Bandrol, KKDF, Damping oranları |
| `rates.json` | GTIP listesi + gözetim oranları (orijinal format) |
| `CHANGELOG_RATES.md` | Otomatik değişiklik kaydı |
| `updater/output/diff_report.md` | Detaylı diff raporu |

## Veri Kaynakları ve Öncelik

1. **Cumhurbaşkanı Kararları** (tccb.gov.tr) - En yüksek öncelik
2. **Resmi Gazete** (resmigazete.gov.tr) - Yüksek öncelik
3. **GİB** (gib.gov.tr) - KDV/ÖTV için
4. **TÜİK** (data.tuik.gov.tr) - GTIP kod listesi için

## Manual Override

`mapping.yaml` dosyasındaki `manual_overrides` bölümünde özel GTIP kuralları tanımlanabilir:

```yaml
manual_overrides:
  "8703":  # Otomotiv
    gv: 10
    kdv: 18
    otv: 45
    otv_type: "ORANALI"
  "2208":  # Alkol
    otv: 150
    otv_type: "MUKTESEP"
```

## GitHub Actions

Workflow `.github/workflows/update-rates.yml` her Pazartesi 06:00 UTC'de çalışır.

Manuel tetikleme için: GitHub → Actions → Update Tax Rates → Run workflow

## Yerel Test

```bash
# 1. Veri çek
python updater/run.py --fetch-only

# 2. Dönüştür
python updater/run.py --transform-only

# 3. Doğrula
python updater/run.py --validate-only

# 4. Diff gör
python updater/run.py --diff
```

## Sorun Giderme

### PDF parse etmiyor
- `poppler-utils` kurulu mu? (`pdftotext --version` ile test)
- PDF şifreli mi? `pdf_password` config'e eklenmeli

### GTIP bulunamıyor
- TÜİK sayfa yapısı değişmiş olabilir, `tuik.py`'deki parser güncellenmeli
- Alternatif: TÜİK'ten manuel CSV indirip `updater/cache/` altına koyun

### Rate 0 geliyor
- Kaynak tabloda oran sütunu farklı isimde olabilir
- `mapping.yaml`'daki `rate_ranges` ve column detection ayarları kontrol edilmeli

## Güvenlik

- Sadece resmi सरकारي (gov.tr) domainlerinden veri çekilir
- `User-Agent` header'ı bot olduğunu belirtir
- Rate limiting: kaynak sunucuları yormamak için request arası gecikme

## Lisans

Bu pipeline MIT lisansı altındadır. Veri kaynakları ilgili kurumların telif haklarına tabidir.