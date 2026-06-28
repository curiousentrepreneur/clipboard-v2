"""Premium arayüz — "Obsidiyen Kasa" tasarım dili.

Gerektirir: pip install customtkinter
(Kurulu değilse main.py otomatik olarak klasik arayüze döner.)

Tasarım kararları:
- Obsidiyen zemin + bakır vurgu: kasa/kilit metaforu, şablon paletlerden uzak.
- Mono yazı tipi yalnızca kriptografik veride (IP, parmak izi, saat):
  biçim, içeriğin doğasını kodlar.
- İmza öğesi: sol "mühür rayı" — hassas mod açılınca kehribar renge döner,
  kullanıcı hangi modda olduğunu her an bilir.
- Durum çubuğu yok; kaybolan toast bildirimleri var.
- Boş cihaz listesi bir davettir: doğrudan "Cihaz ekle" akışına yönlendirir.
"""
import json
import threading
import time
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk
import pyperclip

from . import clipboard_image, core, network, tray

# ---- tasarım belirteçleri ----
C = {
    "bg":        "#0B0D12",  # obsidiyen
    "surface":   "#141823",  # kart
    "surface2":  "#1B2132",  # kabarık kart / giriş
    "hairline":  "#262C3D",  # ince çizgi
    "copper":    "#C98A5B",  # bakır vurgu (kasa pirinci)
    "copper_hv": "#B5754A",
    "amber":     "#E3A23C",  # hassas mod mührü
    "online":    "#46D19A",
    "offline":   "#4A5066",
    "danger":    "#C84B51",
    "text":      "#ECEFF7",
    "muted":     "#8C93A8",
}
SERIF = "Georgia"          # vitrin yüzü (sözcük markası, başlıklar)
MONO = "Consolas"          # kriptografik veri yüzü

MODE_MAP = {"Bu cihaz": core.MODE_LOCAL,
            "Tümü": core.MODE_ALL,
            "Seçili": core.MODE_SELECTED}


class App:
    def __init__(self, c: core.Core):
        self.core = c
        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk(fg_color=C["bg"])
        self.root.title("Pano — güvenli evrensel pano")
        self.root.geometry("1000x680")
        self.root.minsize(860, 580)

        self._sel_vars = {}      # fp -> BooleanVar (kart seçimleri)
        self._dev_sig = None     # cihaz listesi değişim imzası
        self._hist_dirty = True
        self._toast_frame = None

        self._build()
        self.tray = tray.create_tray(self)
        hotkey_ok = tray.register_hotkey(self.send_clipboard_now)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        caps = []
        if core.SPAKE_AVAILABLE:
            caps.append("SPAKE2 etkin")
        if hotkey_ok:
            caps.append(f"kısayol {tray.HOTKEY}")
        if self.tray:
            caps.append("tepside çalışır")
        self.caps_label.configure(text="  ·  ".join(caps) if caps else "")
        self.root.after(300, self._poll)

    # ================= yerleşim =================

    def _build(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # ---------- kenar çubuğu ----------
        side = ctk.CTkFrame(self.root, width=292, fg_color=C["surface"],
                            corner_radius=0)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=22, pady=(24, 6))
        ctk.CTkLabel(brand, text="\u2756", text_color=C["copper"],
                     font=ctk.CTkFont(family=SERIF, size=24)).pack(side="left")
        ctk.CTkLabel(brand, text=" PANO",
                     font=ctk.CTkFont(family=SERIF, size=26, weight="bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkLabel(side, text="güvenli evrensel pano",
                     font=ctk.CTkFont(size=12), text_color=C["muted"]
                     ).pack(anchor="w", padx=24)

        ident = ctk.CTkFrame(side, fg_color=C["surface2"], corner_radius=12)
        ident.pack(fill="x", padx=18, pady=(16, 4))
        ctk.CTkLabel(ident, text=self.core.device_name,
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", padx=14, pady=(10, 0))
        ctk.CTkLabel(ident,
                     text=f"{network.local_ip()}\n{self.core.identity.fingerprint}",
                     font=ctk.CTkFont(family=MONO, size=11),
                     text_color=C["muted"], justify="left"
                     ).pack(anchor="w", padx=14, pady=(2, 10))

        self._section(side, "GÖNDERİM")
        self.seg = ctk.CTkSegmentedButton(
            side, values=list(MODE_MAP),
            command=self._mode_changed,
            fg_color=C["surface2"],
            selected_color=C["copper"], selected_hover_color=C["copper_hv"],
            unselected_color=C["surface2"], unselected_hover_color=C["hairline"],
            text_color=C["text"],
        )
        self.seg.set("Bu cihaz")
        self.seg.pack(fill="x", padx=18, pady=(2, 8))

        self.sw_auto = self._switch(side, "Kopyalayınca otomatik gönder",
                                    self._auto_changed, default=True)
        img_text = ("Görselleri de eşitle" if clipboard_image.AVAILABLE
                    else "Görselleri eşitle (Pillow gerekli)")
        self.sw_img = self._switch(side, img_text, self._img_changed)
        if not clipboard_image.AVAILABLE:
            self.sw_img.configure(state="disabled")

        self._section(side, "GİZLİLİK")
        self.sw_hist = self._switch(side, "Geçmiş tut (yalnızca bellekte)",
                                    self._hist_changed, default=True)
        ttl_row = ctk.CTkFrame(side, fg_color="transparent")
        ttl_row.pack(fill="x", padx=18, pady=(0, 4))
        ctk.CTkLabel(ttl_row, text="Otomatik silme (sn, 0=kapalı)",
                     font=ctk.CTkFont(size=12), text_color=C["muted"]
                     ).pack(side="left")
        self.ttl_entry = ctk.CTkEntry(ttl_row, width=64, height=26,
                                      fg_color=C["surface2"],
                                      border_color=C["hairline"],
                                      text_color=C["text"])
        self.ttl_entry.insert(0, "300")
        self.ttl_entry.pack(side="right")
        self.ttl_entry.bind("<FocusOut>", self._ttl_changed)
        self.ttl_entry.bind("<Return>", self._ttl_changed)
        self.sw_sens = self._switch(
            side, f"Hassas mod · {core.SENSITIVE_CLEAR_SECONDS} sn'de silinir",
            self._sens_changed)

        self.caps_label = ctk.CTkLabel(side, text="",
                                       font=ctk.CTkFont(size=11),
                                       text_color=C["muted"])
        self.caps_label.pack(side="bottom", pady=14)

        # ---------- ana alan ----------
        main = ctk.CTkFrame(self.root, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(1, weight=3)
        main.grid_rowconfigure(3, weight=2)

        # imza öğesi: mühür rayı
        self.seal = ctk.CTkFrame(main, width=4, fg_color=C["hairline"],
                                 corner_radius=0)
        self.seal.grid(row=0, column=0, rowspan=4, sticky="ns")

        top = ctk.CTkFrame(main, fg_color="transparent")
        top.grid(row=0, column=1, sticky="ew", padx=22, pady=(20, 8))
        ctk.CTkLabel(top, text="Cihazlar",
                     font=ctk.CTkFont(family=SERIF, size=22, weight="bold"),
                     text_color=C["text"]).pack(side="left")
        self.sens_pill = ctk.CTkLabel(
            top, text="  HASSAS MOD  ", corner_radius=20,
            fg_color=C["amber"], text_color=C["bg"],
            font=ctk.CTkFont(size=11, weight="bold"))
        # (gizli başlar; hassas mod açılınca pack edilir)
        self._btn(top, "Dosya gönder", self._send_file,
                  outline=True).pack(side="right", padx=(8, 0))
        self._btn(top, "Panodakini gönder", self._send_now,
                  outline=True).pack(side="right", padx=(8, 0))
        self._btn(top, "+  Cihaz ekle", self._add_device).pack(side="right")

        self.dev_area = ctk.CTkScrollableFrame(main, fg_color="transparent")
        self.dev_area.grid(row=1, column=1, sticky="nsew", padx=16)

        hist_head = ctk.CTkFrame(main, fg_color="transparent")
        hist_head.grid(row=2, column=1, sticky="ew", padx=22, pady=(10, 4))
        ctk.CTkLabel(hist_head, text="Geçmiş",
                     font=ctk.CTkFont(family=SERIF, size=17, weight="bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkLabel(hist_head, text="  çift tıkla → panoya",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]
                     ).pack(side="left")
        self._btn(hist_head, "Temizle", self._clear_history,
                  outline=True, small=True).pack(side="right")

        self.hist_area = ctk.CTkScrollableFrame(main, fg_color="transparent")
        self.hist_area.grid(row=3, column=1, sticky="nsew",
                            padx=16, pady=(0, 14))

    # ---- küçük yapı yardımcıları ----

    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=title,
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["muted"]).pack(anchor="w",
                                                 padx=22, pady=(18, 2))

    def _switch(self, parent, text, command, default=False):
        sw = ctk.CTkSwitch(parent, text=text, command=command,
                           font=ctk.CTkFont(size=12),
                           text_color=C["text"],
                           progress_color=C["copper"],
                           fg_color=C["hairline"])
        if default:
            sw.select()
        sw.pack(anchor="w", padx=20, pady=4)
        return sw

    def _btn(self, parent, text, command, outline=False, small=False,
             danger=False):
        h = 26 if small else 34
        if outline:
            return ctk.CTkButton(
                parent, text=text, command=command, height=h,
                fg_color="transparent", hover_color=C["surface2"],
                border_width=1,
                border_color=C["danger"] if danger else C["hairline"],
                text_color=C["danger"] if danger else C["text"],
                corner_radius=9,
                font=ctk.CTkFont(size=12 if small else 13))
        return ctk.CTkButton(
            parent, text=text, command=command, height=h,
            fg_color=C["copper"], hover_color=C["copper_hv"],
            text_color=C["bg"], corner_radius=9,
            font=ctk.CTkFont(size=13, weight="bold"))

    # ================= toast bildirimleri =================

    def toast(self, text, kind="info"):
        bg = {"info": C["surface2"], "ok": "#16352A", "err": "#3A2024"}[kind]
        edge = {"info": C["hairline"], "ok": C["online"], "err": C["danger"]}[kind]
        if self._toast_frame is not None and self._toast_frame.winfo_exists():
            self._toast_frame.destroy()
        t = ctk.CTkFrame(self.root, fg_color=bg, corner_radius=10,
                         border_width=1, border_color=edge)
        ctk.CTkLabel(t, text=text, text_color=C["text"],
                     font=ctk.CTkFont(size=12)).pack(padx=16, pady=9)
        t.place(relx=0.985, rely=0.97, anchor="se")
        self._toast_frame = t
        self.root.after(3200, lambda: t.destroy() if t.winfo_exists() else None)

    # ================= tepsi/kısayol (thread-güvenli) =================

    def show(self):
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift()))

    def send_clipboard_now(self):
        self.root.after(0, self._send_now)

    def quit_app(self):
        self.root.after(0, self._really_quit)

    def _really_quit(self):
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    def _on_close(self):
        if self.tray:
            self.root.withdraw()
        else:
            self._really_quit()

    # ================= olaylar =================

    def _mode_changed(self, value):
        self.core.mode = MODE_MAP[value]

    def _auto_changed(self):
        self.core.auto_send = bool(self.sw_auto.get())

    def _img_changed(self):
        self.core.images_enabled = bool(self.sw_img.get())

    def _hist_changed(self):
        self.core.history_enabled = bool(self.sw_hist.get())

    def _sens_changed(self):
        on = bool(self.sw_sens.get())
        self.core.sensitive_mode = on
        # imza öğesi: mühür rayı renk değiştirir, rozet görünür
        self.seal.configure(fg_color=C["amber"] if on else C["hairline"])
        if on:
            self.sens_pill.pack(side="left", padx=12)
        else:
            self.sens_pill.pack_forget()

    def _ttl_changed(self, _evt=None):
        try:
            self.core.ttl_seconds = max(0, int(self.ttl_entry.get()))
        except ValueError:
            self.ttl_entry.delete(0, "end")
            self.ttl_entry.insert(0, str(self.core.ttl_seconds))

    def _selected_fps(self):
        return {fp for fp, var in self._sel_vars.items() if var.get()}

    def _clear_history(self):
        self.core.clear_history()
        self.toast("Geçmiş temizlendi", "ok")

    # ---- gönderim eylemleri ----

    def _send_now(self):
        try:
            text = pyperclip.paste()
        except Exception:
            text = ""
        if not text:
            self.toast("Pano boş", "err")
            return
        mode = MODE_MAP[self.seg.get()]
        if mode == core.MODE_SELECTED:
            self.core.selected_fps = self._selected_fps()
        if mode == core.MODE_LOCAL:
            fps = self._selected_fps()
            if not fps:
                self.toast("Önce karttan cihaz işaretle", "err")
                return
            self.core.send_clipboard(text, fps_override=fps)
        else:
            self.core.send_clipboard(text)

    def _send_file(self):
        path = filedialog.askopenfilename(parent=self.root)
        if not path:
            return
        fps = None
        if MODE_MAP[self.seg.get()] != core.MODE_ALL:
            fps = self._selected_fps()
            if not fps:
                self.toast("Önce karttan cihaz işaretle", "err")
                return
        try:
            self.core.send_file(path, fps_override=fps)
            self.toast("Dosya gönderiliyor…")
        except Exception as exc:
            self.toast(f"Gönderilemedi: {exc}", "err")

    # ================= cihaz ekleme akışı =================

    def _add_device(self):
        win = ctk.CTkToplevel(self.root, fg_color=C["bg"])
        win.title("Cihaz ekle")
        win.geometry("440x600")
        win.grab_set()
        tabs = ctk.CTkTabview(
            win, fg_color=C["surface"],
            segmented_button_fg_color=C["surface2"],
            segmented_button_selected_color=C["copper"],
            segmented_button_selected_hover_color=C["copper_hv"],
            segmented_button_unselected_color=C["surface2"],
            text_color=C["text"])
        tabs.pack(fill="both", expand=True, padx=14, pady=14)
        t1 = tabs.add("Bu cihazda PIN")
        t2 = tabs.add("Diğer cihaza bağlan")

        # --- sekme 1: PIN + QR göster ---
        pin = self.core.begin_pairing_host()
        ip = network.local_ip()
        ctk.CTkLabel(t1, text="Diğer cihazda 'Bağlan' sekmesini açın",
                     font=ctk.CTkFont(size=13), text_color=C["muted"]
                     ).pack(pady=(14, 2))
        ctk.CTkLabel(t1, text=ip, font=ctk.CTkFont(family=MONO, size=16),
                     text_color=C["text"]).pack()
        ctk.CTkLabel(t1, text=pin,
                     font=ctk.CTkFont(family=SERIF, size=40, weight="bold"),
                     text_color=C["copper"]).pack(pady=(2, 6))
        self._draw_qr(t1, json.dumps({"ip": ip, "pin": pin}))
        ctk.CTkLabel(t1, text="2 dakika geçerli",
                     font=ctk.CTkFont(size=11), text_color=C["muted"]).pack()

        # --- sekme 2: bağlan ---
        ctk.CTkLabel(t2, text="IP adresi veya QR içeriği",
                     font=ctk.CTkFont(size=12), text_color=C["muted"]
                     ).pack(anchor="w", padx=18, pady=(18, 2))
        e_ip = ctk.CTkEntry(t2, fg_color=C["surface2"],
                            border_color=C["hairline"], text_color=C["text"])
        e_ip.pack(fill="x", padx=18)
        ctk.CTkLabel(t2, text="PIN",
                     font=ctk.CTkFont(size=12), text_color=C["muted"]
                     ).pack(anchor="w", padx=18, pady=(12, 2))
        e_pin = ctk.CTkEntry(t2, fg_color=C["surface2"],
                             border_color=C["hairline"], text_color=C["text"])
        e_pin.pack(fill="x", padx=18)
        msg = ctk.CTkLabel(t2, text="", font=ctk.CTkFont(size=12),
                           text_color=C["danger"])
        msg.pack(pady=6)

        def connect():
            raw = e_ip.get().strip()
            pin_v = e_pin.get().strip()
            if raw.startswith("{"):
                try:
                    data = json.loads(raw)
                    raw, pin_v = data["ip"], str(data["pin"])
                except (ValueError, KeyError):
                    msg.configure(text="QR içeriği çözümlenemedi")
                    return
            if not raw or not pin_v:
                msg.configure(text="IP ve PIN gerekli")
                return
            msg.configure(text="")
            self.toast("Eşleştiriliyor…")
            win.destroy()

            def run():
                try:
                    self.core.pair_with(raw, pin_v)
                except Exception as exc:
                    self.core.events.put(("error", f"Eşleştirme: {exc}"))
            threading.Thread(target=run, daemon=True).start()

        self._btn(t2, "Eşleş", connect).pack(padx=18, pady=10, fill="x")

    def _draw_qr(self, parent, payload: str):
        try:
            import qrcode
        except ImportError:
            ctk.CTkLabel(parent, text="QR için: pip install qrcode",
                         font=ctk.CTkFont(size=11),
                         text_color=C["muted"]).pack(pady=6)
            return
        qr = qrcode.QRCode(border=2)
        qr.add_data(payload)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        cell = 5
        size = len(matrix) * cell
        canvas = tk.Canvas(parent, width=size, height=size,
                           bg="white", highlightthickness=0)
        canvas.pack(pady=8)
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    canvas.create_rectangle(
                        x * cell, y * cell, (x + 1) * cell, (y + 1) * cell,
                        fill="#0B0D12", width=0)

    # ================= listeleri tazeleme =================

    def _refresh_devices(self):
        online = self.core.discovery.online
        sig = tuple(sorted(
            (fp, info["name"], fp in online)
            for fp, info in self.core.peers.items()))
        if sig == self._dev_sig:
            return
        self._dev_sig = sig
        saved = {fp: var.get() for fp, var in self._sel_vars.items()}
        for w in self.dev_area.winfo_children():
            w.destroy()
        self._sel_vars = {}

        if not self.core.peers:  # boş durum: bir davet
            empty = ctk.CTkFrame(self.dev_area, fg_color="transparent")
            empty.pack(expand=True, pady=40)
            ctk.CTkLabel(empty, text="\u2756",
                         font=ctk.CTkFont(family=SERIF, size=42),
                         text_color=C["copper"]).pack()
            ctk.CTkLabel(empty, text="Henüz eşleşmiş cihaz yok",
                         font=ctk.CTkFont(size=15, weight="bold"),
                         text_color=C["text"]).pack(pady=(8, 2))
            ctk.CTkLabel(empty,
                         text="Aynı ağdaki cihazını PIN veya QR ile bağla.",
                         font=ctk.CTkFont(size=12),
                         text_color=C["muted"]).pack()
            self._btn(empty, "+  Cihaz ekle",
                      self._add_device).pack(pady=14)
            return

        for fp, info in self.core.peers.items():
            is_on = fp in online
            card = ctk.CTkFrame(self.dev_area, fg_color=C["surface"],
                                corner_radius=14)
            card.pack(fill="x", pady=5, padx=4)
            var = tk.BooleanVar(value=saved.get(fp, False))
            self._sel_vars[fp] = var
            ctk.CTkCheckBox(card, text="", variable=var, width=24,
                            checkbox_width=20, checkbox_height=20,
                            fg_color=C["copper"], hover_color=C["copper_hv"],
                            border_color=C["hairline"]
                            ).pack(side="left", padx=(14, 0), pady=14)
            ctk.CTkLabel(card, text="\u25cf",
                         text_color=C["online"] if is_on else C["offline"],
                         font=ctk.CTkFont(size=13)).pack(side="left", padx=(2, 10))
            col = ctk.CTkFrame(card, fg_color="transparent")
            col.pack(side="left", pady=10)
            ctk.CTkLabel(col, text=info["name"],
                         font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=C["text"]).pack(anchor="w")
            ctk.CTkLabel(col, text=fp,
                         font=ctk.CTkFont(family=MONO, size=11),
                         text_color=C["muted"]).pack(anchor="w")
            self._btn(card, "Kaldır",
                      lambda f=fp: self._unpair(f),
                      outline=True, small=True, danger=True
                      ).pack(side="right", padx=14)
            ctk.CTkLabel(card,
                         text="çevrimiçi" if is_on else "çevrimdışı",
                         font=ctk.CTkFont(size=12),
                         text_color=C["online"] if is_on else C["muted"]
                         ).pack(side="right", padx=8)

    def _unpair(self, fp):
        name = self.core.peers.get(fp, {}).get("name", "?")
        self.core.remove_peer(fp)
        self._dev_sig = None
        self.toast(f"{name} kaldırıldı", "ok")

    def _refresh_history(self):
        if not self._hist_dirty:
            return
        self._hist_dirty = False
        for w in self.hist_area.winfo_children():
            w.destroy()
        if not self.core.history:
            ctk.CTkLabel(self.hist_area, text="Defter boş",
                         font=ctk.CTkFont(size=12),
                         text_color=C["muted"]).pack(pady=18)
            return
        for idx, h in enumerate(reversed(self.core.history)):
            real = len(self.core.history) - 1 - idx
            row = ctk.CTkFrame(self.hist_area, fg_color="transparent")
            row.pack(fill="x")
            ctk.CTkFrame(row, height=1, fg_color=C["hairline"]
                         ).pack(fill="x", pady=(0, 4))
            line = ctk.CTkFrame(row, fg_color="transparent")
            line.pack(fill="x", pady=(0, 5))
            ctk.CTkLabel(line,
                         text=time.strftime("%H:%M",
                                            time.localtime(h["ts"])),
                         font=ctk.CTkFont(family=MONO, size=11),
                         text_color=C["muted"]).pack(side="left", padx=(6, 8))
            ctk.CTkLabel(line, text=f" {h['from']} ", corner_radius=8,
                         fg_color=C["surface2"], text_color=C["muted"],
                         font=ctk.CTkFont(size=10)).pack(side="left")
            text = h["text"].replace("\n", " ")
            if len(text) > 64:
                text = text[:64] + "…"
            lbl = ctk.CTkLabel(line, text=text,
                               font=ctk.CTkFont(size=12),
                               text_color=C["text"], anchor="w")
            lbl.pack(side="left", padx=10, fill="x", expand=True)
            lbl.bind("<Double-Button-1>",
                     lambda e, t=h["text"]: self._copy_back(t))
            ctk.CTkButton(line, text="\u2715", width=26, height=22,
                          fg_color="transparent", hover_color=C["surface2"],
                          text_color=C["muted"],
                          command=lambda i=real: self._del_hist(i)
                          ).pack(side="right", padx=(0, 4))
            ctk.CTkButton(line, text="\u29c9", width=26, height=22,
                          fg_color="transparent", hover_color=C["surface2"],
                          text_color=C["muted"],
                          command=lambda t=h["text"]: self._copy_back(t)
                          ).pack(side="right")

    def _copy_back(self, text):
        self.core._suppress = text
        pyperclip.copy(text)
        self.toast("Panoya kopyalandı", "ok")

    def _del_hist(self, index):
        self.core.delete_history_item(index)

    # ================= olay döngüsü =================

    def _poll(self):
        while not self.core.events.empty():
            evt = self.core.events.get()
            kind = evt[0]
            if kind == "clip_received":
                self.toast(f"{evt[1]} → panoya yazıldı", "ok")
            elif kind == "img_received":
                self.toast(f"{evt[1]} → görsel alındı", "ok")
            elif kind == "file_received":
                self.toast(f"Dosya alındı · {evt[2]}", "ok")
            elif kind == "progress":
                self.toast(f"{evt[1]} ← {evt[2]} · %{evt[3]}")
            elif kind == "cleared":
                self.toast("Hassas içerik panodan silindi")
            elif kind == "sent":
                self.toast(f"{evt[1]} cihazına gönderildi", "ok")
            elif kind == "paired":
                self._dev_sig = None
                self.toast(f"{evt[1]} ile eşleşildi", "ok")
            elif kind == "error":
                self.toast(str(evt[1]), "err")
            elif kind == "history":
                self._hist_dirty = True
        self._refresh_devices()
        self._refresh_history()
        if MODE_MAP[self.seg.get()] == core.MODE_SELECTED:
            self.core.selected_fps = self._selected_fps()
        self.root.after(700, self._poll)

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.core.stop()
