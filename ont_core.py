# -*- coding: utf-8 -*-
"""
ont_core.py —— 中国移动光猫（华为 HSAN / webcmcc 页面）客户端

能力：登录、读 DHCP 设备表（含加密字段解密）、MAC 黑名单封禁/解封。
只对自家局域网内的 192.168.1.1 使用。

注意：光猫的"入口限速"最小粒度是 512Kbps（约 64KB/s），做不到 1KB/s 那种精细限速，
      想真限速还是得让设备走小米路由（那边 QoS 支持 1KB/s）。
"""
import random
import re
import socket

from crypto_compat import decrypt_cbc, encrypt_cbc


class OntError(Exception):
    pass


class OntClient(object):
    def __init__(self, host="192.168.1.1", user="CMCCAdmin", password=""):
        self.host = host
        self.user = user
        self.password = password
        self.token = None
        self.aes_key = b""

    # ---------------- HTTP（要处理畸形响应头 + chunked）
    def http(self, method, path, body=None, timeout=8.0):
        req = "%s %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: netctl-ont/1.0\r\nConnection: close\r\n" % (
            method, path, self.host)
        if self.token:
            req += "Token: %s\r\n" % self.token
        if body is not None:
            req += "Content-Type: application/x-www-form-urlencoded\r\nContent-Length: %d\r\n" % len(body.encode())
        req += "\r\n"
        sock = socket.create_connection((self.host, 80), timeout)
        try:
            sock.sendall(req.encode() + (body.encode() if body else b""))
            data = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        finally:
            sock.close()
        head, _, rest = data.partition(b"\r\n\r\n")
        head = head.decode("latin-1")
        m = re.search(r"(?im)^Token:\s*(.+)$", head)
        if m:
            self.token = m.group(1).strip()
        if "chunked" in head.lower():
            out = b""
            while True:
                line, _, rest = rest.partition(b"\r\n")
                if not line:
                    break
                try:
                    size = int(line.split(b";")[0], 16)
                except ValueError:
                    break
                if size == 0:
                    break
                out += rest[:size]
                rest = rest[size + 2:]
            rest = out
        return head, rest.decode("utf-8", "replace")

    # ---------------- 登录
    @staticmethod
    def _aes_enc_pwd(pwd):
        key_hex = "".join("%02x" % ord(ch) for ch in pwd)
        key_hex = (key_hex + "0" * 64)[:64]
        key = bytes.fromhex(key_hex)
        iv = bytes(random.getrandbits(8) for _ in range(16))
        return (iv + encrypt_cbc(key, iv, pwd.encode("utf-8"))).hex()

    def login(self):
        from urllib.parse import quote
        body = "mode_name=/boaform/web_login_exe&nonedata=0.5&web_login_name=%s&web_login_password=%s" % (
            quote(self.user, safe=""), self._aes_enc_pwd(self.password))
        _, text = self.http("POST", "/boaform/web_login_exe.cgi", body)
        if "success" not in text:
            raise OntError("光猫登录失败：%s" % text.strip()[:120])
        return self.token

    # ---------------- 加解密（密钥是每次请求现给的，必须先取 key 再取数据）
    def fetch_key(self):
        _, text = self.http("POST", "/boaform/web_gen_dh_key.cgi",
                            "mode_name=/boaform/web_gen_dh_key&nonedata=0.5&web_dh_pub=")
        m = re.search(r'"auc_private"\s*:\s*"([0-9A-Fa-f]+)"', text)
        if not m:
            raise OntError("拿不到 AES 密钥")
        self.aes_key = bytes.fromhex(m.group(1))
        return self.aes_key

    def decrypt(self, hexstr):
        if not hexstr:
            return ""
        if not self.aes_key:
            self.fetch_key()
        try:
            iv = bytes.fromhex(hexstr[:32])
            ct = bytes.fromhex(hexstr[32:])
            return decrypt_cbc(self.aes_key, iv, ct).decode("utf-8", "replace")
        except Exception:
            return ""

    # ---------------- 接口
    @staticmethod
    def _loads(text):
        """光猫有时吐出 :[,{...}] 这种非法空项，先修再解析。"""
        import json
        fixed = re.sub(r":\s*\[\s*,", ":[", text)
        fixed = re.sub(r",\s*,", ",", fixed)
        return json.loads(fixed)

    def call(self, name, extra="", need_key=True):
        if need_key:
            self.fetch_key()          # 数据用"取 key 那一刻"的密钥加密，所以必须先取
        body = "mode_name=/boaform/%s&nonedata=0.5%s" % (name, extra)
        _, text = self.http("POST", "/boaform/%s.cgi" % name, body)
        return text

    def get_page(self, path):
        return self.http("GET", path)[1]

    # ---------------- 设备表（DHCP 客户端）
    def devices(self):
        text = self.call("landhcp_ip_show")
        rows = []
        for row in (self._loads(text).get("data") or {}).get("landhcp_stat_list") or []:
            rows.append({
                "name": row.get("Table_landhcp_6_name_table") or "",
                "ip": self.decrypt(row.get("Table_landhcp_1_IP_table")),
                "mac": self.decrypt(row.get("Table_landhcp_2_MAC_table")).upper(),
                "type": row.get("Table_landhcp_3_DeviceType_table") or "",
                "port": row.get("Table_landhcp_4_port_table") or "",
                "lease": row.get("Table_landhcp_5_LeaseTime_table") or "",
                "wlan": row.get("Table_landhcp_11_wlan_table") or "",
                "txpkt": row.get("Table_landhcp_9_txpkt_table") or "",
                "rxpkt": row.get("Table_landhcp_10_rxpkt_table") or "",
            })
        for i, d in enumerate(rows, 1):
            d["idx"] = i
        return rows

    # ---------------- MAC 过滤（黑/白名单）
    def mac_filter(self):
        text = self.call("cmcc_mac_filter_show", need_key=False)
        data = self._loads(text).get("data") or {}
        return {
            "enabled": str(data.get("MAC_filter_enable_checkbox")) == "1",
            "mode": str(data.get("ExcludeMode_mac_select") or "0"),   # 0=黑名单 1=白名单
            "list": data.get("MAC_list") or [],
        }

    def add_mac(self, mac):
        """加入黑名单并确保过滤开启。"""
        state = self.mac_filter()
        mac = mac.upper()
        for item in state["list"]:
            if (item.get("MACAddress") or "").upper() == mac:
                return False
        if not state["enabled"] or state["mode"] != "0":
            self.call("cmcc_mac_filter_set", need_key=False,
                      extra="&mode=save&MAC_filter_enable_checkbox=1&ExcludeMode_mac_select=0")
        self.call("cmcc_mac_filter_list_add", need_key=False,
                  extra="&mode=add&MAC_filter_enable_checkbox=1&ExcludeMode_mac_select=0"
                        "&Mac_select=0&MACAddress_text=" + mac)
        return True

    def del_mac(self, mac):
        mac = mac.upper()
        state = self.mac_filter()
        ids = [str(i.get("indexid")) for i in state["list"]
               if (i.get("MACAddress") or "").upper() == mac]
        if not ids:
            return False
        self.call("cmcc_mac_filter_list_del", need_key=False,
                  extra="&mode=del&data=" + ",".join(ids))
        return True

    def is_blocked(self, mac):
        mac = mac.upper()
        return any((i.get("MACAddress") or "").upper() == mac for i in self.mac_filter()["list"])

    def block(self, mac, blocked=True):
        return self.add_mac(mac) if blocked else self.del_mac(mac)

    # ---------------- 目标解析：序号 / IP / MAC / 名字
    def resolve(self, target):
        target = str(target or "").strip()
        if not target:
            raise OntError("没指定光猫设备")
        rows = self.devices()
        if target.isdigit():
            n = int(target)
            for d in rows:
                if d["idx"] == n:
                    return d
            raise OntError("序号 %d 不存在（共 %d 台）" % (n, len(rows)))
        up = target.upper()
        for d in rows:
            if d["mac"].upper() == up or d["name"].upper() == up:
                return d
        for d in rows:
            if target.lower() in (d["name"] or "").lower():
                return d
        for d in rows:
            if d["ip"] == target:
                return d
        raise OntError("光猫上找不到设备「%s」" % target)

    # ---------------- 入口限速（只读取，供参考；最小粒度 512Kbps，不做写入）
    def ratelimit_show(self):
        return self._loads(self.call("QoS_ratelimit_show")).get("data") or {}
