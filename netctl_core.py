"""
netctl_core.py —— 小米路由器（MiWiFi 2.x / R3G）网络管控核心模块
纯标准库实现，Windows / Linux / macOS / Android(Kivy) 通用。

所有请求只发往局域网内的自家路由器，用于本人设备的带宽管理。
"""

import base64
import hashlib
import json
import os
import platform
import socket
import sys
import time
from urllib.parse import quote

SALT = "a2ffa5c9be07488bbb04a3a47d3c5f6a"
DEFAULT_HOST = "192.168.31.1"

# QoS 模式
MODE_NAMES = {
    0: "自动模式",
    1: "优先级模式",
    2: "手工限速模式",
    3: "自动模式",
    4: "游戏优先",
    5: "网页优先",
    6: "视频优先",
}


class RouterError(Exception):
    pass


# ---------------------------------------------------------------- HTTP

def _dechunk(data: bytes) -> bytes:
    out = bytearray()
    while True:
        line, _, data = data.partition(b"\r\n")
        if not line:
            break
        try:
            size = int(line.split(b";")[0].strip(), 16)
        except ValueError:
            out += line + b"\r\n"
            break
        if size == 0:
            break
        out += data[:size]
        data = data[size + 2:]
    return bytes(out)


def raw_http(host, port, method, path, body=None, timeout=8.0):
    """最小 HTTP/1.1 客户端：绕开路由器畸形的响应头 + chunked 错误响应。"""
    req = "%s %s HTTP/1.1\r\nHost: %s:%d\r\nUser-Agent: netctl/2.0\r\nConnection: close\r\n" % (
        method, path, host, port)
    payload = b""
    if body is not None:
        payload = body.encode("utf-8")
        req += ("Content-Type: application/x-www-form-urlencoded\r\n"
                "Content-Length: %d\r\n" % len(payload))
    req += "\r\n"

    sock = socket.create_connection((host, port), timeout)
    try:
        sock.sendall(req.encode("utf-8") + payload)
        chunks = []
        while True:
            piece = sock.recv(65536)
            if not piece:
                break
            chunks.append(piece)
    finally:
        sock.close()

    data = b"".join(chunks)
    head, sep, rest = data.partition(b"\r\n\r\n")
    if not sep:
        raise RouterError("路由器返回了空响应（检查地址 / 是否在同一 WiFi）")
    if b"transfer-encoding: chunked" in head.lower():
        rest = _dechunk(rest)
    return rest.decode("utf-8", "replace")


def sha1_hex(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 配置

def app_dir():
    """程序所在目录（打包成 exe 后就是 exe 旁边）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def config_paths():
    paths = [os.path.join(app_dir(), "netctl.json")]
    home = os.path.expanduser("~")
    if home and home != "~":
        paths.append(os.path.join(home, ".netctl", "netctl.json"))
    return paths


# ---- Windows DPAPI（只有 Windows 有；其它平台回退到明文，Android 靠应用沙箱保护）

def _dpapi(in_bytes, protect=True):
    import ctypes
    import ctypes.wintypes as wt

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def make(data):
        buf = ctypes.create_string_buffer(data, len(data))
        return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    blob_in = make(in_bytes)
    blob_out = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    func.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(DATA_BLOB)]
    func.restype = wt.BOOL
    if protect:
        ok = func(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    else:
        ok = func(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI 调用失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def can_dpapi():
    return sys.platform == "win32"


def protect_secret(password: str) -> dict:
    """返回要写进配置的字段。Windows 用 DPAPI 加密，其它平台存明文（Android 应用私有目录受沙箱保护）。"""
    if can_dpapi():
        try:
            enc = _dpapi(password.encode("utf-8"), protect=True)
            return {"password_dpapi": base64.b64encode(enc).decode("ascii")}
        except Exception:
            pass
    return {"password": password}


def unprotect_secret(cfg: dict) -> str:
    if cfg.get("password"):
        return cfg["password"]
    return unprotect_named(cfg, "password", "password_dpapi")


def unprotect_named(cfg: dict, plain_key: str, dpapi_key: str) -> str:
    if cfg.get(plain_key):
        return cfg[plain_key]
    blob = cfg.get(dpapi_key)
    if blob:
        if not can_dpapi():
            raise RouterError("这个密码是用 Windows DPAPI 加密的，当前平台解不开。")
        raw = _dpapi(base64.b64decode(blob), protect=False)
        return raw.decode("utf-8")
    return ""


class Config(dict):
    """简单配置：host / self_mac / 密码 / 设备别名。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._path = None

    @classmethod
    def load(cls):
        for path in config_paths():
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        cfg = cls(json.load(fh))
                    cfg._path = path
                    return cfg
                except Exception:
                    continue
        cfg = cls(host=DEFAULT_HOST, self_mac="", profiles={})
        cfg._path = config_paths()[0]
        return cfg

    def save(self):
        path = self._path or config_paths()[0]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        self._path = path

    # ---- 便捷属性
    @property
    def host(self):
        return self.get("host") or DEFAULT_HOST

    @property
    def self_mac(self):
        return (self.get("self_mac") or "").upper()

    @property
    def password(self):
        return unprotect_secret(self)

    def set_password(self, password):
        self.pop("password", None)
        self.pop("password_dpapi", None)
        self.update(protect_secret(password))

    # ---- 光猫（192.168.1.1）
    @property
    def ont_host(self):
        return self.get("ont_host") or "192.168.1.1"

    @property
    def ont_user(self):
        return self.get("ont_user") or "CMCCAdmin"

    @property
    def ont_password(self):
        return unprotect_named(self, "ont_password", "ont_password_dpapi")

    def set_ont_password(self, password):
        self.pop("ont_password", None)
        self.pop("ont_password_dpapi", None)
        if can_dpapi():
            try:
                enc = _dpapi(password.encode("utf-8"), protect=True)
                self["ont_password_dpapi"] = base64.b64encode(enc).decode("ascii")
                return
            except Exception:
                pass
        self["ont_password"] = password

    # ---- 别名：值可以是 MAC，也可以是 "name:关键字"（手机换随机 MAC 时用）
    def profile_value(self, name):
        profiles = self.get("profiles") or {}
        if name in profiles:
            return profiles[name] or ""
        return None


# ---------------------------------------------------------------- 设备行

class Device(object):
    __slots__ = ("idx", "name", "mac", "ip", "online", "uptime", "up_bps", "down_bps",
                 "limit_up", "limit_down", "allowed", "is_self", "link")

    def __init__(self, **kw):
        for key in self.__slots__:
            setattr(self, key, kw.get(key))

    @property
    def link_text(self):
        return self.link or "-"

    @property
    def uptime_text(self):
        s = int(self.uptime or 0)
        if s <= 0:
            return "-"
        if s >= 86400:
            return "%d天%d小时" % (s // 86400, (s % 86400) // 3600)
        if s >= 3600:
            return "%d小时%d分" % (s // 3600, (s % 3600) // 60)
        if s >= 60:
            return "%d分%d秒" % (s // 60, s % 60)
        return "%d秒" % s

    @property
    def up_text(self):
        return _rate_text(self.up_bps)

    @property
    def down_text(self):
        return _rate_text(self.down_bps)

    @property
    def limit_text(self):
        if (self.limit_up or 0) > 0 or (self.limit_down or 0) > 0:
            return "%s/%s KB/s" % (self.limit_up, self.limit_down)
        return "无"

    @property
    def state_text(self):
        parts = ["正常" if self.allowed else "禁止上网"]
        if (self.limit_up or 0) > 0 or (self.limit_down or 0) > 0:
            parts.append("限速中")
        if self.is_self:
            parts.append("(本机)")
        return " / ".join(parts)

    def __repr__(self):
        return "<Device %s %s>" % (self.idx, self.name)


def _link_text(dev=None, dtype=None, port=None):
    """判断接入方式：WiFi 5G / WiFi 2.4G / 有线。只在路由器返回了这些字段时才知道。"""
    d = str(dev or "").lower()
    t = str(dtype or "").lower()
    if d.startswith("wl0"):
        return "WiFi 5G"
    if d.startswith("wl1"):
        return "WiFi 2.4G"
    if d.startswith(("eth", "br", "lan", "usb")):
        return "有线"
    if t == "wifi":
        return "WiFi 5G" if str(port) == "2" else ("WiFi 2.4G" if str(port) == "1" else "WiFi")
    if t in ("line", "lan", "ethernet", "wire"):
        return "有线"
    if str(port) == "1":
        return "WiFi 2.4G"
    if str(port) == "2":
        return "WiFi 5G"
    return ""


def _rate_text(bps):
    try:
        v = float(bps or 0)
    except (TypeError, ValueError):
        return "0"
    if v >= 1048576:
        return "%.1f MB/s" % (v / 1048576)
    if v >= 1024:
        return "%.0f KB/s" % (v / 1024)
    return "%.0f B/s" % v


# ---------------------------------------------------------------- 路由器

class Router(object):
    def __init__(self, config: Config, timeout=8.0):
        self.cfg = config
        self.host = config.host
        self.timeout = timeout
        self.token = None

    # ---- 登录
    def _nonce_candidates(self):
        utc = int(time.time())
        # 路由器校验 nonce 时间戳时用的是"本地时间当成 epoch"的算法（UTC+8 就是 +8 小时），
        # 所以这里把几种可能都试一遍。
        try:
            local_as_epoch = utc - int(time.timezone)
        except Exception:
            local_as_epoch = utc
        cands = [local_as_epoch, utc, utc - 28800, utc + 28800, utc - 3600, utc + 3600]
        seen, out = set(), []
        for c in cands:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def login(self):
        password = self.cfg.password
        if not password:
            raise RouterError("还没有配置路由器管理密码")
        inner = sha1_hex(password + SALT)
        last = "无响应"
        for ts in self._nonce_candidates():
            nonce = "0_%s_%d_%d" % (self.cfg.self_mac or "00:00:00:00:00:00", ts,
                                    int(time.time() * 1000) % 9999)
            outer = sha1_hex(nonce + inner)
            body = "username=admin&password=%s&logtype=2&nonce=%s" % (outer, quote(nonce, safe=""))
            try:
                text = raw_http(self.host, 80, "POST", "/cgi-bin/luci/api/xqsystem/login", body,
                                self.timeout)
            except OSError as exc:
                raise RouterError("连不上路由器：%s" % exc)
            try:
                data = json.loads(text)
            except ValueError:
                last = "返回无法解析：%r" % text[:120]
                continue
            if data.get("code") == 0 and data.get("token"):
                self.token = data["token"]
                return self.token
            last = "code=%s %s" % (data.get("code"), data.get("msg", ""))
            if data.get("code") != 1582:
                break
        raise RouterError("登录失败（%s）。密码可能被改过，用『设置密码』改一下。" % last)

    # ---- 通用接口
    def api(self, path, method="GET", body=None):
        if not self.token:
            self.login()
        url = "/cgi-bin/luci/;stok=%s/api/%s" % (self.token, path)
        text = raw_http(self.host, 80, method, url, body, self.timeout)
        try:
            data = json.loads(text)
        except ValueError:
            raise RouterError("接口 %s 返回异常：%r" % (path, text[:150]))
        if data.get("code") not in (0, None):
            # token 过期就重登一次
            if data.get("code") in (401,):
                self.token = None
                self.login()
                return self.api(path, method, body)
            raise RouterError("接口 %s 出错：code=%s %s" % (path, data.get("code"),
                                                          data.get("msg", "")))
        return data

    # ---- 数据
    def qos_info(self):
        return self.api("misystem/qos_info")

    def devices(self, with_link=False):
        """设备表。with_link=True 时，如果 QoS 没开就临时开一下读"接入方式"（有线/5G/2.4G）再关掉。"""
        raw = self.api("misystem/devicelist").get("list") or []
        qos = self.qos_info()
        restore_off = False
        if with_link and not (qos.get("list") or []):
            try:
                if int((qos.get("status") or {}).get("on") or 0) != 1:
                    self.api("misystem/qos_switch?on=1")
                    restore_off = True
                    qos = self.qos_info()
            except RouterError:
                pass
        qmap = {}
        for item in qos.get("list") or []:
            qmap[item.get("mac")] = item

        rows = []
        for d in raw:
            mac = d.get("mac") or ""
            q = qmap.get(mac) or {}
            stat = q.get("statistics") or d.get("statistics") or {}
            ips = d.get("ip") or []
            ip = ips[0].get("ip", "") if ips else ""
            qos_info = q.get("qos") or {}
            rows.append(Device(
                idx=0,
                name=d.get("name") or d.get("oname") or mac,
                mac=mac,
                ip=ip,
                online=int(d.get("online") or 0) == 1,
                uptime=int(stat.get("online") or 0),
                up_bps=float(stat.get("upspeed") or 0),
                down_bps=float(stat.get("downspeed") or 0),
                limit_up=int(qos_info.get("upmax") or 0),
                limit_down=int(qos_info.get("downmax") or 0),
                allowed=int((d.get("authority") or {}).get("wan", 1)) == 1,
                is_self=mac.upper() == self.cfg.self_mac,
                link=_link_text(stat.get("dev"), q.get("type") or d.get("type"),
                                q.get("port") or d.get("port")),
            ))
        rows.sort(key=lambda dev: (not dev.online, (dev.name or "").lower()))
        for i, dev in enumerate(rows, 1):
            dev.idx = i
        if restore_off:
            try:
                self.api("misystem/qos_switch?on=0")
            except RouterError:
                pass
        return rows

    def qos_state(self):
        info = self.qos_info()
        status = info.get("status") or {}
        return {
            "on": int(status.get("on") or 0) == 1,
            "mode": int(status.get("mode") or 0),
            "mode_name": MODE_NAMES.get(int(status.get("mode") or 0), "?"),
            "limits": [d for d in (info.get("list") or [])
                       if int((d.get("qos") or {}).get("upmax") or 0) > 0
                       or int((d.get("qos") or {}).get("downmax") or 0) > 0],
        }

    # ---- 操作
    def _ensure_qos(self):
        info = self.qos_info()
        status = info.get("status") or {}
        if int(status.get("on") or 0) != 1:
            self.api("misystem/qos_switch?on=1")
        if int(status.get("mode") or 0) != 2:
            self.api("misystem/qos_mode?mode=2")

    def set_limit(self, mac, up_kb, down_kb):
        up_kb, down_kb = int(up_kb), int(down_kb)
        if up_kb < 0 or down_kb < 0:
            raise ValueError("限速值不能为负（0 表示不限速）")
        self._ensure_qos()
        info = self.qos_info()
        limits = []
        for d in info.get("list") or []:
            if (d.get("mac") or "").upper() == mac.upper():
                continue
            q = d.get("qos") or {}
            u, dn = int(q.get("upmax") or 0), int(q.get("downmax") or 0)
            if u > 0 or dn > 0:
                limits.append({"mac": d["mac"], "maxup": u, "maxdown": dn})
        limits.append({"mac": mac, "maxup": up_kb, "maxdown": down_kb})
        payload = "data=" + quote(json.dumps(limits, separators=(",", ":")), safe="")
        self.api("misystem/qos_limits", "POST", payload)

    def clear_limit(self, mac):
        self.api("misystem/qos_offlimit?mac=" + quote(mac, safe=""))
        state = self.qos_state()
        if not state["limits"]:
            # 没有别的设备被限速了，恢复原状
            self.api("misystem/qos_mode?mode=3")
            self.api("misystem/qos_switch?on=0")
            return True
        return False

    def set_blocked(self, mac, blocked):
        self.api("xqsystem/set_mac_filter?mac=%s&wan=%d" % (quote(mac, safe=""), 0 if blocked else 1))

    def qos_switch(self, on):
        self.api("misystem/qos_switch?on=%d" % (1 if on else 0))
        if on:
            self.api("misystem/qos_mode?mode=2")

    def qos_auto(self):
        self.api("misystem/qos_switch?on=1")
        self.api("misystem/qos_mode?mode=3")

    # ---- 目标解析
    def resolve(self, target):
        target = str(target or "").strip()
        if not target:
            raise RouterError("没有指定设备")
        # 1) 配置别名
        val = self.cfg.profile_value(target)
        if val:
            if val.lower().startswith("name:"):
                kw = val[5:].strip().lower()
                for dev in self.devices():
                    if kw in (dev.name or "").lower():
                        return dev
                raise RouterError("别名「%s」按名称关键字「%s」没找到设备" % (target, kw))
            target = val
        # 2) 序号
        if target.isdigit():
            rows = self.devices()
            n = int(target)
            for dev in rows:
                if dev.idx == n:
                    return dev
            raise RouterError("序号 %d 不存在（共 %d 台）" % (n, len(rows)))
        # 3) MAC / 名称 / IP
        up = target.upper()
        rows = self.devices()
        for dev in rows:
            if (dev.mac or "").upper() == up:
                return dev
        for dev in rows:
            if target.lower() in (dev.name or "").lower():
                return dev
        for dev in rows:
            if dev.ip == target:
                return dev
        raise RouterError("找不到设备「%s」" % target)


# ---------------------------------------------------------------- 便捷函数

def connect():
    """读取配置并登录，返回 Router。没配密码时抛 RouterError。"""
    cfg = Config.load()
    if not cfg.password:
        raise RouterError("还没有配置路由器管理密码（先用【设置密码】录入）")
    router = Router(cfg)
    router.login()
    return router


def detect_self_mac(host=DEFAULT_HOST):
    """通过 UDP 连接拿本机出口 IP，再从设备表里对上 MAC。"""
    try:
        cfg = Config.load()
        if not cfg.password:
            return ""
        rows = Router(cfg).devices()
    except Exception:
        return ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((host, 80))
        my_ip = s.getsockname()[0]
        s.close()
    except Exception:
        return ""
    for dev in rows:
        if dev.ip == my_ip:
            return dev.mac
    return ""
