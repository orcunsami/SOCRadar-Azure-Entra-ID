---
id: EXP-0103
title: Graph API role assignment to UAMI requires Privileged Role Admin — portal alternative yok
severity: critical
date: 2026-04-17
tags: [uami, graph-roles, admin, portal, fic, workaround]
---

# UAMI'ye Graph Rolü Atama — Portal'dan Yapılamaz, Admin CLI Gerekir (veya FIC kullan)

## Problem
UAMI'ye Graph API application rolleri (User.Read.All vs.) atamak için:
```bash
az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals/{GRAPH_SP}/appRoleAssignedTo" --body '...'
```
Bu çağrı Privileged Role Admin veya Global Admin gerektirir. Normal kullanıcı → `Authorization_RequestDenied`.

## Portal alternatifi YOK
Microsoft, Managed Identity'lere Graph rolü atamak için portal UI sunmuyor. Enterprise Applications → MI → Permissions sayfası sadece delegated consent gösterir, application role ekletmez.

## Çözüm: FIC
Graph rollerini direkt UAMI'ye atamak yerine:
1. App Registration'da rolleri portal'dan yönet (admin bunu biliyor — Add permission → Grant consent)
2. UAMI'yi App Registration'a FIC ile bağla
3. Kod: `ClientAssertionCredential` kullan
4. → App Registration'ın rolleri geçerli, admin CLI'ya gerek yok

## Ders
"Admin script çalıştırsın" demek kolay — ama admin CLI bilmiyorsa pratik değil. Müdüre portal'dan yapabileceği bir yol sun. FIC bu köprüyü kuruyor.
