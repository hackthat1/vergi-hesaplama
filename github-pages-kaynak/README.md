# İthalat Vergi Hesaplama

Locum Excelini tarayıcıda okuyarak 2026_Vergi_Hesaplama_V10.xlsm dosyasındaki hesapları uygular. Sunucuya dosya göndermez, makro çalıştırmaz.

## Kullanım

1. Locum dosyasını yükleyin; sayfa, başlık satırı ve alan eşleştirmelerini kontrol edin.
2. USD/TL, EUR/TL, para birimi, ödeme şekli ve AT/DI seçimini girin.
3. Eksik menşe ve miktar bilgilerini Girdileri düzenle görünümünde tamamlayın.
4. Özet tabloyu inceleyin. Excel çıktısı indir düğmesi ÖzetTablo, Girdiler ve Hesap Bilgileri sayfalarını oluşturur.

## GitHub Pages

Derleme gerekmez. Bu ZIP dosyasının içeriğini bir GitHub deposunun kök dizinine koyun. Settings > Pages > Deploy from a branch > main / root seçin. Aynı içerik `/docs` klasöründen de yayınlanabilir. `.openai/hosting.json` Sites ortamına aittir; GitHub Pages için gerekli değildir.

## Yerel çalıştırma

`python -m http.server 8080` ardından http://localhost:8080 adresini açın. JSON tabloları fetch ile okunduğu için dosyayı çift tıklayarak açmak yerine HTTP sunucusu kullanın.

## Doğrulama

`node tests/calculation.cjs`

## Kaynak ve sınırlar

Oranlar yalnız kullanıcının sağladığı Excelden alınmıştır; mevzuat güncelliği bağımsız doğrulanmamıştır. Hesaplanan vergiler kaynak formüllerdeki GV, İGV, GTS-EMY, bandrol, ÖTV, KKDF, damping ve KDV'dir. Kaynak formüllerde bulunmayan yükümlülükler eklenmez.

Gözetim eşiğinde fatura ve yan masraf dikkate alınır; navlun kaynak N formülünde olduğu gibi hariçtir. CIF hesabına navlun dahildir. M2/M3, Exceldeki brüt kg kullanımından farklı olarak ayrı ölçü alanıyla hesaplanır. Damping, kaynak U formülünü aynen izler: CIF yüzdesi veya pozitif (birim tutarı × miktar − CIF); kaynak formül döviz dönüşümü yapmaz. Damping satırları kontrol için işaretlenir.

ÖzetTablo: CIF EUR; gözetim ve vergiler TL. Toplam, kaynak W sütunu gibi gözetim farkını da içerir. Ekrandaki toplam vergi, gözetim farkını içermez. Eksik satırlar sonuç üretemez; çıktı kontrol sütununda açıklanır ve toplam yalnız hesaplanabilen satırları kapsar.

Ürün kapsamı ve muafiyetler kullanıcı tarafından açıklamalar üzerinden kontrol edilir. Para birimi tüm satırlar için aynıdır; farklı para birimli dosyaları ayrı çalıştırın. Navlun da seçili para biriminde olmalıdır. Satırdaki ödeme ve antlaşma bilgileri genel seçimlerin önüne geçer.

## Dosyalar

- `index.html`, `style.css`, `app.js`: kullanıcı arayüzü, aktarım, özet ve Excel çıktısı.
- `core.js`, `tax-core.js`: hesap motoru.
- `rates.json`, `taxes.json`: Excelden çıkarılan oran ve ülke tabloları.
- `vendor/xlsx.full.min.js`: SheetJS CE 0.20.3, Apache-2.0.

Kaynak orijinal xlsm ve gerçek fatura verileri depoya dahil edilmemiştir.
