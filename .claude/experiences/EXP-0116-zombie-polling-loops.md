---
exp: 0116
title: Background polling loop'lar — zombie kalmasın diye max-attempts ZORUNLU
date: 2026-04-29
severity: medium
project: entra-id
---

# Olay
- Apr 28 deploy sırasında: `until grep -qE "DEPLOYMENT COMPLETE|FAILED|ERROR.*deploy" file 2>/dev/null; do sleep 30; done`
- Output dosyasında bash glob hatası vardı (`*/30: No such file or directory`)
- Pattern'lar (`DEPLOYMENT COMPLETE`, `FAILED`, `ERROR.*deploy`) HİÇ MATCHLEMEDİ
- Loop **16 SAAT** sonsuza dek devam etti (sleep 30 cycle)
- User session devam ederken stdout boş, ben fark etmedim

# Kök neden
1. Pattern listesi tüm muhtemel çıkışları kapsamadı (bash error mesajları farklı format)
2. Max-attempts veya timeout YOKTU
3. Output file değişmediği için (yeni dosyaya retry geçti) bekleyiş anlamsızlaştı

# Doğru pattern
**HER ZAMAN** max-attempts ekle:
```bash
ATTEMPTS=0
until [ $ATTEMPTS -ge 30 ] || grep -qE "DONE|FAILED|ERROR" "$FILE" 2>/dev/null; do
  sleep 30
  ATTEMPTS=$((ATTEMPTS+1))
done
[ $ATTEMPTS -ge 30 ] && echo "TIMEOUT after $((ATTEMPTS*30))s" >&2
```

# Veya: trap + timeout coupling
```bash
timeout 600 bash -c 'until grep -qE "DONE|FAILED" "$FILE"; do sleep 30; done'
```

# Doğrulama (zombie var mı kontrol)
```bash
# Long-running bash polling
pgrep -af "until grep" | head
ps -p $PID -o pid,etime,command  # ELAPSED check

# Genel: eskimiş user proc'ları
ps -eo pid,etime,command | awk '$2 ~ /^[0-9]+-/ || $2 ~ /^[0-9]{2,}:/' | head
```

# Önlem
- Background task tasarımı: max-attempts veya timeout ZORUNLU
- Session başında `pgrep -af "until grep"` kontrol et (önceki session'dan kalmasın)
- File-based polling yerine: `wait $PID && check_status` (parent process bilgisi)
- Az CLI long-running operasyonlar için `--no-wait` + ayrı status check

# Bu session'da kanıt
- 73847 (16h elapsed) terminate edildi
- 9652 (yeni) zaten ölmüştü
- Polling şablonu güncellendi: max-attempts'lı versiyon kullanıldı
