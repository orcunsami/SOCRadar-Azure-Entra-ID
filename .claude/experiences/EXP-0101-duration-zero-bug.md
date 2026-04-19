---
id: EXP-0101
title: duration=0 pre-existing bug — _process_source returns 0, caller never sets
severity: medium
date: 2026-04-15
tags: [bug, duration, audit, law, pre-existing]
---

# duration=0 Bug — Caller Hiç Set Etmiyordu

## Problem
`_process_source()` return dict'inde `"duration": 0` hardcode edilmiş, `# caller sets this` comment'i var. Ama caller (`socradar_entra_id_import`) hiç set etmiyordu → tüm başarılı run'larda `duration_sec=0` yazılıyordu LAW'a.

## Fix
1. Caller'da: `result["duration"] = round(time.time() - src_start, 1)` eklendi (append'ten ÖNCE)
2. `_process_source`'dan `duration: 0` çıkarıldı — yoksa KeyError patlar (silent-zero trap yok artık)
3. Exception branch zaten kendi duration'ını hesaplıyordu (doğru)
4. Downstream consumer'lar (`audit_summary`, `write_audit`) `.get("duration", 0)` kullanıyor — defensive, doğru

## Doğrulama
Canlıda: `duration=0.3s, 0.6s, 4.6s` — gerçek değerler artık görünüyor.

## Ders
"caller sets this" comment'i = code smell. Ya caller'da implement et, ya sentinel value koy (ama sentinel 0 tehlikeli — gerçek 0 ile karışır). En temizi: field'ı hiç return etme, caller set etsin, yoksa KeyError.
