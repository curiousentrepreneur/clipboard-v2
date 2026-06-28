# Labs Clipboard v0.1

Bu paket, önceki Clipboard projesindeki eksik dosya yapısı ve çalıştırma sorunları düzeltilmiş sürümdür.

## Hızlı başlatma - Windows

1. ZIP'i çıkar.
2. Klasöre gir.
3. Kolay yol: `run_windows.bat` dosyasına çift tıkla.
4. Sorun çıkarsa: `run_classic_windows.bat` ile klasik arayüzü aç.

## Terminalden çalıştırma

```bash
python -m pip install -r requirements.txt
python main.py
```

Klasik arayüz:

```bash
python -m pip install cryptography pyperclip Pillow
python main.py --klasik
```

## Bu sürümde düzeltilenler

- `app/` paket yapısı kuruldu.
- `main.py` içindeki `from app.core import Core` hatası giderildi.
- Eksik `tray.py` eklendi.
- Eksik `gui_classic.py` eklendi.
- `requirements.txt` eklendi.
- Windows için tek tık başlatma dosyaları eklendi.
- Premium arayüz çalışmazsa klasik arayüze düşecek yapı tamamlandı.

## İlk test

Aynı ağdaki iki bilgisayarda uygulamayı aç:

1. Bir cihazda `PIN oluştur`.
2. Diğer cihazda `Cihaza bağlan`.
3. IP ve PIN gir.
4. Modu `Tümü` yap.
5. Bir metin kopyala ve `Panoyu gönder` de.

## Not

Bu hâlâ v0.1 geliştirme sürümüdür. Para, hesap sistemi, bulut senkronizasyonu ve AI özellikleri henüz eklenmedi. Önce yerel ağda güvenli pano çekirdeğini sağlamlaştırıyoruz.
