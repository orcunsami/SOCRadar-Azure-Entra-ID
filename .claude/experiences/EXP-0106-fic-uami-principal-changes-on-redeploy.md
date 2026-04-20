---
id: EXP-0106
title: FIC breaks on redeploy — UAMI gets new principal ID, FIC still points to old one
severity: critical
date: 2026-04-20
tags: [fic, uami, redeploy, principal-id, breaking, deployment]
---

# FIC Kırılması: Redeploy Sonrası UAMI Yeni Principal ID Alır

## Problem
RG silindi + sıfırdan deploy edildi. ARM template yeni UAMI oluşturdu — FARKLI principal ID ile. Ama App Registration'daki FIC hâlâ ESKİ UAMI'nin principal ID'sine bağlı.

Sonuç: FIC token exchange başarısız → Graph token alınamıyor → tüm Entra aksiyonları sessizce skip ediliyor.

## Kanıt
```
Eski UAMI: 067f9268-4802-43f1-88a0-7ddfccfeab76
Yeni UAMI: d171b593-2887-41a7-85ef-ef21d21e0167
FIC subject: 067f9268... (eski → YANLIŞ!)
```

## Çözüm
FIC'i yeni UAMI'ye güncelle:
```bash
az ad app federated-credential delete --id {APP_ID} --federated-credential-id uami-federation
az ad app federated-credential create --id {APP_ID} --parameters '{
  "name": "uami-federation",
  "issuer": "https://login.microsoftonline.com/{TENANT}/v2.0",
  "subject": "{NEW_UAMI_PRINCIPAL_ID}",
  "audiences": ["api://AzureADTokenExchange"]
}'
```

## Kalıcı çözüm (TODO)
deploy.sh'e FIC güncelleme adımı ekle — her deploy sonrası UAMI principal ID kontrol et, FIC'le eşleşmiyorsa güncelle.

## Ders
- UAMI silinip yeniden oluşturulunca principal ID DEĞİŞİR
- FIC hardcoded subject kullanır — otomatik güncellenMEZ
- Her clean deploy sonrası FIC kontrolü ŞART
- Bu client_secret kullanmayan tüm FIC-based auth'lar için geçerli
