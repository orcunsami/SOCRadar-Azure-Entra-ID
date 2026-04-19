---
id: EXP-0091
title: Preprod Cloudflare blocks Python User-Agent
severity: medium
date: 2026-04-07
tags: [preprod, cloudflare, user-agent, api]
---

# Preprod Cloudflare Python User-Agent Bloklama

## Problem
`preprod.socradar.com` Cloudflare arkasında. Python urllib'in default User-Agent'ı (`Python-urllib/3.x`) 403 alıyor. curl çalışıyor.

## Çözüm
`User-Agent: SOCRadar-Test/1.0` veya `curl/8.0` header'ı ekle.

## Not
Production (platform.socradar.com) bu sorunu yaşamıyor. Sadece preprod.
Azure Function App'te `requests` kütüphanesi kullanılıyor — default User-Agent farklı, test gerekli.
Preprod bazen tamamen çöküyor (524 timeout), bu Cloudflare'in origin timeout'u.
