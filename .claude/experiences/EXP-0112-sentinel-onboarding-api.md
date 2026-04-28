---
exp: 0112
title: Sentinel onboarding tek satırlık API call — portal'a girmeye gerek yok
date: 2026-04-28
severity: low
project: entra-id
---

# Senaryo
Function App'in `ENABLE_CREATE_INCIDENT=true` çalışması için workspace'in Sentinel'e onboard
edilmiş olması gerek. Portal'da: "Add Microsoft Sentinel" → workspace seç → 30 sn beklen.

# CLI çözümü (10 sn)
```bash
SUB="d0ecc63f-..."
RG="..."
WS="..."

az rest --method PUT \
  --url "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.OperationalInsights/workspaces/${WS}/providers/Microsoft.SecurityInsights/onboardingStates/default?api-version=2024-03-01" \
  --body '{"properties":{"customerManagedKey":false}}'
```

Sonrası: SecurityInsights solution otomatik kurulur, incidents API açılır.

# Doğrulama
```bash
# Onboard mı?
az resource list -g $RG --resource-type "Microsoft.SecurityInsights/onboardingStates" -o tsv

# Incidents endpoint açıldı mı?
az rest --method GET --url ".../providers/Microsoft.SecurityInsights/incidents?api-version=2024-03-01&\$top=1"
# 200 = onboarded, 400 BadRequest "not onboarded" = kurulmamış
```

# Üzerine: Manuel incident yaratma (demo için)
```bash
INC_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
az rest --method PUT \
  --url ".../providers/Microsoft.SecurityInsights/incidents/${INC_ID}?api-version=2024-03-01" \
  --body '{
    "properties": {
      "title": "[SOCRadar Demo] PII Leak — testradar2",
      "description": "...",
      "severity": "High",
      "status": "New",
      "labels": [{"labelName": "SOCRadar", "labelType": "User"}]
    }
  }'
```

# Notlar
- `labelType: "User"` ZORUNLU (Microsoft Sentinel labels schema)
- Severity: Informational, Low, Medium, High (case-sensitive!)
- Status: New, Active, Closed
- ARM template'in `onboardingStates/default` resource'u bu işi otomatik yapar (production'da)
