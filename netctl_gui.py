# -*- coding: utf-8 -*-
"""
netctl_gui.py —— 路由器/光猫管控 傻瓜版图形界面

两个标签页：
  1) 小米路由 192.168.31.1：设备列表、限速(最低 1KB/s)、取消限速、断网/恢复
  2) 光猫 192.168.1.1：设备列表（插网线的设备在这边）、MAC 封禁/解封

用法：python netctl_gui.py
"""
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netctl_core as nc

APP_TITLE = "netctl 网络管控"
FONT = ("Microsoft YaHei UI", 10)
TYPE_NAME = {"1": "电脑", "2": "手机", "8": "网关/路由"}


class App(object):
    def __init__(self, root):
        self.root = root
        self.cfg = nc.Config.load()
        self.router = None
        self.ont = None
        self.devices = []
        self.ont_devices = []
        self.by_iid = {}
        self.ont_by_iid = {}
        self.busy = False
        self.queue = queue.Queue()
        self.auto_refresh = tk.BooleanVar(value=False)
        self.flap_stop = None

        root.title(APP_TITLE)
        root.geometry("1180x640")
        root.minsize(960, 500)

        self._build_ui()
        self._pump()
        self.root.after(200, lambda: self.refresh(async_=True, prompt=True))

    # ------------------------------------------------------------ UI 骨架
    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", font=FONT, rowheight=26)
        style.configure("Treeview.Heading", font=(FONT[0], 10, "bold"))
        style.configure("TButton", font=FONT)
        style.configure("TLabel", font=FONT)
        style.configure("TNotebook.Tab", font=FONT, padding=(14, 6))

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.tab_router = ttk.Frame(self.nb)
        self.tab_ont = ttk.Frame(self.nb)
        self.nb.add(self.tab_router, text="小米路由 192.168.31.1")
        self.nb.add(self.tab_ont, text="光猫 192.168.1.1（插网线的设备在这边）")
        self._build_router_tab()
        self._build_ont_tab()

    def _build_router_tab(self):
        top = ttk.Frame(self.tab_router, padding=(10, 8, 10, 4))
        top.pack(fill="x")
        ttk.Label(top, text="路由器").pack(side="left")
        self.host_var = tk.StringVar(value=self.cfg.host)
        ttk.Entry(top, textvariable=self.host_var, width=16).pack(side="left", padx=6)
        self.status_var = tk.StringVar(value="准备就绪")
        ttk.Label(top, textvariable=self.status_var, foreground="#555").pack(side="left", padx=12)
        ttk.Button(top, text="刷新设备 (F5)", command=lambda: self.refresh(with_link=True)).pack(side="right")
        ttk.Checkbutton(top, text="每 5 秒自动刷新", variable=self.auto_refresh,
                        command=self._toggle_auto).pack(side="right", padx=10)

        mid = ttk.Frame(self.tab_router, padding=(10, 0, 10, 4))
        mid.pack(fill="both", expand=True)
        columns = ("idx", "name", "mac", "ip", "online", "link", "uptime", "up", "down", "limit", "state")
        heads = ("序号", "设备名称", "MAC", "IP", "在线", "接入", "在线时长", "上行", "下行", "限速", "状态")
        widths = (50, 230, 150, 120, 50, 90, 95, 85, 85, 95, 130)
        self.tree = ttk.Treeview(mid, columns=columns, show="headings", selectmode="browse")
        for col, head, width in zip(columns, heads, widths):
            self.tree.heading(col, text=head)
            self.tree.column(col, width=width,
                             anchor="center" if col not in ("name", "mac", "state") else "w")
        self.tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        bar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.tag_configure("self", background="#fff7e0")
        self.tree.tag_configure("limited", background="#ffe9e9")
        self.tree.tag_configure("blocked", background="#eeeeee")
        self.tree.bind("<Double-1>", lambda e: self.quick_limit())

        bottom = ttk.Frame(self.tab_router, padding=(10, 4, 10, 10))
        bottom.pack(fill="x")
        ttk.Label(bottom, text="限速值").pack(side="left")
        self.kb_var = tk.StringVar(value="1")
        ttk.Spinbox(bottom, from_=1, to=100000, width=7, textvariable=self.kb_var,
                    font=FONT).pack(side="left", padx=4)
        ttk.Label(bottom, text="KB/s").pack(side="left")
        self.btn_limit = ttk.Button(bottom, text="限速选中设备", command=self.limit_selected)
        self.btn_limit.pack(side="left", padx=(12, 4))
        self.btn_free = ttk.Button(bottom, text="取消限速", command=self.free_selected)
        self.btn_free.pack(side="left", padx=4)
        self.btn_block = ttk.Button(bottom, text="禁止上网", command=lambda: self.block_selected(True))
        self.btn_block.pack(side="left", padx=4)
        self.btn_unblock = ttk.Button(bottom, text="恢复上网", command=lambda: self.block_selected(False))
        self.btn_unblock.pack(side="left", padx=4)
        ttk.Separator(bottom, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bottom, text="全部限速", command=self.limit_all).pack(side="left", padx=4)
        self.btn_pause = ttk.Button(bottom, text="暂停全部限速", command=lambda: self.qos(False))
        self.btn_pause.pack(side="left", padx=4)
        self.btn_resume = ttk.Button(bottom, text="恢复限速", command=lambda: self.qos(True))
        self.btn_resume.pack(side="left", padx=4)
        ttk.Button(bottom, text="设置密码", command=self.set_password).pack(side="right")
        self.root.bind("<F5>", lambda e: self.refresh(with_link=True))

    def _build_ont_tab(self):
        top = ttk.Frame(self.tab_ont, padding=(10, 8, 10, 4))
        top.pack(fill="x")
        self.ont_status_var = tk.StringVar(value="点「刷新」读取光猫设备")
        ttk.Label(top, textvariable=self.ont_status_var, foreground="#555").pack(side="left")
        ttk.Button(top, text="刷新光猫设备", command=self.refresh_ont).pack(side="right")
        ttk.Button(top, text="设置光猫密码",
                   command=self.set_ont_password).pack(side="right", padx=6)

        mid = ttk.Frame(self.tab_ont, padding=(10, 0, 10, 4))
        mid.pack(fill="both", expand=True)
        columns = ("idx", "name", "ip", "mac", "link", "type", "port", "state")
        heads = ("序号", "名称", "IP", "MAC", "接入", "类型", "端口", "状态")
        widths = (50, 260, 130, 160, 80, 110, 70, 110)
        self.ont_tree = ttk.Treeview(mid, columns=columns, show="headings", selectmode="browse")
        for col, head, width in zip(columns, heads, widths):
            self.ont_tree.heading(col, text=head)
            self.ont_tree.column(col, width=width,
                                 anchor="center" if col not in ("name", "mac") else "w")
        self.ont_tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(mid, orient="vertical", command=self.ont_tree.yview)
        bar.pack(side="right", fill="y")
        self.ont_tree.configure(yscrollcommand=bar.set)
        self.ont_tree.tag_configure("blocked", background="#eeeeee")

        bottom = ttk.Frame(self.tab_ont, padding=(10, 4, 10, 10))
        bottom.pack(fill="x")
        self.btn_ont_block = ttk.Button(bottom, text="封禁选中设备（MAC 黑名单）",
                                        command=lambda: self.block_ont(True))
        self.btn_ont_block.pack(side="left", padx=4)
        self.btn_ont_unblock = ttk.Button(bottom, text="解封选中设备",
                                          command=lambda: self.block_ont(False))
        self.btn_ont_unblock.pack(side="left", padx=4)
        ttk.Button(bottom, text="封禁记录 / 恢复封禁",
                   command=self.show_history).pack(side="left", padx=4)
        self.btn_flap = ttk.Button(bottom, text="间歇封禁…", command=self.start_flap)
        self.btn_flap.pack(side="left", padx=4)
        ttk.Label(bottom, foreground="#777",
                  text="说明：光猫只能按 MAC 封禁/解封；它的限速最小粒度 512Kbps，限不住游戏。").pack(
            side="left", padx=12)

    # ------------------------------------------------------------ 基础设施
    def _pump(self):
        try:
            while True:
                func, args = self.queue.get_nowait()
                func(*args)
        except queue.Empty:
            pass
        self.root.after(120, self._pump)

    def _run(self, worker, on_ok, on_err=None):
        if self.busy:
            self.status_var.set("上一个操作还没完成…")
            return
        self.busy = True
        self._set_buttons(False)
        self.status_var.set("处理中…")

        def target():
            try:
                result = worker()
                self.queue.put((lambda: self._done_ok(on_ok, result), ()))
            except Exception as exc:  # noqa: BLE001
                err = exc
                self.queue.put((lambda: self._done_err(on_err, err), ()))

        threading.Thread(target=target, daemon=True).start()

    def _done_ok(self, on_ok, result):
        self.busy = False
        self._set_buttons(True)
        try:
            on_ok(result)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, str(exc))

    def _done_err(self, on_err, exc):
        self.busy = False
        self._set_buttons(True)
        if on_err:
            on_err(exc)
        else:
            self.status_var.set("出错：" + str(exc))
            messagebox.showerror(APP_TITLE, str(exc))

    def _set_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        for btn in (self.btn_limit, self.btn_free, self.btn_block, self.btn_unblock,
                    self.btn_pause, self.btn_resume, self.btn_ont_block, self.btn_ont_unblock):
            btn.configure(state=state)

    # ------------------------------------------------------------ 小米路由
    def _ensure_router(self, prompt=True):
        if self.router and self.router.token:
            return self.router
        if not self.cfg.password:
            if not prompt:
                raise nc.RouterError("还没有配置路由器管理密码")
            pw = simpledialog.askstring(APP_TITLE, "第一次使用，请输入小米路由器管理密码：", show="*")
            if not pw:
                raise nc.RouterError("没有输入密码，无法继续")
            self.cfg.set_password(pw)
            self.cfg["host"] = self.host_var.get().strip() or nc.DEFAULT_HOST
            self.cfg.save()
        self.cfg["host"] = self.host_var.get().strip() or nc.DEFAULT_HOST
        self.router = nc.Router(self.cfg)
        self.router.login()
        return self.router

    def refresh(self, async_=True, prompt=True, with_link=False):
        """with_link=True 时会临时开一下 QoS 读"接入方式"（有线/WiFi），只给手动刷新用。"""
        def worker():
            router = self._ensure_router(prompt)
            return router.devices(with_link=with_link), router.qos_state()

        def ok(result):
            devices, state = result
            self.devices = devices
            self._fill_tree(devices)
            self.status_var.set("已连接 %s ｜ 设备 %d 台 ｜ QoS %s(%s) ｜ 限速中 %d 台" % (
                self.cfg.host, len(devices), "开" if state["on"] else "关",
                state["mode_name"], len(state["limits"])))

        if async_:
            self._run(worker, ok)
        else:
            devices, state = worker()
            ok((devices, state))
            return devices

    def refresh_blocking(self):
        return self.refresh(async_=False)

    def _fill_tree(self, devices):
        selected = self.tree.selection()
        keep = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        self.by_iid = {}
        for dev in devices:
            iid = str(dev.idx)
            tags = []
            if dev.is_self:
                tags.append("self")
            if not dev.allowed:
                tags.append("blocked")
            elif (dev.limit_up or 0) > 0 or (dev.limit_down or 0) > 0:
                tags.append("limited")
            self.tree.insert("", "end", iid=iid, tags=tags, values=(
                dev.idx, dev.name, dev.mac, dev.ip or "-", "是" if dev.online else "否",
                dev.link_text, dev.uptime_text, dev.up_text, dev.down_text,
                dev.limit_text, dev.state_text))
            self.by_iid[iid] = dev
        if keep and keep in self.by_iid:
            self.tree.selection_set(keep)

    def selected_device(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "先在上面选一台设备")
            return None
        return self.by_iid.get(sel[0])

    def _kb(self):
        try:
            kb = int(float(self.kb_var.get()))
        except ValueError:
            kb = 1
        return max(0, kb)

    def quick_limit(self):
        dev = self.selected_device()
        if dev:
            self._apply_limit(dev, self._kb())

    def limit_selected(self):
        dev = self.selected_device()
        if not dev:
            return
        if dev.is_self and not messagebox.askyesno(
                APP_TITLE, "这是你自己这台电脑，限速后你也会断网（可以用「取消限速」恢复）。仍然继续？"):
            return
        self._apply_limit(dev, self._kb())

    def _apply_limit(self, dev, kb):
        def worker():
            router = self._ensure_router()
            router.set_limit(dev.mac, kb, kb)
            return router.devices(), router.qos_state()

        def ok(result):
            devices, state = result
            self.devices = devices
            self._fill_tree(devices)
            self.status_var.set("已把「%s」限速为 %d KB/s" % (dev.name, kb))

        self._run(worker, ok)

    def free_selected(self):
        dev = self.selected_device()
        if not dev:
            return

        def worker():
            router = self._ensure_router()
            restored = router.clear_limit(dev.mac)
            return router.devices(), restored

        def ok(result):
            devices, restored = result
            self.devices = devices
            self._fill_tree(devices)
            self.status_var.set("已取消「%s」的限速%s" % (
                dev.name, "，QoS 也恢复关闭" if restored else ""))

        self._run(worker, ok)

    def block_selected(self, blocked):
        dev = self.selected_device()
        if not dev:
            return
        if blocked and dev.is_self and not messagebox.askyesno(
                APP_TITLE, "这是你自己这台电脑，断网后这个程序也连不上路由器了。继续？"):
            return
        if blocked and not messagebox.askyesno(APP_TITLE, "直接把「%s」断网？" % dev.name):
            return

        def worker():
            router = self._ensure_router()
            router.set_blocked(dev.mac, blocked)
            return router.devices()

        def ok(devices):
            self.devices = devices
            self._fill_tree(devices)
            self.status_var.set("「%s」已%s" % (dev.name, "禁止上网" if blocked else "恢复上网"))

        self._run(worker, ok)

    def limit_all(self):
        kb = self._kb()
        if not messagebox.askyesno(
                APP_TITLE, "给所有设备限速 %d KB/s 会把你自己的电脑也算进去，确定？" % kb):
            return

        def worker():
            router = self._ensure_router()
            devices = router.devices()
            for dev in devices:
                router.set_limit(dev.mac, kb, kb)
            return router.devices()

        def ok(devices):
            self.devices = devices
            self._fill_tree(devices)
            self.status_var.set("已对 %d 台设备限速 %d KB/s" % (len(devices), kb))

        self._run(worker, ok)

    def qos(self, on):
        def worker():
            router = self._ensure_router()
            router.qos_switch(on)
            return router.devices()

        def ok(devices):
            self.devices = devices
            self._fill_tree(devices)
            self.status_var.set("已%s全部限速" % ("恢复" if on else "暂停"))

        self._run(worker, ok)

    def set_password(self):
        pw = simpledialog.askstring(APP_TITLE, "新的小米路由器管理密码：", show="*")
        if not pw:
            return
        self.cfg.set_password(pw)
        self.cfg["host"] = self.host_var.get().strip() or nc.DEFAULT_HOST
        self.cfg.save()
        self.router = None
        self.status_var.set("密码已保存，正在验证…")

        def worker():
            router = self._ensure_router()
            return router.devices()

        def ok(devices):
            self.devices = devices
            self._fill_tree(devices)
            self.status_var.set("密码已更新并验证通过")

        self._run(worker, ok)

    def _toggle_auto(self):
        if self.auto_refresh.get():
            self._auto_tick()

    def _auto_tick(self):
        if not self.auto_refresh.get():
            return
        if not self.busy:
            self.refresh()
        self.root.after(5000, self._auto_tick)

    # ------------------------------------------------------------ 光猫
    def _ensure_ont(self):
        from ont_core import OntClient
        if self.ont:
            return self.ont
        if not self.cfg.ont_password:
            pw = simpledialog.askstring(
                APP_TITLE, "请输入光猫管理密码（账号 %s）：" % self.cfg.ont_user, show="*")
            if not pw:
                raise RuntimeError("没有输入光猫密码")
            self.cfg.set_ont_password(pw)
            self.cfg["ont_host"] = self.cfg.get("ont_host") or "192.168.1.1"
            self.cfg["ont_user"] = self.cfg.get("ont_user") or "CMCCAdmin"
            self.cfg.save()
        self.ont = OntClient(self.cfg.ont_host, self.cfg.ont_user, self.cfg.ont_password)
        self.ont.login()
        return self.ont

    def refresh_ont(self):
        def worker():
            ont = self._ensure_ont()
            rows = ont.devices()
            try:
                blocked = {(i.get("MACAddress") or "").upper()
                           for i in ont.mac_filter()["list"]}
            except Exception:
                # 设备表已经拿到了，黑名单读失败也不影响显示
                blocked = set()
            # 把设备上已有、但本地没记录的黑名单（比如你直接在光猫后台手动加的）同步进来
            added = 0
            if blocked:
                try:
                    added = nc.BlockHistory().sync_from_device(blocked, rows, where="ont")
                except Exception:
                    added = 0
            return rows, blocked, added

        def ok(result):
            rows, blocked, added = result
            self.ont_devices = rows
            self.ont_tree.delete(*self.ont_tree.get_children())
            self.ont_by_iid = {}
            for d in rows:
                iid = str(d["idx"])
                is_blocked = (d["mac"] or "").upper() in blocked
                tags = ("blocked",) if is_blocked else ()
                self.ont_tree.insert("", "end", iid=iid, tags=tags, values=(
                    d["idx"], d["name"], d["ip"] or "-", d["mac"] or "-",
                    "有线" if str(d["wlan"]) != "1" else "WiFi",
                    TYPE_NAME.get(str(d["type"]), "类型" + str(d["type"])),
                    d["port"], "已封禁" if is_blocked else "正常"))
                self.ont_by_iid[iid] = d
            hist = nc.BlockHistory()
            open_cnt = len(hist.open_entries("ont"))
            extra = "（本次从光猫同步 %d 条）" % added if added else ""
            self.ont_status_var.set(
                "光猫 %s ｜ 设备 %d 台 ｜ 已封禁 %d 台 ｜ 记录中封禁 %d 条%s" % (
                    self.cfg.ont_host, len(rows),
                    sum(1 for d in rows if (d["mac"] or "").upper() in blocked),
                    open_cnt, extra))

        self._run(worker, ok, on_err=lambda e: self.ont_status_var.set("出错：" + str(e)))

    def block_ont(self, blocked):
        sel = self.ont_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "先在光猫列表里选一台设备")
            return
        dev = self.ont_by_iid.get(sel[0])
        if not dev or not dev.get("mac"):
            messagebox.showinfo(APP_TITLE, "这台设备没有 MAC，无法操作")
            return
        if blocked and not messagebox.askyesno(
                APP_TITLE, "在光猫上封禁「%s」(%s)？会立即断网。" % (dev["name"], dev["mac"])):
            return

        def worker():
            ont = self._ensure_ont()
            ok_ = ont.block(dev["mac"], blocked)
            # 本地记录：程序重启后也能看到封过谁
            hist = nc.BlockHistory()
            if blocked:
                hist.record_block(dev["mac"], dev["name"], dev.get("ip", ""), where="ont")
            else:
                hist.record_unblock(dev["mac"], where="ont")
            rows = ont.devices()
            try:
                listed = {(i.get("MACAddress") or "").upper() for i in ont.mac_filter()["list"]}
            except Exception:
                listed = set()
            return rows, listed, ok_

        def ok(result):
            rows, listed, changed = result
            self.ont_devices = rows
            self.refresh_ont()
            self.ont_status_var.set("光猫上「%s」已%s%s（已记录）" % (
                dev["name"], "封禁" if blocked else "解封",
                "" if changed else "（本来就是这个状态）"))

        self._run(worker, ok, on_err=lambda e: self.ont_status_var.set("出错：" + str(e)))

    # ------------------------------------------------------------ 封禁记录
    def show_history(self):
        def worker():
            hist = nc.BlockHistory()
            entries = hist.entries("ont")
            current = None
            try:
                ont = self._ensure_ont()
                current = {(i.get("MACAddress") or "").upper() for i in ont.mac_filter()["list"]}
            except Exception:
                current = None
            return hist, entries, current

        def ok(result):
            hist, entries, current = result
            win = tk.Toplevel(self.root)
            win.title("封禁记录（本地保存，重启不丢）")
            win.geometry("900x440")
            txt = tk.Text(win, font=FONT, wrap="none")
            txt.pack(fill="both", expand=True, padx=8, pady=8)
            if not entries:
                txt.insert("end", "还没有任何封禁记录。\n\n在光猫列表里封禁设备后会自动记录。")
            else:
                txt.insert("end", "记录文件：%s\n\n" % hist.path)
                if current is None:
                    txt.insert("end", "（本次没连上光猫，只显示本地记录）\n\n")
                txt.insert("end", "%-18s %-22s %-15s %-20s %-20s %s\n" % (
                    "MAC", "名称", "IP", "封禁时间", "解封时间", "当前状态"))
                txt.insert("end", "-" * 130 + "\n")
                for e in entries:
                    if e.get("unblocked_at"):
                        state = "已解封"
                    elif current is not None and e["mac"] not in current:
                        state = "⚠ 黑名单里没有（被人解封/光猫被重置？）"
                    elif current is not None:
                        state = "封禁生效中"
                    else:
                        state = "封禁中（未核对）"
                    txt.insert("end", "%-18s %-22s %-15s %-20s %-20s %s\n" % (
                        e["mac"], (e.get("name") or "")[:22], e.get("ip") or "-",
                        e.get("blocked_at") or "-", e.get("unblocked_at") or "-", state))
            txt.configure(state="disabled")

            btns = ttk.Frame(win)
            btns.pack(fill="x", padx=8, pady=(0, 8))
            ttk.Button(btns, text="按记录重新封禁（恢复被解封的）",
                       command=lambda: (win.destroy(), self.reapply_history())).pack(side="left")
            ttk.Button(btns, text="关闭", command=win.destroy).pack(side="right")

        self._run(worker, ok, on_err=lambda e: messagebox.showerror(APP_TITLE, str(e)))

    def reapply_history(self):
        def worker():
            ont = self._ensure_ont()
            current = {(i.get("MACAddress") or "").upper() for i in ont.mac_filter()["list"]}
            hist = nc.BlockHistory()
            alive, gone = hist.diff(current, where="ont")
            done = 0
            for e in gone:
                ont.block(e["mac"], True)
                done += 1
            return done

        def ok(done):
            self.ont_status_var.set("按记录重新封禁：%d 台" % done)
            self.refresh_ont()

        self._run(worker, ok, on_err=lambda e: self.ont_status_var.set("出错：" + str(e)))

    # ------------------------------------------------------------ 间歇封禁
    def start_flap(self):
        sel = self.ont_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "先在光猫列表里选一台设备")
            return
        dev = self.ont_by_iid.get(sel[0])
        if not dev or not dev.get("mac"):
            return
        win = tk.Toplevel(self.root)
        win.title("间歇封禁：%s" % dev.get("name", ""))
        win.geometry("400x260")
        win.transient(self.root)
        vars_ = {}
        rows = [("封禁秒数", "5"), ("解封秒数", "4"),
                ("循环轮数（0=一直）", "10"), ("随机抖动 0~1（0.3=±30%）", "0.3")]
        for i, (label, default) in enumerate(rows):
            ttk.Label(win, text=label).grid(row=i, column=0, padx=12, pady=8, sticky="w")
            var = tk.StringVar(value=default)
            ttk.Entry(win, textvariable=var, width=12).grid(row=i, column=1, padx=12, pady=8)
            vars_[i] = var
        tip = ttk.Label(win, foreground="#777",
                        text="效果：封几秒/解几秒循环，对方会以为网络不稳定。\n"
                             "停止后自动恢复上网，并记录到 flap_log.json。")
        tip.grid(row=4, column=0, columnspan=2, padx=12, pady=4, sticky="w")

        def go():
            try:
                on = float(vars_[0].get())
                off = float(vars_[1].get())
                cycles = int(vars_[2].get() or 0)
                jitter = max(0.0, min(1.0, float(vars_[3].get() or 0)))
            except ValueError:
                messagebox.showerror(APP_TITLE, "请填数字")
                return
            win.destroy()
            self._run_flap(dev, on, off, cycles, jitter)

        ttk.Button(win, text="开始", command=go).grid(row=5, column=0, padx=12, pady=12)
        ttk.Button(win, text="取消", command=win.destroy).grid(row=5, column=1, padx=12, pady=12)

    def stop_flap(self):
        if self.flap_stop is not None:
            self.flap_stop.set()
            self.ont_status_var.set("正在停止间歇封禁……（会先恢复上网）")

    def _run_flap(self, dev, on, off, cycles, jitter):
        stop = threading.Event()
        self.flap_stop = stop
        self.btn_flap.configure(text="停止间歇封禁", command=self.stop_flap)
        mac = dev["mac"]

        def logmsg(msg):
            self.queue.put((self.ont_status_var.set, (msg,)))

        def worker():
            try:
                ont = self._ensure_ont()
                fl = nc.Flapper(lambda: ont.block(mac, True),
                                lambda: ont.block(mac, False),
                                pattern=[(on, off)], cycles=cycles,
                                jitter=jitter, stop_event=stop, log=logmsg)
                stats = fl.run()
                try:
                    base = os.path.dirname(self.cfg._path) if self.cfg._path else nc.app_dir()
                    nc.log_flap_session(os.path.join(base, "flap_log.json"), {
                        "target": dev.get("name", ""), "mac": mac, "ip": dev.get("ip", ""),
                        "where": "ont", "started": "",
                        "ended": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "rounds": stats["rounds"],
                        "pattern": ["%.1f/%.1f" % (on, off)],
                        "jitter": jitter,
                        "blocked_sec": round(stats["blocked_sec"], 1),
                        "unblocked_sec": round(stats["unblocked_sec"], 1),
                    })
                except Exception:
                    pass
                self.queue.put((self._flap_done, (dev, stats)))
            except Exception as exc:  # noqa: BLE001
                err = exc
                self.queue.put((lambda: (self._flap_done(dev, None),
                                         self.ont_status_var.set("间歇封禁出错：%s" % err)), ()))

        threading.Thread(target=worker, daemon=True).start()

    def _flap_done(self, dev, stats):
        self.flap_stop = None
        self.btn_flap.configure(text="间歇封禁…", command=self.start_flap)
        if stats:
            self.ont_status_var.set("间歇封禁结束：「%s」%d 轮，已恢复上网" % (
                dev.get("name", ""), stats["rounds"]))
        self.refresh_ont()

    def set_ont_password(self):
        pw = simpledialog.askstring(
            APP_TITLE, "新的光猫管理密码（账号 %s）：" % self.cfg.ont_user, show="*")
        if not pw:
            return
        self.cfg.set_ont_password(pw)
        self.cfg["ont_host"] = self.cfg.get("ont_host") or "192.168.1.1"
        self.cfg["ont_user"] = self.cfg.get("ont_user") or "CMCCAdmin"
        self.cfg.save()
        self.ont = None
        self.ont_status_var.set("光猫密码已保存，正在验证…")
        self.refresh_ont()


def selftest():
    lines = []
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        app._ensure_router(prompt=False)
        devices = app.refresh_blocking()
        lines.append("ROUTER OK devices=%d" % len(devices))
        for d in devices:
            lines.append("  %d %s %s %s" % (d.idx, d.name, d.mac, d.state_text))
        try:
            app.cfg.ont_password  # noqa: B018
            app._ensure_ont()
            app.refresh_ont()
            ont = app._ensure_ont()
            rows = ont.devices()
            lines.append("ONT OK devices=%d" % len(rows))
            for d in rows:
                lines.append("  %d %s %s %s" % (d["idx"], d["name"], d["ip"], d["mac"]))
        except Exception as exc:  # noqa: BLE001
            lines.append("ONT SKIP/FAIL: %r" % (exc,))
        status = 0
    except Exception as exc:  # noqa: BLE001
        lines.append("SELFTEST FAIL: %r" % (exc,))
        status = 1
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
    _report(lines)
    return status


def _report(lines):
    text = "\n".join(lines)
    try:
        if sys.stdout is not None:
            print(text)
    except Exception:
        pass


def main(argv):
    if "--selftest" in argv:
        return selftest()
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
