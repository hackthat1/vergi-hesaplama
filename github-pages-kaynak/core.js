(function(root){
const norm=v=>String(v??'').trim().replace(/[^0-9]/g,'');
function num(v){if(typeof v==='number')return Number.isFinite(v)?v:NaN;let s=String(v??'').trim().replace(/\s/g,'');if(!s)return NaN;if(s.includes(','))s=s.replace(/\./g,'').replace(',','.');return Number(s)}
function calculate(row,rule,p){
 const errors=[];const amount=num(row.amount),expense=String(row.expense??'').trim()===''?0:num(row.expense);const usd=num(p.usd),eur=num(p.eur);
 if(!Number.isFinite(usd)||usd<=0||!Number.isFinite(eur)||eur<=0)errors.push('Pozitif USD/TL ve EUR/TL kuru gerekli');
 if(!Number.isFinite(amount)||amount<0||!Number.isFinite(expense)||expense<0)errors.push('Tutar / yan masraf geçersiz');
 if(!rule||!Number.isFinite(rule.rate))errors.push('GTİP tabloda bulunamadı veya oran boş');
 const unit=String(rule?.unit||'').toUpperCase();let qty=0;
 if(rule?.rate>0){qty=num(unit==='KG'?row.kg:unit==='ADET'?row.qty:unit==='M2'||unit==='M3'?row.measure:undefined);if(!Number.isFinite(qty)||qty<0)errors.push(unit+' miktarı gerekli');if(!['KG','ADET','M2','M3'].includes(unit))errors.push('Birim desteklenmiyor');}
 if(errors.length)return {errors};
 const divisor=p.currency==='USD'?usd:p.currency==='TRY'?1:eur;
 const base=(amount+expense)*divisor/eur,threshold=qty*(rule.rate||0)*usd/eur;
 const difference=row.exempt?0:Math.max(0,threshold-base);
 return {errors:[],base,threshold,difference,tryDifference:difference*eur,unit,qty,status:row.exempt?'Kapsam dışı / muaf':rule.rate>0?'Kapsam teyidi gerekli':'Tabloda oran 0'};
}
const api={norm,num,calculate};if(typeof module!=='undefined')module.exports=api;root.Gozetim=api;
})(typeof globalThis!=='undefined'?globalThis:this);
