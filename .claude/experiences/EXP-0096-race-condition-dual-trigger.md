---
id: EXP-0096
title: Race condition — timer + manual trigger çakışması disable/enable sırasını bozar
severity: critical
date: 2026-04-20
tags: [race-condition, timer-trigger, disable-account, enable-account, bug]
---

# Race Condition: Timer + Manual Trigger Çakışması

## Problem
Function App `run_on_startup=True` ayarlı. App Settings değiştiğinde (veya func publish sonrası) Function App restart olur → timer hemen tetiklenir. Aynı anda manual trigger da gönderilirse IKI EXECUTION paralel çalışır.

## Sonuç
İki execution aynı user üzerinde sırayla:
- Execution A: disable → enable (doğru sıra, hesap açık kalır)
- Execution B: enable → disable (YANlış sıra, hesap KİLİTLİ kalır)

Son çalışan disable'ı kazanır → user kilitli.

## Kanıt
```
8:48.9235 [ENTRA] disableAccount dbfeca18 → ok   (execution A)
8:49.2935 [ENTRA] disableAccount dbfeca18 → ok   (execution B — SONRA çalıştı!)
8:49.6222 [ENTRA] enableAccount dbfeca18 → ok    (execution A)
8:49.975  [ENTRA] enableAccount dbfeca18 → ok    (execution B)
```

Ama diğer user'da farklı sıralama olabilir → sonuç belirsiz.

## Çözüm (gelecek)
1. Manual trigger gönderirken timer'ın tetiklenmesini bekle (20s delay yeterli)
2. VEYA `run_on_startup=False` yap (production'da önerilen)
3. VEYA function içinde distributed lock (overkill)

## Kısa çözüm (test sırasında)
Manual trigger gönderirken `run_on_startup` tetiklenmesini hesaba kat — 20s bekle, sonra trigger.
accountEnabled durumunu Graph'tan kontrol et.

## Not
Production'da bu sorun yok — timer 6 saatte bir çalışıyor, manual trigger nadir. Sorun test sırasında ortaya çıkıyor.
