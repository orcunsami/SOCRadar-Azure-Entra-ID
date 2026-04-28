---
exp: 0108
title: Workbook deploy edilip kullanıcıya "git bak" demek — TEST ETMEDEN onaylama disiplini
date: 2026-04-28
severity: CRITICAL
project: entra-id
---

# Olay
- 4 workbook'u `az monitor app-insights workbook create` ile deploy ettim.
- Kullanıcıya "Workbook'lar hazır, portal link şu" dedim.
- Workbook'u kendim ÖNCE açıp render etmedim.
- Kullanıcı açtı: `Failed to resolve table 'SOCRadar_Botnet_CL'` — tablolar henüz oluşmamıştı çünkü Botnet/VIP toggle'ları kapalıydı.
- Kullanıcı: "ihanet ediyorsun ya"

# Kök neden
**Deploy ≠ Hazır.** Resource oluşturuldu = kaynak Azure'da var. Ama:
- Tablolar yok → KQL fail
- Veri yok → tile boş
- Display name güncellenmemiş (tag cache) → yanlış başlık görünüyor

# Kural
**Demo öncesi her ekranın baştan sona render olduğunu KENDIM doğrulamadan kullanıcıya sunmayacağım.**

Her workbook için test edilecekler:
1. Tablo var mı? (`<table> | summarize count()` → numeric döner mi)
2. KQL hata yok mu? (`SemanticError` aranır)
3. Veri var mı? (count > 0)
4. Display name doğru mu? (tag refresh)
5. Tile/chart render mı? (visualization=tiles için columnMatch valid mi)

# Doğru sıra (her demo için)
1. Toggle'ları aç
2. Function'ı manuel trigger et
3. Audit'te yeni run gör
4. LAW'da tablo + veri doğrula (KQL ile)
5. Workbook'u açıp render kontrol et (her tile)
6. Sonra kullanıcıya göster

# Kullanıcı talebi
> "her adım tek tek kontrol edilecek. tek sorun yaşarsan her şeyi baştan sona tekrar yapacaksın."

Bu cümle artık demo prep'in temel kuralı.
