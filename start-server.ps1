<#
Vergi Hesaplama - Yerel HTTP Sunucusu
Bu script projeyi yerel bir HTTP sunucusunda çalıştırır.
JSON dosyalarının yüklenmesi için HTTP protokolü gereklidir (file:// çalışmaz).
#>

Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "  İTHALAT VERGİ HESAPLAMA - Yerel Sunucu" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""

$projectPath = "C:\Users\ademc\ofis\vergi-hesaplama-fixed"
Set-Location $projectPath

Write-Host "Proje dizini: $projectPath" -ForegroundColor Gray
Write-Host "Sunucu başlatılıyor: http://localhost:8080" -ForegroundColor Green
Write-Host ""
Write-Host "Tarayıcıda aç: http://localhost:8080" -ForegroundColor Yellow
Write-Host "Durdurmak için: Ctrl+C" -ForegroundColor Gray
Write-Host ""

# Python 3 kontrolü
if (Get-Command python -ErrorAction SilentlyContinue) {
    Write-Host "Python 3 bulundu, http.server başlatılıyor..." -ForegroundColor Green
    python -m http.server 8080
}
elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    Write-Host "Python 3 (python3) bulundu, http.server başlatılıyor..." -ForegroundColor Green
    python3 -m http.server 8080
}
elseif (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Host "Node.js bulundu, http-server başlatılıyor..." -ForegroundColor Green
    # npx http-server kullan
    npx http-server -p 8080 -c-1
}
else {
    Write-Host "HATA: Python 3 veya Node.js bulunamadı!" -ForegroundColor Red
    Write-Host "Lütfen Python 3 (python.org) veya Node.js (nodejs.org) kurun." -ForegroundColor Red
    Read-Host "Çıkmak için Enter'a basın"
}