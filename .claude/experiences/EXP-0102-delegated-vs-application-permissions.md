---
id: EXP-0102
title: Delegated vs Application permissions — az CLI local test sınırları
severity: medium
date: 2026-04-17
tags: [delegated, application, permissions, az-cli, testing, graph-api]
---

# Delegated vs Application Permissions Farkı

## Problem
`az account get-access-token --resource https://graph.microsoft.com` delegated token verir. Bazı Graph action'lar (revokeSignInSessions, disable account, auth method delete) sadece application permission ile çalışır → local test'te 403 alırız.

## Tablo
| Action | Delegated (az CLI) | Application (Function App) |
|--------|:---:|:---:|
| GET /users/{email} | ✅ | ✅ |
| POST revokeSignInSessions | ❌ 403 | ✅ |
| PATCH accountEnabled | ❌ 403 | ✅ |
| PATCH passwordProfile | ✅ (bazı roller ile) | ✅ |
| POST confirmCompromised | ❌ 403 | ✅ (P1/P2) |
| DELETE auth methods | ❌ 403 | ✅ |

## Çözüm
Application permission gerektiren action'ları local'den test edemezsin. Function App'te test et (FIC + App Registration permission'ları).

## Ders
"az CLI ile çalıştırdım, 403 aldım" → bu permission yok demek DEĞİL. Delegated vs Application farkını kontrol et. Function App'te farklı sonuç alabilirsin.
