---
id: EXP-0092
title: .env file overrides shell environment variables
severity: high
date: 2026-04-07
tags: [env, dotenv, testing, config]
---

# .env Dosyası Shell Env Var'ı Eziyor

## Problem
Test dosyalarında `.env` yükleyici `os.environ[key] = value` ile her zaman üzerine yazıyordu.
`SOCRADAR_BASE_URL=https://preprod.socradar.com python3 test_botnet.py` çalıştırılsa bile
`.env`'deki `platform.socradar.com` değeri shell env'yi eziyordu.

## Çözüm
```python
# Yanlış
os.environ[key] = value

# Doğru — shell env var'ı varsa .env'den ezme
if key not in os.environ:
    os.environ[key] = value
```

## Kural
`.env` yükleyici her zaman "shell env öncelikli" olmalı. Bu python-dotenv'in default davranışı (`override=False`) ama manual yükleyicide unutulabilir.
