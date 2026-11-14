# -*- coding: utf-8 -*-
"""
netctl 安卓版（Kivy）

打包前先在 android/ 目录里跑一次 sync_core.py，把核心模块复制过来；
然后 buildozer android debug 生成 apk。

功能与桌面版一致：
  标签1 小米路由：设备列表 / 限速(KB/s) / 取消限速 / 断网 / 恢复
  标签2 光猫    ：设备列表 / MAC 封禁 / 解封
"""
import json
import os
import sys
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.textinput import TextInput

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netctl_core as nc  # noqa: E402

TYPE_NAME = {"1": "电脑", "2": "手机", "8": "网关/路由"}


# ---------------------------------------------------------------- 小工具
def ask_password(title, hint, on_done):
    """弹窗输入密码，关掉后回调 on_done(密码或 None)。"""
    content = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(8))
    content.add_widget(Label(text=hint, size_hint_y=None, height=dp(40), font_size=dp(13)))
    ti = TextInput(password=True, multiline=False, size_hint_y=None, height=dp(40))
    content.add_widget(ti)
    row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
    popup = Popup(title=title, content=content, size_hint=(0.9, 0.45))

    def ok(_):
        popup.dismiss()
        Clock.schedule_once(lambda dt: on_done(ti.text.strip() or None), 0.05)

    def cancel(_):
        popup.dismiss()

    row.add_widget(Button(text="取消", on_release=cancel))
    row.add_widget(Button(text="确定", on_release=ok))
    content.add_widget(row)
    popup.open()


class NetctlApp(App):
    title = "netctl"

    # ------------------------------------------------------------ 生命周期
    def build(self):
        Window.clearcolor = (1, 1, 1, 1)
        self.cfg = nc.Config.load()
        # 安卓上配置统一放应用私有目录（可写、别的应用读不到）
        cfg_path = os.path.join(self.user_data_dir, "netctl.json")
        try:
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as fh:
                    self.cfg = nc.Config(json.load(fh))
        except Exception:
            pass
        self.cfg._path = cfg_path
        self.router = None
        self.ont = None
        self.selected = None
        self.selected_ont = None

        root = TabbedPanel(do_default_tab=False)
        self.tab_router = TabbedPanelItem(text="小米路由")
        self.tab_ont = TabbedPanelItem(text="光猫")
        root.add_widget(self.tab_router)
        root.add_widget(self.tab_ont)
        self.tab_router.content = self._build_router_tab()
        self.tab_ont.content = self._build_ont_tab()

        Clock.schedule_once(lambda dt: self.refresh_router(), 0.5)
        return root

    # ------------------------------------------------------------ UI 组件
    def _build_router_tab(self):
        box = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(4))
        self.router_status = Label(text="准备中…", size_hint_y=None, height=dp(56),
                                   halign="left", valign="middle", font_size=dp(13))
        self.router_status.bind(size=lambda *a: setattr(self.router_status, "text_size",
                                                        (self.router_status.width, None)))
        box.add_widget(self.router_status)

        self.router_area = GridLayout(cols=1, spacing=dp(2), size_hint_y=None)
        self.router_area.bind(minimum_height=self.router_area.setter("height"))
        sv = ScrollView()
        sv.add_widget(self.router_area)
        box.add_widget(sv)

        box.add_widget(self._action_row("router"))
        return box

    def _build_ont_tab(self):
        box = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(4))
        self.ont_status = Label(text="点「刷新」读取光猫", size_hint_y=None, height=dp(56),
                                halign="left", valign="middle", font_size=dp(13))
        self.ont_status.bind(size=lambda *a: setattr(self.ont_status, "text_size",
                                                     (self.ont_status.width, None)))
        box.add_widget(self.ont_status)

        self.ont_area = GridLayout(cols=1, spacing=dp(2), size_hint_y=None)
        self.ont_area.bind(minimum_height=self.ont_area.setter("height"))
        sv = ScrollView()
        sv.add_widget(self.ont_area)
        box.add_widget(sv)

        box.add_widget(self._action_row("ont"))
        return box

    def _action_row(self, kind):
        wrap = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(96), spacing=dp(4))
        row1 = BoxLayout(spacing=dp(4), padding=(dp(2), 0))
        row2 = BoxLayout(spacing=dp(4), padding=(dp(2), 0))
        if kind == "router":
            row1.add_widget(Button(text="刷新", on_release=lambda *a: self.refresh_router()))
            self.kb_input = TextInput(text="1", input_filter="int", multiline=False,
                                      size_hint=(0.6, 1), font_size=dp(16))
            row1.add_widget(self.kb_input)
            row1.add_widget(Button(text="限速", on_release=lambda *a: self.do_router("limit")))
            row1.add_widget(Button(text="取消限速", on_release=lambda *a: self.do_router("free")))
            row2.add_widget(Button(text="断网", on_release=lambda *a: self.do_router("block")))
            row2.add_widget(Button(text="恢复上网", on_release=lambda *a: self.do_router("unblock")))
            row2.add_widget(Button(text="设置小米密码", on_release=lambda *a: self.set_router_password()))
        else:
            row1.add_widget(Button(text="刷新", on_release=lambda *a: self.refresh_ont()))
            row1.add_widget(Button(text="封禁选中", on_release=lambda *a: self.do_ont(True)))
            row1.add_widget(Button(text="解封选中", on_release=lambda *a: self.do_ont(False)))
            row2.add_widget(Button(text="设置光猫密码", on_release=lambda *a: self.set_ont_password()))
        wrap.add_widget(row1)
        wrap.add_widget(row2)
        return wrap

    # ------------------------------------------------------------ 通用
    def _bg(self, func, done=None):
        """后台线程跑 func，结果回主线程"""

        def runner():
            try:
                result = func()
                if done:
                    Clock.schedule_once(lambda dt: done(result, None), 0)
            except Exception as exc:  # noqa: BLE001
                if done:
                    err = exc
                    Clock.schedule_once(lambda dt: done(None, err), 0)

        threading.Thread(target=runner, daemon=True).start()

    def _ensure_router(self):
        if self.router and self.router.token:
            return self.router
        if not self.cfg.password:
            raise RuntimeError("没有配置小米路由密码，请先点「设置密码」")
        self.cfg["host"] = self.cfg.get("host") or "192.168.31.1"
        self.router = nc.Router(self.cfg)
        self.router.login()
        return self.router

    def _ensure_ont(self):
        if self.ont:
            return self.ont
        from ont_core import OntClient
        if not self.cfg.ont_password:
            raise RuntimeError("没有配置光猫密码，请先点「设置光猫密码」")
        self.ont = OntClient(self.cfg.ont_host, self.cfg.ont_user, self.cfg.ont_password)
        self.ont.login()
        return self.ont

    # ------------------------------------------------------------ 小米路由
    def refresh_router(self):
        def work():
            router = self._ensure_router()
            return router.devices(), router.qos_state()

        def done(result, err):
            self.router_area.clear_widgets()
            if err:
                self.router_status.text = "出错：%s" % err
                return
            devices, state = result
            for d in devices:
                btn = Button(
                    text="%d  %s  %s  %s   限速:%s" % (
                        d.idx, d.name[:14], d.link_text, "在线" if d.online else "离线",
                        d.limit_text),
                    size_hint_y=None, height=dp(46), font_size=dp(13))
                btn.dev = d
                if not d.allowed:
                    btn.background_color = (0.8, 0.8, 0.8, 1)
                btn.bind(on_release=self._select_router)
                self.router_area.add_widget(btn)
            self.router_status.text = "设备 %d 台 ｜ QoS %s(%s) ｜ 限速中 %d 台" % (
                len(devices), "开" if state["on"] else "关", state["mode_name"], len(state["limits"]))

        self._bg(work, done)

    def _select_router(self, btn):
        self.selected = btn.dev
        self.router_status.text = "已选：%s (%s)" % (btn.dev.name, btn.dev.mac)

    def do_router(self, action):
        dev = getattr(self, "selected", None)
        if not dev:
            self.router_status.text = "先在列表里点选一台设备"
            return
        try:
            kb = max(1, int(self.kb_input.text or "1"))
        except ValueError:
            kb = 1

        def work():
            router = self._ensure_router()
            if action == "limit":
                router.set_limit(dev.mac, kb, kb)
            elif action == "free":
                router.clear_limit(dev.mac)
            elif action == "block":
                router.set_blocked(dev.mac, True)
            elif action == "unblock":
                router.set_blocked(dev.mac, False)
            return True

        def done(result, err):
            if err:
                self.router_status.text = "出错：%s" % err
            else:
                self.router_status.text = "操作完成：%s" % action
                self.refresh_router()

        self._bg(work, done)

    # ------------------------------------------------------------ 光猫
    def refresh_ont(self):
        def work():
            ont = self._ensure_ont()
            rows = ont.devices()
            blocked = {(i.get("MACAddress") or "").upper() for i in ont.mac_filter()["list"]}
            return rows, blocked

        def done(result, err):
            self.ont_area.clear_widgets()
            if err:
                self.ont_status.text = "出错：%s" % err
                return
            rows, blocked = result
            for d in rows:
                is_b = (d["mac"] or "").upper() in blocked
                btn = Button(
                    text="%d  %s  %s  %s" % (d["idx"], d["name"][:16], d["ip"] or "-",
                                             "已封禁" if is_b else "正常"),
                    size_hint_y=None, height=dp(46), font_size=dp(13))
                btn.dev = d
                if is_b:
                    btn.background_color = (0.8, 0.8, 0.8, 1)
                btn.bind(on_release=self._select_ont)
                self.ont_area.add_widget(btn)
            self.ont_status.text = "光猫设备 %d 台 ｜ 已封禁 %d 台" % (
                len(rows), sum(1 for d in rows if (d["mac"] or "").upper() in blocked))

        self._bg(work, done)

    def _select_ont(self, btn):
        self.selected_ont = btn.dev
        self.ont_status.text = "已选：%s (%s)" % (btn.dev["name"], btn.dev["mac"])

    def do_ont(self, blocked):
        dev = getattr(self, "selected_ont", None)
        if not dev:
            self.ont_status.text = "先在列表里点选一台设备"
            return

        def work():
            ont = self._ensure_ont()
            ont.block(dev["mac"], blocked)
            return True

        def done(result, err):
            if err:
                self.ont_status.text = "出错：%s" % err
            else:
                self.ont_status.text = "「%s」已%s" % (dev["name"], "封禁" if blocked else "解封")
                self.refresh_ont()

        self._bg(work, done)

    def set_ont_password(self):
        def apply(pw):
            if not pw:
                return
            self.cfg.set_ont_password(pw)
            self.cfg["ont_host"] = self.cfg.get("ont_host") or "192.168.1.1"
            self.cfg["ont_user"] = self.cfg.get("ont_user") or "CMCCAdmin"
            self.cfg.save()
            self.ont = None
            self.ont_status.text = "光猫密码已保存，正在读取…"
            self.refresh_ont()

        ask_password("光猫密码", "账号 %s（默认 CMCCAdmin）" % self.cfg.ont_user, apply)

    def set_router_password(self):
        def apply(pw):
            if not pw:
                return
            self.cfg.set_password(pw)
            self.cfg["host"] = self.cfg.get("host") or "192.168.31.1"
            self.cfg.save()
            self.router = None
            self.router_status.text = "小米路由密码已保存，正在读取…"
            self.refresh_router()

        ask_password("小米路由密码", "登录 192.168.31.1 的管理密码", apply)


if __name__ == "__main__":
    NetctlApp().run()
