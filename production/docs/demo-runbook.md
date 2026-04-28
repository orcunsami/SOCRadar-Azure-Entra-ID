# SOCRadar Entra ID — Demo Runbook

Demo öncesi kontrol listesi ve canlı sunum akışı.

## Pre-Demo Checklist (T-30 dk)

```bash
# 1. Function App Running
az functionapp show --name socradar-entraid-yyqon2cmnnf5w \
  --resource-group test-socradar-deployments --query state -o tsv
# Beklenen: Running

# 2. Workbook'lar listede
az resource list --resource-group test-socradar-deployments \
  --resource-type "microsoft.insights/workbooks" \
  --query "[].tags.\"hidden-title\"" -o tsv
# Beklenen: 4 workbook
#   - SOCRadar Entra ID — PII Exposure
#   - SOCRadar Entra ID — Botnet Data
#   - SOCRadar Entra ID — VIP Protection
#   - SOCRadar Entra ID — Combined Dashboard

# 3. LAW tabloları
WS_ID="659d2cb2-2d64-4f3c-b0fb-77b5d5844849"
for t in PII Botnet VIP EntraID_Audit; do
  echo -n "$t: "
  az monitor log-analytics query -w "$WS_ID" \
    --analytics-query "SOCRadar_${t}_CL | count" -o tsv 2>/dev/null | head -1
done

# 4. testradar2/3 enabled
TOKEN=$(az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv)
for u in testradar2 testradar3; do
  curl -s -H "Authorization: Bearer $TOKEN" \
    "https://graph.microsoft.com/v1.0/users/${u}@SOCRadarCyberIntelligenceIn.onmicrosoft.com?\$select=accountEnabled" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'$u: enabled={d.get(\"accountEnabled\")}')"
done

# 5. Sentinel incident var
SUB="d0ecc63f-6d3a-4c3e-9f76-729831df6c4f"
az rest --method GET \
  --url "https://management.azure.com/subscriptions/${SUB}/resourceGroups/test-socradar-deployments/providers/Microsoft.OperationalInsights/workspaces/entraid-test-ws-v3/providers/Microsoft.SecurityInsights/incidents?api-version=2024-03-01&\$top=1" \
  --query "value[].properties.title" -o tsv
```

## Demo Akışı (15 dk)

### 1. Senaryo Tanımı (2 dk)
> "Müşterimizin çalışanlarının email + şifresi dark web'de leak edildi. SOCRadar bu leak'leri tespit ediyor, biz Azure Function App ile otomatik olarak Entra ID'de ilgili kullanıcıları buluyor ve 7 farklı remediation aksiyonunu uyguluyoruz."

### 2. SOCRadar Platform — Leak Listesi (2 dk)
- preprod.socradar.com → Company 132 → PII Exposure → 2 alarm
- testradar2 (alarmId 89151979): Test Leak Source, password Hucu975301
- testradar3 (alarmId 89151980): Test VIP Leak Source, password Wagu246469

### 3. Azure Function App (2 dk)
- Portal: socradar-entraid-yyqon2cmnnf5w
- Trigger: Timer (6 saatte bir, run_on_startup=true)
- Auth: **Workload Identity Federation (FIC)** — secretless, UAMI üzerinden Graph token
- 4 source × 7 action × audit + lifecycle log

### 4. Workbook'lar (5 dk) — ANA EKRAN

**Combined Dashboard** ile başla:
- 9 toplam compromised user
- Source breakdown: PII=6, Botnet=2, VIP=1

Sırayla aç:
1. **PII Exposure**: 6 records, 6 found in Entra, source breakdown chart
2. **Botnet Data**: 2 records (testradar2/3), device OS+IP breakdown
3. **VIP Protection**: 1 alarm (CEO mention)

### 5. Sentinel Incident (2 dk)
- Microsoft Sentinel → Incidents
- "[SOCRadar Demo] PII Leak — testradar2 credentials exposed"
- High severity, New status, SOCRadar tag

### 6. Action Confirmation — testradar2 (2 dk)
- Entra ID portalında testradar2'yi aç
- Sign-in logs → revokeSignInSessions kanıtı
- Authentication methods → MFA delete kanıtı (force re-registration)
- Group membership → SOCRadar-Quarantine-Test ✓

## Q&A Cevap Kütüphanesi

| Soru | Cevap |
|---|---|
| "Hangi authentication kullanıyor?" | Workload Identity Federation (FIC) — secretless, MSAL üzerinden UAMI token, hiç client_secret yok |
| "Permission'lar?" | 7 narrow Graph permission: User.Read.All, User.RevokeSessions.All, GroupMember.ReadWrite.All, User-PasswordProfile.ReadWrite.All, User.EnableDisableAccount.All, IdentityRiskyUser.ReadWrite.All, UserAuthenticationMethod.ReadWrite.All |
| "Confirm Risky test edildi mi?" | Hayır — P1/P2 lisans gerek (tenant'ımız Free tier). Code çalışır, license verisi kontrol edilince çalışır |
| "MSSP destekliyor mu?" | Yol haritası hazır, henüz implement değil. Single tenant production-ready |
| "Content Hub'da yayında mı?" | Hayır — Incidents/Feeds/TAXII Content Hub PR'larında, Entra ID standalone repo |
| "Throttling?" | 429 retry wrapper var (Retry-After header, 3 retry) |
| "Consent revocation?" | Detect ediliyor → audit'e lifecycle event yazılıyor |

## Demo Sonrası

```bash
# Test data'sı temizleme (gerekirse)
az monitor log-analytics workspace delete --resource-group test-socradar-deployments \
  --workspace-name entraid-test-ws-v3 --yes

# Function App durdur (cost saving)
# az functionapp stop --name socradar-entraid-yyqon2cmnnf5w --resource-group test-socradar-deployments
```

