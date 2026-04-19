---
id: EXP-0099
title: AADSTS7000215 is NOT a consent issue — it's a credential error
severity: high
date: 2026-04-15
tags: [aadsts, consent, credential, misclassification, bug-fix]
---

# AADSTS7000215 = Invalid Client Secret, NOT Consent Revocation

## Problem
İlk implementasyonda AADSTS7000215'i `_CONSENT_AADSTS_CODES` set'ine koydum. Bu kod `ConsentRevokedError` raise edip `event_type=consent_revoked` audit event yazıyordu.

## Neden yanlış
AADSTS7000215 = "Invalid client secret provided" — secret expired veya yanlış. Consent ile ilgisi yok. Operator audit log'da `consent_revoked` görünce admin consent yeniden vermeye çalışır — yanlış yöne gider. Aslında secret'ı rotate etmesi lazım.

## Kaynak
[MS Learn — AADSTS7000215](https://learn.microsoft.com/en-us/answers/questions/632524/aadsts7000215-error-from-microsoft-(invalid-client))

## Fix
- `_CONSENT_AADSTS_CODES`'tan çıkarıldı
- 7000215 artık `RuntimeError` → `event_type=token_acquisition_failed` yazdırıyor
- Regression test eklendi: `test_invalid_client_secret_is_not_consent`
- Troubleshooting runbook güncellendi

## Ders
Token error code'larını MS docs'tan doğrulamadan consent set'ine ekleme. Her AADSTS kodu farklı — tahmin etme, doğrula.
