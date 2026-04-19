---
id: EXP-0095
title: Workload Identity Federation (FIC) — UAMI → App Registration (secretless Graph auth)
severity: critical
date: 2026-04-19
tags: [fic, uami, managed-identity, secretless, graph-api, auth]
---

# FIC — Secretless Graph Auth via Workload Identity Federation

## Problem
Direct UAMI → Graph yaklaşımı başarısız oldu. UAMI'ye Graph rolleri atamak `az rest POST appRoleAssignedTo` gerektiriyor — bu Privileged Role Admin yetkisi istiyor. Bizim hesapta o yetki yok. Admin CLI bilmiyor.

## Yanlış yaklaşım
`assign_graph_roles.sh` scripti yazdık — 7 Graph rolünü UAMI'nin service principal'ına atıyor. Ama script admin yetkisi istiyor → fail.

## Doğru yaklaşım: FIC
1. App Registration zaten portal'da var, 7 permission granted (admin zaten tıklamış)
2. UAMI'yi App Registration'a FIC ile bağla:
   ```bash
   az ad app federated-credential create --id {APP_ID} --parameters '{
     "name": "uami-federation",
     "issuer": "https://login.microsoftonline.com/{TENANT}/v2.0",
     "subject": "{UAMI_PRINCIPAL_ID}",
     "audiences": ["api://AzureADTokenExchange"]
   }'
   ```
3. Kod: `ClientAssertionCredential(tenant_id, client_id, func=lambda: mi.get_token("api://AzureADTokenExchange").token)`
4. Graph, App Registration'ın permission'larını görür → çalışır

## Sonuç
- ENTRA_CLIENT_SECRET tamamen kaldırıldı
- Permission yönetimi portal'dan (admin CLI'ya gerek yok)
- UAMI secretless auth sağlıyor
- App Registration permission'ları sağlıyor

## Not
- `ENTRA_TENANT_ID` ve `ENTRA_CLIENT_ID` hâlâ gerekli (identifier, secret değil)
- FIC oluşturma bizim hesapla yapılabiliyor (admin gerekmez)
- Sentinel management API için FIC GEREKMİYOR — UAMI direkt DefaultAzureCredential ile gidiyor (Azure RBAC rolü var)
