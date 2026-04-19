---
id: EXP-0094
title: First successful E2E test with preprod + Graph token + Entra ID lookup
severity: info
date: 2026-04-07
tags: [e2e, preprod, entra-id, graph-api, milestone]
---

# İlk Başarılı E2E Test (Preprod + Entra ID)

## Sonuç
- Function App: socradar-entraid-yyqon2cmnnf5w
- RG: test-socradar-deployments
- SOCRadar: preprod.socradar.com, company 132
- Graph token: ACQUIRED ✅
- Botnet: 4 kayıt çekildi, 3 employee, 0 found in Entra ID (email format uyuşmazlığı?)
- PII: 17 kayıt çekildi, 17 employee, 2 FOUND (testradar2 + testradar3), 2 action taken
- Duration: 17.5s
- LAW audit: 2 records written

## Önemli Notlar
- Preprod'a SOCRADAR_BASE_URL app setting override ile bağlandık (ARM template'te yok)
- App Registration: b0afca82, 3/5 permission granted (User.Read.All, User.ReadWrite.All, IdentityRiskyUser)
- testradar1 Botnet'te not_found — muhtemelen "user" field'ında sadece username var, tam email yok
- Admin consent eksik: GroupMember.ReadWrite.All, User.RevokeSessions.All

## Test Users
- testradar1@SOCRadarCyberIntelligenceIn.onmicrosoft.com (Vusu326486)
- testradar2@SOCRadarCyberIntelligenceIn.onmicrosoft.com (Hucu975301)
- testradar3@SOCRadarCyberIntelligenceIn.onmicrosoft.com (Wagu246469)
