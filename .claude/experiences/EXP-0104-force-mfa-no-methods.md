---
id: EXP-0104
title: Force MFA Re-registration — deleted=0 when user has no MFA methods registered
severity: low
date: 2026-04-20
tags: [force-mfa, auth-methods, testing, edge-case]
---

# Force MFA Re-reg: deleted=0 Eğer User'da MFA Kayıtlı Değilse

## Durum
`forceMfaRereg → deleted=0 skipped=1 errors=0` — silinecek method yok.

## Sebep
Test user'larda sadece password method var (ID: `28c10230-6103-485e-b985-444c60001490`). Bu method korunuyor (silinemez). Authenticator, phone, FIDO2 gibi method kayıtlı değilse silinecek bir şey yok.

## Test etmek için
User'a MFA register ettirmek lazım:
1. User olarak login → https://mysignins.microsoft.com/security-info
2. "Add sign-in method" → Phone veya Authenticator
3. Sonra function tetikle → `deleted=1` görürsün

## Not
- `deleted=0 skipped=1` hata DEĞİL — doğru davranış
- Production'da çoğu user MFA kayıtlı olacak → deleted>0 görülür
- Edge case: şirket MFA zorunlu kılmamışsa bazı user'larda MFA olmayabilir
