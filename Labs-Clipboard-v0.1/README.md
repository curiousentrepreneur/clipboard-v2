# Güvenli Evrensel Pano (Clipboard)

Marka ve işletim sistemi bağımsız, **buluta veri göndermeyen**, uçtan uca
şifreli cihazlar arası kopyala-yapıştır sistemi. Windows, macOS ve Linux'ta
çalışır (masaüstü MVP).

## Özellikler

- ✅ Uçtan uca şifreleme (X25519 anahtar değişimi + AES-256-GCM)
- ✅ **SPAKE2 eşleştirme** (`spake2` kuruluysa) — PIN'den üretim kalitesinde PAKE; kurulu değilse HMAC onayına geri düşer
- ✅ PIN **veya QR kod** ile güvenli cihaz eşleştirme — yetkisiz cihazlar bağlanamaz
- ✅ Kopyalama davranışı seçimi: sadece bu cihaz / tüm cihazlar / seçili cihazlar
- ✅ **Görsel senkronu** (Pillow kuruluysa) — ekran görüntüleri ve panodaki resimler de eşitlenir
- ✅ **Parçalı dosya aktarımı** — 1 MB'lik şifreli parçalar, ilerleme göstergesi, pratikte boyut sınırı yok (`~/GuvenliPano_Gelen` klasörüne iner)
- ✅ **Sistem tepsisi** (pystray kuruluysa) — pencere kapatılınca arka planda çalışmaya devam eder
- ✅ **Global kısayol** (keyboard kuruluysa) — Ctrl+Alt+G ile panodakini anında gönder
- ✅ **Hassas mod**: içerik geçmişe yazılmaz, alıcı cihazda 30 sn sonra panodan otomatik silinir
- ✅ Tamamen yerel ağ üzerinden çalışır, hiçbir sunucu veya bulut yok
- ✅ Geçici pano: geçmiş girdileri belirlenen süre sonunda otomatik silinir
- ✅ Geçmiş yalnızca bellekte tutulur, diske asla yazılmaz
- ✅ Otomatik cihaz keşfi (yerel ağda)

> İsteğe bağlı kütüphaneler kurulu değilse ilgili özellik sessizce devre
> dışı kalır; uygulamanın geri kalanı normal çalışır.

## Arayüz — "Obsidiyen Kasa"

`customtkinter` kuruluysa uygulama premium karanlık arayüzle açılır:

- **Obsidiyen + bakır** palet: kasa/kilit metaforuna bağlı, şablon dışı bir kimlik
- **Mühür rayı**: sol kenardaki ince şerit, hassas mod açılınca kehribar renge
  döner — hangi modda olduğunuz her an görünür
- Cihazlar **kart** olarak: çevrimiçi noktası, mono parmak izi, seçim kutusu
- **Toast bildirimleri**: durum çubuğu yerine kaybolan zarif bildirimler
- Boş cihaz listesi sizi doğrudan eşleştirme akışına davet eder
- Tek pencerede sekmeli **Cihaz ekle** akışı (PIN+QR göster / bağlan)
- Mono yazı tipi yalnızca kriptografik veride (IP, parmak izi, saat)

customtkinter yoksa veya `--klasik` bayrağı verilirse klasik arayüz açılır.

## Kurulum

```bash
pip install -r requirements.txt
python main.py --ad "Çalışma Bilgisayarı"
```

Notlar:
- **Linux:** `pyperclip` için `sudo apt install xclip` (veya `xsel`) gerekir.
- Güvenlik duvarında **TCP 47801** ve **UDP 47800** portlarına yerel ağ
  içinden izin verin.
- Her cihazda farklı `--ad` kullanın.

## Kullanım

1. İki cihazda da uygulamayı başlatın (aynı Wi-Fi / yerel ağda olmalılar).
2. Birinci cihazda **"PIN oluştur (bekle)"** düğmesine basın → IP ve 6 haneli
   PIN görünür.
3. İkinci cihazda **"Cihaza bağlan"** → IP'yi ve PIN'i girin.
4. Eşleşme tamam! Artık "Kopyalama davranışı" bölümünden modu seçin:
   - **Sadece bu cihazda kopyala** — hiçbir şey gönderilmez (varsayılan).
   - **Tüm cihazlara gönder** — kopyaladığınız her metin tüm eşleşmiş
     çevrimiçi cihazlara gider.
   - **Seçili cihazlara gönder** — listeden işaretlediğiniz cihazlara gider.
5. "Otomatik gönder" kapalıysa, **"Panodakini şimdi gönder"** ile manuel
   gönderebilirsiniz (yerel moddayken bile, listeden cihaz seçip tek seferlik
   gönderim yapar).

## Güvenlik mimarisi

| Hedef | Nasıl sağlanıyor |
|---|---|
| Üçüncü taraflara veri gitmemesi | Yalnızca yerel ağ; sunucu/bulut yok |
| Yetkisiz cihazların erişememesi | PIN doğrulamalı eşleştirme; eşleşmemiş cihazlardan gelen mesajlar reddedilir |
| İletişim gizliliği | Her mesaj X25519 ECDH + HKDF + AES-256-GCM ile uçtan uca şifreli; her mesajda yeni salt + nonce |
| Hassas veri koruması | Geçmiş diske yazılmaz; TTL ile otomatik silme; geçmiş tamamen kapatılabilir |
| Kimlik bütünlüğü | Her cihazın kalıcı anahtarı ve kullanıcıya gösterilen parmak izi vardır |

Keşif (UDP broadcast) paketlerinde **asla içerik bulunmaz** — yalnızca cihaz
adı ve parmak izi yayınlanır.

### Bilinen sınırlar (dürüst notlar)

- `spake2` kurulu değilse eşleştirme basitleştirilmiş HMAC onayına döner;
  güvenlik için iki cihazda da `pip install spake2` önerilir.
- Görsel yapıştırma Linux'ta `xclip` veya `wl-clipboard` gerektirir.
- `keyboard` kütüphanesi Linux'ta root yetkisi isteyebilir.
- Cihazların aynı yerel ağda olması gerekir.

## Yol haritası

- [x] QR kod ile eşleştirme
- [x] Parçalı/akışlı dosya aktarımı (ilerleme göstergeli)
- [x] Görsel (resim/ekran görüntüsü) senkronu
- [x] Hassas mod (geçmişsiz + otomatik pano temizleme)
- [x] SPAKE2 tabanlı eşleştirme
- [x] Sistem tepsisi ve global kısayol
- [ ] mDNS/Bonjour ile keşif (broadcast yerine)
- [ ] Yarıda kalan dosya aktarımına devam etme
- [ ] Flutter ile mobil istemciler

## Mobil (Android / iOS) hakkında

Bu Python MVP'si masaüstü içindir. Mobil için aynı protokol şu yollarla
taşınabilir:

- **Android:** Aynı protokolü Kotlin ile uygulamak kolaydır (TCP/UDP +
  `cryptography` karşılığı olarak Tink/BouncyCastle). Arka planda pano
  izleme Android 10+ sürümlerinde kısıtlıdır; ön plan servisi veya paylaş
  menüsü entegrasyonu gerekir.
- **iOS:** Apple, arka planda pano okumayı engeller; tam otomatik senkron
  teknik olarak mümkün değildir. Paylaşım uzantısı (Share Extension) ile
  manuel gönderme yapılabilir.
- **Çapraz platform:** Flutter/Dart ile tek kod tabanından beş platforma da
  derlemek en pratik yoldur; bu projedeki mesaj formatı (JSON + b64 alanlar)
  doğrudan kullanılabilir.
