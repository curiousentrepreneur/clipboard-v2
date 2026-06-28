"""Çekirdek uygulama mantığı.

- Eşleştirme: spake2 kütüphanesi kuruluysa PAKE tabanlı (üretim kalitesi),
  değilse PIN doğrulamalı HMAC onayına geri düşer.
- Pano izleme: metin (ve etkinse görsel) değişince modlara göre gönderim.
- Dosyalar: 1 MB'lik şifreli parçalar halinde, tek bağlantı üzerinden,
  ilerleme bildirimiyle aktarılır (boyut sınırı pratikte disk kadar).
- Hassas mod: içerik geçmişe yazılmaz, alıcıda 30 sn sonra panodan silinir.
- Geçmiş yalnızca bellekte tutulur, diske YAZILMAZ.
"""
import hashlib
import json
import queue
import random
import threading
import time
import uuid
from pathlib import Path

import pyperclip

from . import clipboard_image, crypto, network

try:
    from spake2 import SPAKE2_A, SPAKE2_B
    SPAKE_AVAILABLE = True
except ImportError:
    SPAKE_AVAILABLE = False

APP_DIR = Path.home() / ".guvenli_pano"
PEERS_FILE = APP_DIR / "peers.json"
IDENTITY_FILE = APP_DIR / "identity.key"
INCOMING_DIR = Path.home() / "GuvenliPano_Gelen"

MODE_LOCAL = "local"        # sadece bu cihazda kopyala
MODE_ALL = "all"            # tüm eşleşmiş cihazlara gönder
MODE_SELECTED = "selected"  # seçili cihazlara gönder

CHUNK_SIZE = 1024 * 1024             # dosya parça boyutu (1 MB)
SENSITIVE_CLEAR_SECONDS = 30         # hassas içerik panodan silinme süresi


class Core:
    def __init__(self, device_name: str):
        self.device_name = device_name
        self.identity = crypto.Identity(IDENTITY_FILE)
        self.peers = self._load_peers()      # fp -> {"name", "pub"}
        self.events = queue.Queue()          # GUI'ye olay kuyruğu

        self.mode = MODE_LOCAL
        self.selected_fps = set()
        self.auto_send = True
        self.sensitive_mode = False          # hassas mod
        self.images_enabled = False          # görsel senkronu
        self.history_enabled = True
        self.ttl_seconds = 300               # 0 = süresiz
        self.history = []                    # [{"text","ts","expires","from"}]

        self.active_pin = None               # eşleştirme bekleme PIN'i
        self._pin_deadline = 0.0
        self._spake_sessions = {}            # sid -> {"key", "deadline"}
        self._incoming = {}                  # tid -> aktarım durumu
        self._last_clip = ""
        self._suppress = ""                  # uzaktan geleni geri yollama
        self._last_img_hash = ""
        self._img_suppress = ""

        self.discovery = network.Discovery(device_name, self.identity.fingerprint)
        self.server = network.Server(self._handle_message)

    # ---------- yaşam döngüsü ----------

    def start(self):
        self.discovery.start()
        self.server.start()
        threading.Thread(target=self._clipboard_loop, daemon=True).start()
        threading.Thread(target=self._image_loop, daemon=True).start()
        threading.Thread(target=self._expiry_loop, daemon=True).start()

    def stop(self):
        self.discovery.stop()
        self.server.stop()

    # ---------- eşleşmiş cihaz kaydı ----------

    def _load_peers(self):
        if PEERS_FILE.exists():
            try:
                return json.loads(PEERS_FILE.read_text())
            except ValueError:
                return {}
        return {}

    def _save_peers(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        PEERS_FILE.write_text(json.dumps(self.peers, indent=2))

    def _add_peer(self, pub_b64: str, name: str):
        fp = hashlib.sha256(crypto.b64d(pub_b64)).hexdigest()[:16]
        self.peers[fp] = {"name": name, "pub": pub_b64}
        self._save_peers()
        self.events.put(("paired", name))

    def remove_peer(self, fp: str):
        self.peers.pop(fp, None)
        self.selected_fps.discard(fp)
        self._save_peers()

    # ---------- eşleştirme ----------

    def begin_pairing_host(self, seconds: int = 120) -> str:
        """Bu cihazda PIN oluştur ve eşleştirme isteği bekle."""
        self.active_pin = f"{random.SystemRandom().randint(0, 999999):06d}"
        self._pin_deadline = time.time() + seconds
        return self.active_pin

    def cancel_pairing(self):
        self.active_pin = None

    def _pin_active(self) -> bool:
        return bool(self.active_pin) and time.time() <= self._pin_deadline

    def pair_with(self, host_ip: str, pin: str):
        """Karşı cihaza (PIN gösteren) bağlanıp eşleş.

        İki taraf da spake2 destekliyorsa PAKE; değilse eski yöntem.
        """
        with network.Session(host_ip) as s:
            hello = s.request({"type": "pair_hello"})
            if not hello or not hello.get("ok"):
                raise RuntimeError(hello.get("hata", "Eşleştirme reddedildi")
                                   if hello else "Yanıt yok")
            if hello.get("spake") and SPAKE_AVAILABLE:
                self._pair_spake(s, pin)
            else:
                self._pair_legacy(s, hello, pin)

    def _pair_spake(self, s: network.Session, pin: str):
        """SPAKE2: PIN'den güçlü ortak anahtar türetilir; kimlik anahtarları
        bu anahtarla şifreli+doğrulanmış olarak değiş tokuş edilir."""
        a = SPAKE2_A(pin.encode())
        sid = uuid.uuid4().hex
        r = s.request({"type": "pair_spake_a", "sid": sid,
                       "a": crypto.b64e(a.start())})
        if not r.get("ok"):
            raise RuntimeError(r.get("hata", "SPAKE eşleştirmesi reddedildi"))
        key = a.finish(crypto.b64d(r["b"]))
        try:
            host = json.loads(crypto.aead_decrypt(
                key, crypto.b64d(r["nonce"]), crypto.b64d(r["box"]),
                aad=b"host").decode())
        except Exception:
            raise RuntimeError("PIN hatalı")
        bundle = json.dumps({
            "name": self.device_name,
            "pub": crypto.b64e(self.identity.public_bytes),
        }).encode()
        nonce, ct = crypto.aead_encrypt(key, bundle, aad=b"client")
        r2 = s.request({"type": "pair_spake_c", "sid": sid,
                        "nonce": crypto.b64e(nonce), "box": crypto.b64e(ct)})
        if not r2.get("ok"):
            raise RuntimeError(r2.get("hata", "Eşleştirme tamamlanamadı"))
        self._add_peer(host["pub"], host.get("name", "?"))

    def _pair_legacy(self, s: network.Session, hello: dict, pin: str):
        """Geriye dönük uyumlu HMAC onaylı eşleştirme."""
        host_pub = crypto.b64d(hello["pub"])
        tag = crypto.pairing_tag(self.identity.private, host_pub, pin, "client")
        reply = s.request({
            "type": "pair_request",
            "name": self.device_name,
            "pub": crypto.b64e(self.identity.public_bytes),
            "tag": tag,
        })
        if not reply or not reply.get("ok"):
            raise RuntimeError(reply.get("hata", "PIN hatalı")
                               if reply else "Yanıt yok")
        expected = crypto.pairing_tag(self.identity.private, host_pub, pin, "host")
        if not crypto.verify_tag(expected, reply.get("tag", "")):
            raise RuntimeError("Karşı cihaz doğrulanamadı")
        self._add_peer(hello["pub"], reply.get("name", "?"))

    # ---------- gelen mesajlar ----------

    def _handle_message(self, msg: dict, ip: str):
        mtype = msg.get("type")

        if mtype == "pair_hello":
            if not self._pin_active():
                return {"ok": False, "hata": "Bu cihaz eşleştirme modunda değil"}
            return {"ok": True,
                    "pub": crypto.b64e(self.identity.public_bytes),
                    "spake": SPAKE_AVAILABLE}

        if mtype == "pair_spake_a":
            if not self._pin_active():
                return {"ok": False, "hata": "Eşleştirme modunda değil"}
            if not SPAKE_AVAILABLE:
                return {"ok": False, "hata": "SPAKE desteklenmiyor"}
            b = SPAKE2_B(self.active_pin.encode())
            msg_b = b.start()
            try:
                key = b.finish(crypto.b64d(msg["a"]))
            except Exception:
                return {"ok": False, "hata": "SPAKE mesajı geçersiz"}
            self._spake_sessions[msg.get("sid", "")] = {
                "key": key, "deadline": time.time() + 120}
            bundle = json.dumps({
                "name": self.device_name,
                "pub": crypto.b64e(self.identity.public_bytes),
            }).encode()
            nonce, ct = crypto.aead_encrypt(key, bundle, aad=b"host")
            return {"ok": True, "b": crypto.b64e(msg_b),
                    "nonce": crypto.b64e(nonce), "box": crypto.b64e(ct)}

        if mtype == "pair_spake_c":
            sess = self._spake_sessions.pop(msg.get("sid", ""), None)
            if not sess or time.time() > sess["deadline"]:
                return {"ok": False, "hata": "Eşleştirme oturumu yok/süresi doldu"}
            try:
                client = json.loads(crypto.aead_decrypt(
                    sess["key"], crypto.b64d(msg["nonce"]),
                    crypto.b64d(msg["box"]), aad=b"client").decode())
            except Exception:
                return {"ok": False, "hata": "PIN hatalı"}
            self.active_pin = None
            self._add_peer(client["pub"], client.get("name", "?"))
            return {"ok": True}

        if mtype == "pair_request":  # eski istemciler için
            if not self._pin_active():
                return {"ok": False, "hata": "Eşleştirme modunda değil"}
            client_pub = crypto.b64d(msg["pub"])
            expected = crypto.pairing_tag(
                self.identity.private, client_pub, self.active_pin, "client")
            if not crypto.verify_tag(expected, msg.get("tag", "")):
                return {"ok": False, "hata": "PIN hatalı"}
            tag = crypto.pairing_tag(
                self.identity.private, client_pub, self.active_pin, "host")
            self.active_pin = None
            self._add_peer(msg["pub"], msg.get("name", "?"))
            return {"ok": True, "name": self.device_name, "tag": tag}

        # ---- bundan sonrası eşleşmiş cihaz gerektirir ----
        fp = msg.get("fp", "")
        peer = self.peers.get(fp)
        if not peer:
            return {"ok": False, "hata": "Eşleşmemiş cihaz"}

        if mtype == "clip":
            try:
                text = self._decrypt_from(peer, msg, aad=fp.encode()).decode()
            except Exception:
                return {"ok": False, "hata": "Şifre çözülemedi"}
            self._suppress = text
            pyperclip.copy(text)
            self._last_clip = text
            if msg.get("sensitive"):
                self._schedule_clear(text)
            else:
                self._add_history(text, source=peer["name"])
            self.events.put(("clip_received", peer["name"], text))
            return {"ok": True}

        if mtype == "img":
            if not clipboard_image.AVAILABLE:
                return {"ok": False, "hata": "Görsel desteği yok (Pillow kurulu değil)"}
            try:
                data = self._decrypt_from(peer, msg, aad=fp.encode())
            except Exception:
                return {"ok": False, "hata": "Şifre çözülemedi"}
            h = hashlib.sha256(data).hexdigest()
            self._img_suppress = h
            self._last_img_hash = h
            if not clipboard_image.put_png(data):
                return {"ok": False, "hata": "Panoya görsel yazılamadı"}
            self.events.put(("img_received", peer["name"]))
            return {"ok": True}

        if mtype == "file_begin":
            try:
                meta = json.loads(
                    self._decrypt_from(peer, msg, aad=fp.encode()).decode())
            except Exception:
                return {"ok": False, "hata": "Şifre çözülemedi"}
            tid = msg.get("tid", "")
            INCOMING_DIR.mkdir(parents=True, exist_ok=True)
            tmp = INCOMING_DIR / f".{tid}.part"
            self._incoming[tid] = {
                "fp": fp,
                "name": Path(str(meta.get("name", "dosya"))).name,  # traversal engeli
                "chunks": int(meta.get("chunks", 0)),
                "next": 0,
                "fh": open(tmp, "wb"),
                "tmp": tmp,
                "peer": peer["name"],
            }
            return {"ok": True}

        if mtype == "file_chunk":
            st = self._incoming.get(msg.get("tid", ""))
            if not st or st["fp"] != fp or msg.get("i") != st["next"]:
                return {"ok": False, "hata": "Geçersiz parça"}
            aad = f"{fp}:{msg['tid']}:{st['next']}".encode()
            try:
                chunk = self._decrypt_from(peer, msg, aad=aad)
            except Exception:
                self._abort_incoming(msg["tid"])
                return {"ok": False, "hata": "Parça şifresi çözülemedi"}
            st["fh"].write(chunk)
            st["next"] += 1
            return {"ok": True}

        if mtype == "file_end":
            tid = msg.get("tid", "")
            st = self._incoming.pop(tid, None)
            if not st or st["fp"] != fp:
                return {"ok": False, "hata": "Aktarım bulunamadı"}
            st["fh"].close()
            if st["next"] != st["chunks"]:
                st["tmp"].unlink(missing_ok=True)
                return {"ok": False, "hata": "Eksik parça"}
            target = INCOMING_DIR / st["name"]
            i = 1
            while target.exists():
                target = INCOMING_DIR / f"{Path(st['name']).stem}_{i}{Path(st['name']).suffix}"
                i += 1
            st["tmp"].rename(target)
            self.events.put(("file_received", st["peer"], str(target)))
            return {"ok": True}

        return {"ok": False, "hata": "Bilinmeyen mesaj"}

    def _decrypt_from(self, peer: dict, msg: dict, aad: bytes) -> bytes:
        return crypto.decrypt(
            self.identity.private,
            crypto.b64d(peer["pub"]),
            crypto.b64d(msg["salt"]),
            crypto.b64d(msg["nonce"]),
            crypto.b64d(msg["ct"]),
            aad=aad,
        )

    def _abort_incoming(self, tid: str):
        st = self._incoming.pop(tid, None)
        if st:
            try:
                st["fh"].close()
                st["tmp"].unlink(missing_ok=True)
            except OSError:
                pass

    # ---------- pano izleme ----------

    def _clipboard_loop(self):
        try:
            self._last_clip = pyperclip.paste()
        except Exception:
            self._last_clip = ""
        while True:
            time.sleep(0.5)
            try:
                text = pyperclip.paste()
            except Exception:
                continue
            if not text or text == self._last_clip:
                continue
            self._last_clip = text
            if text == self._suppress:   # uzaktan gelen metin, geri yollama
                continue
            if self.sensitive_mode:
                self._schedule_clear(text)
            else:
                self._add_history(text, source="bu cihaz")
            self.events.put(("clip_local", text))
            if self.auto_send and self.mode != MODE_LOCAL:
                self.send_clipboard(text)

    def _image_loop(self):
        if not clipboard_image.AVAILABLE:
            return
        while True:
            time.sleep(2.0)
            if not self.images_enabled:
                continue
            png = clipboard_image.grab_png()
            if not png:
                continue
            h = hashlib.sha256(png).hexdigest()
            if h == self._last_img_hash:
                continue
            self._last_img_hash = h
            if h == self._img_suppress:  # uzaktan geleni geri yollama
                continue
            if self.auto_send and self.mode != MODE_LOCAL:
                self.send_image(png)

    # ---------- gönderme ----------

    def targets(self):
        """Moda göre hedef (fp, ip) listesi."""
        online = self.discovery.online
        if self.mode == MODE_ALL:
            fps = set(self.peers)
        elif self.mode == MODE_SELECTED:
            fps = set(self.selected_fps)
        else:
            return []
        return [(fp, online[fp]["ip"]) for fp in fps if fp in online]

    def _resolve_targets(self, fps_override):
        if fps_override is None:
            return self.targets()
        online = self.discovery.online
        return [(fp, online[fp]["ip"]) for fp in fps_override if fp in online]

    def _encrypted_msg(self, mtype: str, peer: dict, plaintext: bytes,
                       aad: bytes, **extra) -> dict:
        salt, nonce, ct = crypto.encrypt(
            self.identity.private, crypto.b64d(peer["pub"]), plaintext, aad)
        msg = {"type": mtype, "fp": self.identity.fingerprint,
               "salt": crypto.b64e(salt), "nonce": crypto.b64e(nonce),
               "ct": crypto.b64e(ct)}
        msg.update(extra)
        return msg

    def send_clipboard(self, text: str, fps_override=None, sensitive=None):
        """Metni hedef cihazlara şifreli olarak gönderir."""
        if sensitive is None:
            sensitive = self.sensitive_mode
        aad = self.identity.fingerprint.encode()
        for fp, ip in self._resolve_targets(fps_override):
            peer = self.peers.get(fp)
            if not peer:
                continue
            msg = self._encrypted_msg("clip", peer, text.encode(), aad,
                                      sensitive=sensitive)
            threading.Thread(target=self._send_one,
                             args=(ip, msg, peer["name"]), daemon=True).start()

    def send_image(self, png: bytes, fps_override=None):
        """Panodaki görseli hedef cihazlara gönderir."""
        aad = self.identity.fingerprint.encode()
        for fp, ip in self._resolve_targets(fps_override):
            peer = self.peers.get(fp)
            if not peer:
                continue
            msg = self._encrypted_msg("img", peer, png, aad)
            threading.Thread(target=self._send_one,
                             args=(ip, msg, peer["name"], 30.0),
                             daemon=True).start()

    def send_file(self, path: str, fps_override=None):
        """Dosyayı 1 MB'lik şifreli parçalar halinde gönderir."""
        p = Path(path)
        size = p.stat().st_size
        targets = self._resolve_targets(fps_override)
        if not targets:
            raise RuntimeError("Çevrimiçi hedef cihaz yok")
        for fp, ip in targets:
            peer = self.peers.get(fp)
            if peer:
                threading.Thread(
                    target=self._send_file_to,
                    args=(p, size, ip, peer), daemon=True).start()

    def _send_file_to(self, p: Path, size: int, ip: str, peer: dict):
        my_fp = self.identity.fingerprint
        tid = uuid.uuid4().hex
        total = max(1, (size + CHUNK_SIZE - 1) // CHUNK_SIZE)
        try:
            with network.Session(ip, timeout=60.0) as s:
                meta = json.dumps({"name": p.name, "size": size,
                                   "chunks": total}).encode()
                r = s.request(self._encrypted_msg(
                    "file_begin", peer, meta, my_fp.encode(), tid=tid))
                if not r.get("ok"):
                    raise RuntimeError(r.get("hata", "reddedildi"))
                with open(p, "rb") as fh:
                    for i in range(total):
                        chunk = fh.read(CHUNK_SIZE)
                        aad = f"{my_fp}:{tid}:{i}".encode()
                        r = s.request(self._encrypted_msg(
                            "file_chunk", peer, chunk, aad, tid=tid, i=i))
                        if not r.get("ok"):
                            raise RuntimeError(r.get("hata", "parça reddedildi"))
                        self.events.put(("progress", peer["name"], p.name,
                                         int((i + 1) * 100 / total)))
                r = s.request({"type": "file_end", "fp": my_fp, "tid": tid})
                if not r.get("ok"):
                    raise RuntimeError(r.get("hata", "tamamlanamadı"))
            self.events.put(("sent", f"{peer['name']} ({p.name})"))
        except Exception as exc:
            self.events.put(("error", f"{peer['name']}: {exc}"))

    def _send_one(self, ip, msg, name, timeout=5.0):
        try:
            reply = network.send_message(ip, msg, timeout=timeout)
            if reply and reply.get("ok"):
                self.events.put(("sent", name))
            else:
                hata = (reply or {}).get("hata", "gönderilemedi")
                self.events.put(("error", f"{name}: {hata}"))
        except Exception as exc:
            self.events.put(("error", f"{name}: {exc}"))

    def _schedule_clear(self, text: str, delay: int = SENSITIVE_CLEAR_SECONDS):
        """Hassas içeriği belirli süre sonra panodan siler (değişmediyse)."""
        def job():
            time.sleep(delay)
            try:
                if pyperclip.paste() == text:
                    self._suppress = ""
                    self._last_clip = ""
                    pyperclip.copy("")
                    self.events.put(("cleared",))
            except Exception:
                pass
        threading.Thread(target=job, daemon=True).start()

    # ---------- geçici geçmiş ----------

    def _add_history(self, text: str, source: str):
        if not self.history_enabled:
            return
        expires = time.time() + self.ttl_seconds if self.ttl_seconds > 0 else None
        self.history.append(
            {"text": text, "ts": time.time(), "expires": expires, "from": source}
        )
        self.events.put(("history",))

    def _expiry_loop(self):
        while True:
            time.sleep(2.0)
            now = time.time()
            before = len(self.history)
            self.history = [
                h for h in self.history
                if h["expires"] is None or h["expires"] > now
            ]
            if len(self.history) != before:
                self.events.put(("history",))

    def clear_history(self):
        self.history.clear()
        self.events.put(("history",))

    def delete_history_item(self, index: int):
        if 0 <= index < len(self.history):
            del self.history[index]
            self.events.put(("history",))
