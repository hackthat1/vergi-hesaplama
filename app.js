'use strict';

const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>]/g, c => ({ '&': '&', '<': '<', '>': '>' })[c]).replace(/"/g, '"');
const fmt = v => Number(v).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// State
let refs = [], lookup = new Map(), db = null;
let rows = [], results = [], workbook = null, headers = [], grid = [], fileName = '';
let viewMode = 'summary';
let rateLimit = 100;

// Backup system for error recovery
let stateHistory = [];
const MAX_HISTORY = 3;

const specs = [
    ['gtip', 'GTİP / Tarife', ['tarife', 'gtip']],
    ['model', 'Model / Malzeme kodu', ['malzeme kodu', 'model']],
    ['invoice', 'Fatura numarası', ['fatura no', 'fatura numarası']],
    ['feature', 'Özellik kodları', ['özellik kodları']],
    ['amount', 'Tutar', ['tutar', 'fatura tutarı']],
    ['expense', 'Tedarik dışı yan masraf', ['tedarik dışı yan masraf', 'yan masraf']],
    ['freight', 'Navlun (seçilen para birimi)', ['navlun euro', 'navlun']],
    ['kg', 'Brüt ağırlık', ['brüt ağırlık', 'brüt kg']],
    ['qty', 'Miktar / Adet', ['miktar', 'adet']],
    ['measure', 'M² / M³ miktarı', ['ölçü miktarı', 'm2', 'm3']],
    ['country', 'Menşe ülkesi', ['menşe ülkesi', 'menşei', 'menşe', 'mense ulkesi', 'mense ulke', 'mense', 'country', 'origin', 'country of origin', 'menşe ülke', 'menşe ülke adi', 'menşe ülke adı']],
    ['payment', 'Ödeme şekli', ['ödeme şekli']],
    ['agreement', 'Uluslararası antlaşma', ['uluslararası ant', 'uluslararası antlaşma']]
];

const lower = v => String(v ?? '').normalize('NFC').toLocaleLowerCase('tr-TR').replace(/[İı]/g, 'i').replace(/[^a-z0-9çöşğü]/g, '');

function rule(row) { return lookup.get(Gozetim.norm(row.gtip)); }

function params() {
    return {
        usd: $('usd').value,
        eur: $('eur').value,
        currency: $('currency').value,
        payment: $('payment').value,
        agreement: $('agreement').value
    };
}

function notify(s, type = 'info') {
    const el = $('notice');
    el.textContent = s;
    el.className = 'notice ' + type;
}

// Backup current state
function saveState() {
    // Serialize rows safely
    const safeRows = rows.map(r => ({ ...r }));

    // Serialize results safely - exclude non-serializable properties
    const safeResults = results.map(r => {
        const { dampingRule, ...rest } = r;
        return rest;
    });

    const state = {
        rows: safeRows,
        results: safeResults,
        fileName,
        workbook: workbook ? true : false,
        viewMode,
        params: params()
    };
    stateHistory.push(state);
    if (stateHistory.length > MAX_HISTORY) stateHistory.shift();
}

// Restore previous state
function restoreState() {
    if (stateHistory.length === 0) {
        notify('Geri dönülecek önceki durum yok.', 'warning');
        return false;
    }
    const state = stateHistory.pop();
    rows = state.rows;
    results = state.results;
    fileName = state.fileName;
    viewMode = state.viewMode;

    // Restore form values
    $('usd').value = state.params.usd;
    $('eur').value = state.params.eur;
    $('currency').value = state.params.currency;
    $('payment').value = state.params.payment;
    $('agreement').value = state.params.agreement;

    // Update UI
    $('mapping').hidden = true;
    $('fileinfo').textContent = fileName ? fileName : 'Henüz dosya yüklenmedi.';

    // Recalculate to regenerate dampingRule and other computed fields
    recalc();
    notify('Önceki duruma dönüldü.', 'success');
    return true;
}

// Clear all data and reset to initial state
function resetAll() {
    // Save current state before reset (for undo)
    saveState();

    rows = [];
    results = [];
    workbook = null;
    headers = [];
    grid = [];
    fileName = '';
    viewMode = 'summary';

    // Reset form
    $('usd').value = '';
    $('eur').value = '';
    $('currency').value = 'EUR';
    $('payment').value = '';
    $('agreement').value = '';
    $('country').value = '';
    $('search').value = '';
    $('filter').value = 'all';
    $('mode').value = 'summary';
    $('file').value = '';
    $('fileinfo').textContent = 'Henüz dosya yüklenmedi.';
    $('mapping').hidden = true;
    $('parity').textContent = '—';
    $('export').disabled = true;

    renderRows();
    updateMetrics();
    notify('Tüm veriler sıfırlandı. Yeni dosya yükleyebilirsiniz.', 'success');
}

async function init() {
    try {
        [refs, db] = await Promise.all([
            fetch('rates.json').then(r => { if (!r.ok) throw Error(); return r.json(); }),
            fetch('taxes.json').then(r => { if (!r.ok) throw Error(); return r.json(); })
        ]);
        refs.forEach(r => { const k = Gozetim.norm(r.gtip); if (!lookup.has(k)) lookup.set(k, r); });
        $('country').innerHTML += [...new Set([...db.countries, ...Object.values(db.aliases)])].sort().map(c => `<option>${esc(c)}</option>`).join('');
        renderRates();
        renderRows();
        updateMetrics();
    } catch (e) {
        notify('Referans tablolar yüklenemedi. Sayfayı yenileyip tekrar dene.', 'error');
    }
}

function recalc() {
    if (!db) return;

    // Save state before calculation
    saveState();

    try {
        const p = params();
        results = rows.map(r => TaxEngine.calculateTax({ ...r, country: r.country || $('country').value }, rule(r), p, db));

        $('parity').textContent = Gozetim.num(p.usd) > 0 && Gozetim.num(p.eur) > 0 ? fmt(Gozetim.num(p.usd) / Gozetim.num(p.eur)) : '—';
        updateMetrics();
        renderRows();
    } catch (e) {
        console.error('Calculation error:', e);
        notify('Hesaplama hatası: ' + e.message, 'error');
        // Offer restore
        if (confirm('Hesaplama sırasında hata oluştu. Önceki duruma dönmek ister misiniz?')) {
            restoreState();
        }
    }
}

function updateMetrics() {
    const valid = results.filter(r => !r.errors.length);
    $('count').textContent = rows.length;
    $('affected').textContent = valid.length;
    const total = valid.reduce((a, r) => a + r.taxTotal, 0);
    const eur = Gozetim.num($('eur').value);
    $('total').textContent = valid.length ? fmt(total) : '—';
    $('totaltry').textContent = valid.length && eur ? fmt(total * eur) : '—';
    $('export').disabled = !rows.length;
    $('rowbadge').textContent = rows.length;
    $('source').textContent = rows.length ? `${fileName || 'Manuel çalışma'} · ${valid.length} hesaplandı · ${rows.length - valid.length} hatalı` : 'Sonuçlar dosya aktardığında burada görünecek.';
}

function renderRows() {
    const q = lower($('search').value);
    const filter = $('filter').value;
    const summary = viewMode === 'summary';

    const visible = rows.map((r, i) => ({ r, i, x: results[i] })).filter(({ r, x }) =>
        (!q || lower([r.gtip, r.model, r.invoice].join(' ')).includes(q)) &&
        (filter === 'all' || filter === 'error' && x.errors.length || filter === 'positive' && !x.errors.length && x.difference > 0)
    );

    // Table headers - SIMPLIFIED: Only Invoice + Tax breakdown
    if (summary) {
        $('tableHead').innerHTML = '<tr>' + [
            'Fatura Numarası',
            'GTİP',
            'Model',
            'GV (TL)',
            'İGV (TL)',
            'EMY (TL)',
            'Bandrol (TL)',
            'ÖTV (TL)',
            'KKDF (TL)',
            'Damping (TL)',
            'KDV (TL)',
            'Toplam Vergi (TL)',
            'Durum'
        ].map(t => `<th>${t}</th>`).join('') + '</tr>';
    } else {
        $('tableHead').innerHTML = '<tr>' + [
            'Kalem / Malzeme',
            'GTİP',
            'Tutar',
            'Yan masraf',
            'Navlun',
            'Brüt kg',
            'Adet',
            'M² / M³',
            'Menşe / Ödeme / Antlaşma',
            'Gözetim · EUR',
            'GV',
            'İGV',
            'EMY',
            'Bandrol',
            'ÖTV',
            'KKDF',
            'Damping',
            'KDV',
            'Toplam vergi · EUR',
            'İnceleme'
        ].map(t => `<th>${t}</th>`).join('') + '</tr>';
    }

    if (!rows.length) {
        $('rows').innerHTML = '<tr><td colspan="13" class="empty"><div>▤</div><strong>Hesaplamaya hazır</strong><p>Bir dosya yükle veya örnek verilerle çalışma alanını keşfet.</p></tr>';
        return;
    }

    const eur = Gozetim.num($('eur').value);
    const money = k => x.errors.length ? '—' : fmt(x[k]);
    const tl = k => x.errors.length ? '—' : fmt(x[k] * eur);

    $('rows').innerHTML = visible.slice(0, 500).map(({ r, i, x }) => {
        const ru = rule(r);
        const statusHtml = x.errors.length
            ? `<span class="error">${esc(x.errors.join(' · '))}</span>`
            : x.dampingRule
                ? `<span class="warning">Damping kontrolü gerekli</span>`
                : `<span class="status">Tamam</span>`;

        const details = `<details><summary>Detay</summary><div class="rowdetail">
            ${esc(ru?.note || 'Gözetim kaydı bulunamadı')}
            ${x.dampingRule ? '<p>Damping: ' + esc(x.dampingRule.note) + '; kaynak Excel formülü uygulandı.</p>' : ''}
            <label><input type="checkbox" data-i="${i}" data-key="exempt" ${r.exempt ? 'checked' : ''}> Gözetim kapsam dışı / muaf</label>
        </div></details>`;

        if (summary) {
            return `<tr>
                <td>${esc(r.invoice || '—')}</td>
                <td>${esc(r.gtip)}</td>
                <td>${esc(r.model || '—')}</td>
                <td>${tl('gv')}</td>
                <td>${tl('igv')}</td>
                <td>${tl('emy')}</td>
                <td>${tl('bandrol')}</td>
                <td>${tl('otv')}</td>
                <td>${tl('kkdf')}</td>
                <td>${tl('damping')}</td>
                <td>${tl('kdv')}</td>
                <td><strong>${tl('taxTotal')}</strong></td>
                <td>${statusHtml} ${details}</td>
            </tr>`;
        } else {
            return `<tr>
                <td><input aria-label="Malzeme kodu" data-i="${i}" data-key="model" value="${esc(r.model)}"><small>${esc(r.invoice || 'Fatura belirtilmedi')}</small></td>
                <td>${input(r, i, 'gtip', 'GTİP')}</td>
                ${['amount', 'expense', 'freight', 'kg', 'qty', 'measure'].map(k => `<td>${input(r, i, k, k)}</td>`).join('')}
                <td>
                    <input aria-label="Menşe" data-i="${i}" data-key="country" value="${esc(r.country)}" placeholder="${esc($('country').value || 'Menşe giriniz')}">
                    <select aria-label="Ödeme şekli" data-i="${i}" data-key="payment"><option value="">Genel ayar</option>${['PEŞİN', 'MAL MUKABİLİ'].map(v => `<option ${r.payment === v ? 'selected' : ''}>${v}</option>`).join('')}</select>
                    <select aria-label="Antlaşma" data-i="${i}" data-key="agreement"><option value="">Genel ayar</option>${['AT', 'DI'].map(v => `<option ${r.agreement === v ? 'selected' : ''}>${v}</option>`).join('')}</select>
                </td>
                <td>${money('difference')}</td>
                ${['gv', 'igv', 'emy', 'bandrol', 'otv', 'kkdf', 'damping', 'kdv', 'taxTotal'].map(k => `<td>${money(k)}</td>`).join('')}
                <td>${statusHtml} ${details}</td>
            </tr>`;
        }
    }).join('') || '<tr><td colspan="13" class="empty">Bu filtreye uygun satır yok.</td></tr>';

    $('footer').textContent = `${visible.length} satır${visible.length > 500 ? ' · İlk 500 gösteriliyor; Excel çıktısı tümünü içerir.' : ''} · ${summary ? 'Sadece fatura bazlı vergi özeti.' : 'Vergi tutarları EUR. Değişiklikler otomatik hesaplanır.'}`;
}

function input(r, i, key, label) {
    return `<input aria-label="${esc(label)} ${i+1}" data-i="${i}" data-key="${key}" value="${esc(r[key])}" inputmode="decimal">`;
}

async function readFile(file) {
    if (!db) { notify('Referanslar henüz hazır değil.', 'error'); return; }
    try {
        notify('');
        const data = await file.arrayBuffer();
        workbook = XLSX.read(data, { type: 'array', cellFormula: false, codepage: 1254 });
        fileName = file.name;
        $('fileinfo').textContent = fileName;
        $('mapping').hidden = false;
        $('sheet').innerHTML = workbook.SheetNames.map(n => `<option>${esc(n)}</option>`).join('');
        if (workbook.SheetNames.includes('Fatura Bilgileri')) $('sheet').value = 'Fatura Bilgileri';
        $('headerrow').value = 1;
        loadSheet();
    } catch (e) {
        notify('Dosya okunamadı. Geçerli ve şifresiz bir Excel veya CSV dosyası seç.', 'error');
    }
}

function loadSheet() {
    grid = XLSX.utils.sheet_to_json(workbook.Sheets[$('sheet').value], { header: 1, defval: '', raw: true });
    const h = Math.max(1, Number($('headerrow').value) || 1);
    headers = grid[h - 1] || [];
    $('maps').innerHTML = specs.map(([key, label, aliases]) => {
        let ix = headers.findIndex(h => aliases.some(a => lower(h) === lower(a)));
        return `<label>${label}<select id="map-${key}"><option value="">Eşleşme yok</option>${headers.map((h, j) => `<option value="${j}" ${j === ix ? 'selected' : ''}>${esc(h || 'Sütun ' + (j + 1))}</option>`).join('')}</select></label>`;
    }).join('');
}

function importRows() {
    const mapping = Object.fromEntries(specs.map(([k]) => [k, $('map-' + k).value]));
    if (mapping.gtip === '' || mapping.amount === '') { notify('GTİP / Tarife ve Tutar sütunlarını eşleştir.', 'error'); return; }
    const raw = grid.slice(Number($('headerrow').value) || 1);
    rows = raw.filter(a => String(a[Number(mapping.gtip)] ?? '').trim() !== '').map(a => Object.fromEntries(specs.map(([k]) => [k, mapping[k] === '' ? '' : a[Number(mapping.k)] ?? ''])));
    $('mapping').hidden = true;
    notify(rows.length ? 'Veriler aktarıldı. Eksik bilgileri "Girdileri düzenle" görünümünde tamamla; kur ve genel seçimleri kontrol et.' : 'GTİP içeren veri satırı bulunamadı.', rows.length ? 'success' : 'error');
    recalc();
}

function exportExcel() {
    recalc();
    const p = params(), eur = Gozetim.num(p.eur);
    const summary = [['Fatura Numarası', 'GTİP', 'Model', 'GV (TL)', 'İGV (TL)', 'EMY (TL)', 'Bandrol (TL)', 'ÖTV (TL)', 'KKDF (TL)', 'Damping (TL)', 'KDV (TL)', 'Toplam Vergi (TL)', 'Durum']];
    const taxKeys = ['gv', 'igv', 'emy', 'bandrol', 'otv', 'kkdf', 'damping', 'kdv', 'taxTotal'];

    rows.forEach((r, i) => {
        const x = results[i];
        summary.push([
            r.invoice,
            r.gtip,
            r.model,
            ...taxKeys.map(k => x.errors.length ? null : fmt(x[k] * eur)),
            x.errors.length ? x.errors.join('; ') : x.dampingRule ? 'Damping kontrolü' : 'Tamam'
        ]);
    });

    const ok = results.filter(x => !x.errors.length);
    const sum = k => ok.reduce((a, x) => a + x[k], 0);
    summary.push(['TOPLAM', '', '', ...taxKeys.map(k => fmt(sum(k) * eur)), `${ok.length}/${rows.length} satır hesaplandı`]);

    const wb = XLSX.utils.book_new();
    const ws = XLSX.utils.aoa_to_sheet(summary);
    ws['!cols'] = summary[0].map((_, i) => ({ wch: i < 3 ? 22 : i === 12 ? 40 : 18 }));
    for (let i = 1; i < summary.length; i++) for (let c = 3; c < 12; c++) {
        const cell = ws[XLSX.utils.encode_cell({ r: i, c })];
        if (cell && cell.t === 'n') cell.z = '#,##0.00';
    }
    XLSX.utils.book_append_sheet(wb, ws, 'Fatura_Vergi_Ozeti');

    // Inputs sheet
    const inp = [['Fatura', 'GTİP', 'Model', 'Tutar', 'Yan Masraf', 'Navlun', 'Brüt Kg', 'Adet', 'M2/M3', 'Menşe', 'Ödeme Şekli', 'Antlaşma', 'Gözetim Muaf'],
        ...rows.map((r, i) => [r.invoice, r.gtip, r.model, r.amount, r.expense, r.freight, r.kg, r.qty, r.measure, results[i].country || r.country || $('country').value, results[i].pay || r.payment || p.payment, results[i].agreement || r.agreement || p.agreement, r.exempt ? 'Evet' : 'Hayır'])];
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(inp), 'Girdiler');

    // Settings sheet
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
        ['AYAR', 'DEĞER'],
        ['USD/TL', Gozetim.num(p.usd)],
        ['EUR/TL', eur],
        ['Tutar para birimi', p.currency],
        ['Ödeme şekli', p.payment],
        ['Antlaşma', p.agreement],
        ['Kaynak dosya', fileName],
        ['Oran kaynağı', '2026_Vergi_Hesaplama_V10.xlsm'],
        ['Sadece vergi toplamı (TL)', fmt(sum('taxTotal') * eur)],
        ['Hesaplanamayan satır', rows.length - ok.length]
    ]), 'Ayarlar');

    XLSX.writeFile(wb, 'Fatura_Vergi_Ozeti.xlsx');
}

function renderRates() {
    if (!refs.length) return;
    const q = lower($('rateSearch').value);
    const rs = refs.filter(r => r.rate > 0 && (!q || lower(r.gtip + ' ' + r.note).includes(q)));
    $('rateCount').textContent = `${rs.length} pozitif oran kaydı · Kaynak Excel tablosu`;
    $('rateRows').innerHTML = rs.slice(0, rateLimit).map(r => `<tr><td>${esc(r.gtip)}</td><td>${fmt(r.rate)}</td><td>${esc(r.unit)}</td><td style="min-width:350px">${esc(r.note)}</td></tr>`).join('');
    $('moreRates').hidden = rs.length <= rateLimit;
}

// Event bindings
document.querySelectorAll('[data-view]').forEach(b => b.onclick = () => {
    document.querySelectorAll('.view').forEach(v => v.hidden = v.id !== b.dataset.view);
    document.querySelectorAll('.nav').forEach(n => n.classList.toggle('active', n === b));
});

$('file').onchange = e => e.target.files[0] && readFile(e.target.files[0]);
$('drop').ondragover = e => { e.preventDefault(); };
$('drop').ondrop = e => { e.preventDefault(); if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]); };
$('sheet').onchange = loadSheet;
$('headerrow').onchange = loadSheet;
$('import').onclick = importRows;
['usd', 'eur', 'currency', 'payment', 'agreement', 'country'].forEach(id => $(id).onchange = recalc);
$('search').oninput = renderRows;
$('filter').onchange = renderRows;
$('rows').onchange = e => { const t = e.target; if (t.dataset.i !== undefined) { rows[Number(t.dataset.i)][t.dataset.key] = t.type === 'checkbox' ? t.checked : t.value; recalc(); } };
$('export').onclick = exportExcel;
$('mode').onchange = () => { viewMode = $('mode').value; renderRows(); };

// New: Reset button
$('reset').onclick = () => {
    if (rows.length === 0) { notify('Zaten boş.', 'info'); return; }
    if (confirm('Tüm veriler silinecek ve baştan başlanacak. Emin misiniz?')) {
        resetAll();
    }
};

// New: Undo button
$('undo').onclick = () => {
    if (stateHistory.length === 0) { notify('Geri alınacak işlem yok.', 'info'); return; }
    restoreState();
};

$('demo').onclick = () => {
    if (!db) return;
    const first = refs.find(r => r.rate > 0 && r.unit === 'KG' && db.taxes[Gozetim.norm(r.gtip)]);
    rows = [{ model: 'ÖRNEK-001', invoice: 'ÖRNEK FATURA', gtip: first.gtip, amount: 100, expense: 0, freight: 10, kg: 2, qty: 1, country: 'ALMANYA' }];
    fileName = 'Örnek çalışma — gerçek işlem değildir';
    $('usd').value = 50;
    $('eur').value = 56;
    $('payment').value = 'PEŞİN';
    $('agreement').value = 'DI';
    notify('Örnek veriler ve kurlar kullanılıyor. Gerçek işlem için kendi dosyanı ve kurlarını gir.', 'info');
    recalc();
};

$('manual').onclick = () => {
    rows.push({ model: '', gtip: '', amount: '', expense: 0, freight: 0, kg: '', qty: '', country: $('country').value });
    viewMode = 'inputs';
    $('mode').value = 'inputs';
    recalc();
};

init();