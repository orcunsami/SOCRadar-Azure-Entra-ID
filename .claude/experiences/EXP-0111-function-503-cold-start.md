---
exp: 0111
title: Function App 503 — WEBSITE_RUN_FROM_PACKAGE değişimi sonrası uzun cold start
date: 2026-04-28
severity: medium
project: entra-id
---

# Olay
- WEBSITE_RUN_FROM_PACKAGE'ı `1` → release URL → tekrar release URL set ettim
- Restart sonrası function 30+ dk HTTP 503 "Service unavailable"
- Manuel HTTP trigger 503 dönüyor

# Kök neden
Linux Consumption Plan'da WEBSITE_RUN_FROM_PACKAGE değişimi sonrası:
1. Worker yeni package URL'i okur
2. ZIP'i indirir (~26KB → cold start ekstra delay)
3. /home/site/wwwroot'a extract
4. Python venv kurulur (her cold start'ta tekrar)
5. Function host worker register

Tüm bu zinciri Linux Consumption tetiklenmesi 5-15 dk sürer.

# Belirti
- `az functionapp show --query state` → Running ✓
- `az functionapp function show` → registered ✓
- HTTP root → 503
- `/admin/functions/{name}` POST → 503

# Çözüm denemeleri
1. ✅ Yeterli bekleme (10-15 dk)
2. ⚠️ `az functionapp restart` — re-tetikler ama süreyi kısaltmaz
3. ❌ WEBSITE_RUN_FROM_PACKAGE=1 yap → /home/site/wwwroot'ta package yok ise daha kötü
4. 🔧 `func azure functionapp publish --remote-build` → SCM build, daha sağlam

# Önlem
- Production'da sadece tek deploy yöntemi seç (release URL VS func publish)
- Mix etme: birinden diğerine geçiş cold start tetikler
- Demo gibi zaman kritik durumlarda WEBSITE_RUN_FROM_PACKAGE değiştirme

# Doğrulama
```bash
# Cold start tamamlandı mı?
SITE=socradar-entraid-yyqon2cmnnf5w
for i in {1..30}; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://${SITE}.azurewebsites.net/")
  echo "$i: $CODE"
  [ "$CODE" = "200" ] && break
  sleep 30
done
```
