# RF Identity vs SOCRadar Entra ID — Karşılaştırma

**Tarih:** Mar 2026
**Amaç:** SOCRadar Azure Entra ID entegrasyonu için tasarım rehberi

---

## Temel Fark

| Boyut | Recorded Future | SOCRadar |
|-------|----------------|----------|
| Veri kaynağı | RF Playbook Alerts API | SOCRadar Identity Intelligence API |
| Kapsam | Novel identity exposure (domain bazlı) | Employee credential alarmları + stealer logs |
| Platform entegrasyon | Yok (doğrudan Azure) | Var (SOCRadar platform doğruluyor, Azure aksiyon alıyor) |
| Password validation | Yok | Var (SOCRadar tarafında) |
| Mimari | Logic App only | Logic App (muhtemelen) |

---

## Mimari Karşılaştırma

### RF Yaklaşımı
```
RF API → Custom Connector → Logic App → Entra ID (azuread + azureadip)
                                      ↓
                                   Sentinel (opsiyonel)
                                   LAW (opsiyonel)
```

### SOCRadar Yaklaşımı (Tahmini)
İki seçenek:

**Seçenek A — RF'ye Benzer (Direct)**
```
SOCRadar Identity API → Logic App → Entra ID (azuread + azureadip)
                                   ↓
                                Sentinel incident (opsiyonel)
                                LAW / SOCRadar_EntraID_CL (opsiyonel)
```

**Seçenek B — Platform-Triggered**
```
SOCRadar Platform (validation yapar) → Webhook/Event → Logic App → Entra ID actions
```

Seçenek A daha temiz ve bağımsız. Mevcut Incidents/Feeds pattern'iyle tutarlı.

---

## Entra ID API Kullanımı (Her İkisi İçin Aynı)

### Graph API (azuread connector)
```
GET  /v1.0/users/{upn}                          # Kullanıcı var mı?
POST /v1.0/groups/{group_id}/members/$ref        # Gruba ekle
POST /v1.0/users/{id}/revokeSignInSessions       # Session iptal
PATCH /v1.0/users/{id}  accountEnabled: false    # Hesap kapat
```

### Identity Protection API (azureadip connector)
```
POST /beta/riskyUsers/confirmCompromised         # Risky olarak işaretle
```

**Not:** Password validation Graph API üzerinden yapılamaz — SOCRadar bunu platform tarafında hallediyor.

---

## SOCRadar Endpoint → Logic App Mapping

| SOCRadar Endpoint | Kullanım |
|-------------------|----------|
| `/query` (domain, is_employee=true) | Çalışan credential'larını çek |
| `/breach/query` | Breach verisi (alternatif) |
| `/stealer_logs_on_sale/query` | Dark market'teki satılık loglar |

**Recurrence önerisi:** 6 saat (Feeds ile aynı pattern) veya 15 dakika (RF gibi)
**Lookback:** `log_start_date` = son run zamanı
**Pagination:** `checkpoint` bazlı (bizim cursor pattern'imize benzer)

---

## RF'den Alınacak Pattern'ler

1. **Custom Connector** veya direkt HTTP action — SOCRadar API için
2. **Domain mapping parametresi** — `entra_id_domain` pattern'i, email → UPN dönüşümü
3. **Conditional actions** — enabled/disabled user'a göre farklı aksiyon
4. **azuread + azureadip** connector kullanımı — aynı pattern
5. **Opsiyonel Sentinel incident oluşturma** — bizim mevcut pattern'imiz zaten var

## Mevcut SOCRadar Pattern'lerinden Tutulacaklar

1. **Cross-RG deployment** — WorkspaceResourceGroup parametresi
2. **3-dakika startTime offset** — deploy anında çalışmasın
3. **Onboarding state resource** — Sentinel API için zorunlu
4. **LAW custom table** (SOCRadar_EntraID_CL) — audit trail
5. **Content Hub V3 packaging** — Solutions/SOCRadarEntraID/
6. **"Microsoft Sentinel" branding** — CI pipeline zorunluluğu
7. **startTime parametresi** — tüm Logic App'lerde zorunlu

---

## Önerilen İlk Adımlar

1. SOCRadar'ın hangi seçeneği tercih ettiğini öğren (A: direct vs B: platform-triggered)
2. Required Entra ID permissions listesi çıkar
3. Test tenant'ta App Registration oluştur
4. SOCRadar Identity API'dan test verisi çek
5. RF'nin custom connector pattern'ini incele — SOCRadar API custom connector mı yapacağız?
6. Minimal Logic App: `/query` → Entra ID user lookup → log
