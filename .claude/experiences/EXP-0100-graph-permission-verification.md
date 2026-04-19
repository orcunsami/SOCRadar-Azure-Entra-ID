---
id: EXP-0100
title: Graph granular permissions (RevokeSessions.All etc.) are REAL — reviewer was wrong
severity: high
date: 2026-04-15
tags: [graph-permissions, review, verification, ms-learn]
---

# Granular Graph Permissions Doğrulaması

## Problem
Azure reviewer `User.RevokeSessions.All`, `User-PasswordProfile.ReadWrite.All`, `User.EnableDisableAccount.All` permission'larını "fictional" diye reddetti. Handoff "E2E tested" diyordu ama broad grant (User.ReadWrite.All) hâlâ SP'de olduğu için narrow-only behavior kanıtlanmamıştı.

## Doğrulama
WebSearch ile MS Learn'den tek tek doğrulandı:
- `User.RevokeSessions.All` → [MS Learn](https://learn.microsoft.com/en-us/graph/api/user-revokesigninsessions) — GERÇEK, v1.0
- `User.EnableDisableAccount.All` → [MS Learn](https://learn.microsoft.com/en-us/graph/permissions-reference) — GERÇEK, Şubat 2023'te eklendi
- `User-PasswordProfile.ReadWrite.All` → [graphpermissions.merill.net](https://graphpermissions.merill.net/permission/User-PasswordProfile.ReadWrite.All) — GERÇEK
- `az ad sp show` ile GUID'ler resolve edildi → hepsi gerçek role ID'lere map ediyor

## Sonuç
Reviewer'ın knowledge'ı outdated'dı (bu permission'lar 2023'te eklendi). Ama "handoff'a güven" de tehlikeli — bağımsız doğrulama şart.

## Ders
1. "E2E tested" lafı yetmez — broad grant arkadan her şeyi kapattığı sürece narrow-only kanıtlanmamış demek
2. Reviewer'ı dismiss etmek için MS docs'tan link göster, tahmine dayalı dismiss etme
3. `az ad sp show --id 00000003-... --query "appRoles[?value=='X'].id"` ile GUID resolve et
