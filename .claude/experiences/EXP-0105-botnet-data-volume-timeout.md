---
id: EXP-0105
title: Botnet 126K records causes function timeout (10 min limit)
severity: high
date: 2026-04-19
tags: [botnet, timeout, consumption-plan, data-volume, function-app]
---

# Botnet Büyük Veri → Function Timeout

## Problem
Checkpoint resetleyip 1 yıllık lookback ile tetikledik. Botnet: 126,312 record, 2,358 employee. Her employee için Graph lookup + 7 action = ~16,500 API çağrısı. Consumption plan timeout 10 dakika (`host.json: functionTimeout: 00:10:00`).

## Sonuç
Function timeout'a düştü — botnet bitmeden kesildi, PII'ya sıra gelmedi.

## Çözüm
1. Test sırasında: gereksiz kaynakları kapat (`ENABLE_BOTNET_SOURCE=false`)
2. Production'da: checkpoint sayesinde her run sadece SON veriyi çeker (126K olmaz)
3. `limit` parametresi ile per-run employee sayısı sınırlanabilir (kodda mevcut — sayfa başına limit)
4. Consumption plan yerine Premium plan (30 dk timeout) düşünülebilir

## Ders
Checkpoint resetleme test için gerekli ama büyük veri kaynaklarında timeout riski var. PII gibi küçük kaynakla test et, botnet'i sadece gerektiğinde aç.
