# SOCRadar Entra ID Integration — Platform Dokümanı

**Kaynak:** SOCRadar Platform Dokümanı (Mar 2026)
**Konu:** Microsoft Entra ID – Credential Validation Integration

---

## 1. Amaç

Çalışan credential alarmlarında tespit edilen e-postaların gerçekten o organizasyona ait olup olmadığını Microsoft Entra ID üzerinden doğrulamak.

**Kapsam — sadece employee credential alarmları:**
- Employee Credential Detection (Hacker Forum)
- Employee Credential Detection on Telegram
- Compromised Employee Credential from Infected Machine Detected in Dark Market
- Employee Credential Detected in Combolists – No Machine Information

Müşteri/partner credential'ları kapsam dışı.

---

## 2. Yetenekler

- Kullanıcının Entra ID'de var olup olmadığını doğrula
- Hesap durumunu kontrol et (enabled/disabled)
- Opsiyonel: şifre doğruluğunu valide et
- Alarm'ı directory context ile zenginleştir
- Validation sonuçlarına göre alarm severity/priority yeniden hesapla
- Platform veya Entra ID seviyesinde aksiyon al

---

## 3. Konfigürasyon (3 Adım)

### Adım 1 — Validation Configuration

**Gerekli alanlar:**
| Alan | Açıklama |
|------|----------|
| Integration Name | Açıklayıcı isim |
| Tenant ID | Entra ID tenant'ın benzersiz ID'si |
| Client ID | App Registration'ın Application (Client) ID'si |
| Client Secret | App Registration'daki Client Credential secret değeri |

**App Registration Kurulumu:**
1. Entra Admin Center → App registrations → New registration
2. Name gir, "Accounts in this organizational directory only (Single tenant)" seç
3. Register
4. Overview'dan **Application (client) ID** ve **Directory (tenant) ID**'yi kopyala
5. Certificates & secrets → New client secret → Value'yu HEMEN kopyala (bir kez gösterilir!)

**Best Practice:** Sadece bu entegrasyon için dedicated, single-tenant app registration kullan.

---

### Adım 2 — Post-Validation Actions

#### Validation Modları

| Mod | Açıklama |
|-----|----------|
| User Validation | Kullanıcı Entra ID'de var mı? Hesap durumu? |
| User + Password Validation | + Şifre doğruluğunu kontrol et |

**Password Validation Kuralları:**
- Günde en fazla 1 kez per user
- MFA aktif kullanıcılarda ÇALIŞMAZ
- Şifreyle ilgili sonuçlar High Priority

---

#### Validation Sonuçları

| Sonuç | Açıklama |
|-------|----------|
| User not found | Directory'de yok |
| User exists and is enabled | Aktif çalışan |
| User exists but is disabled | Hesap kapalı |
| User is enabled, valid password (High Priority) | AKTİF KOMPROMİZ — kritik! |
| User is enabled, invalid password (High Priority) | Şifre değişmiş olabilir |

---

#### Scenario Konfigürasyonu

- Max 5 scenario
- Her scenario 1+ validation result'a map edilir
- Platform ve/veya Entra ID actions içerebilir
- Password validation içeren scenario'lar daha yüksek öncelik
- Birden fazla eşleşirse sadece EN YÜKSEK öncelikli çalışır
- Çakışan action'lar sistem tarafından otomatik bloklama

---

#### Platform Actions

- Change severity of the alarm
- Add assignee to the related alarm
- Change alarm status
- Add tag to the alarm
- Flag validated user on Botnet and PII pages
- Flag validated password on Botnet and PII pages
- Add user as Former Employee
- Change status of the DRP finding

#### Entra ID Actions

- **Revoke sign-in sessions**
- **Require password change on next login**
- **Add user to a special group**
- **Disable user account**

Sadece employee identity ve yeterli validation confidence ile.

---

### Adım 3 — Review

Tüm konfigürasyonu özetle → Onayla → Entegrasyon aktif.

---

## 4. Status Göstergesi

| Renk | Anlam |
|------|-------|
| 🟢 Yeşil | Aktif, sorun yok |
| 🟡 Sarı | Aktif ama son 24 saatte bazı istekler başarısız |
| 🔴 Kırmızı | Çalışmıyor, bağlantı/auth sorunu |

---

## 5. Örnek Scenario Şablonları

### Scenario 1 — Kullanıcı bulunamadı
- **Trigger:** User not found in directory
- **Actions:** severity → Low, tag "non-employee", status → Resolved, flag user

### Scenario 2 — Aktif çalışan (şifre doğrulaması yok)
- **Trigger:** User exists and is enabled
- **Actions:** severity → Medium, assignee ekle, tag "employee-credential", flag user

### Scenario 3 — Hesap kapalı
- **Trigger:** User exists but is disabled
- **Actions:** severity → Low, tag "disabled-account", Add user as Former Employee

### Scenario 4 — Aktif çalışan, geçersiz şifre (High Priority)
- **Trigger:** User is enabled, invalid password
- **Actions:** severity → High, revoke sessions, require password change, tag "credential-compromise"

### Scenario 5 — Aktif çalışan, geçerli şifre (CRITICAL)
- **Trigger:** User is enabled, valid password
- **Actions:** severity → Critical, **disable user account**, revoke sessions, group'a ekle "Under Investigation"

---

## 6. Mimari Notlar (Azure Logic App Perspektifi)

SOCRadar bu entegrasyonu platform içinde yönetiyor ama Azure Logic App çözümü için:

- **Auth:** App Registration → Client Credentials flow → Access Token → Graph API
- **Graph API Base:** `https://graph.microsoft.com/v1.0/`
- **Identity Protection API:** `https://graph.microsoft.com/beta/riskyUsers/confirmCompromised`
- **Required Permissions (Application):**
  - `User.Read.All` — kullanıcı doğrulama
  - `Group.ReadWrite.All` — gruba ekleme
  - `IdentityRiskyUser.ReadWrite.All` — risky user (P1/P2 lisans gerekli)
  - `Directory.Read.All` — genel lookup
- **Password validation:** Graph API üzerinden değil, Active Directory Authentication Library (ADAL/MSAL) — Logic App'te doğrudan yapılamaz, proxy service gerekebilir
