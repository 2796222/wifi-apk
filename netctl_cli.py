# -*- coding: utf-8 -*-
"""
netctl_cli.py —— 命令行版路由器管控（傻瓜菜单）

用法：
    python netctl_cli.py                交互式菜单（推荐，直接敲数字）
    python netctl_cli.py list           列出设备
    python netctl_cli.py limit 4 1      第 4 台限速 1 KB/s
    python netctl_cli.py limit Xiaomi-13 1
    python netctl_cli.py free 4         取消第 4 台限速
    python netctl_cli.py block 4        禁止第 4 台上网
    python netctl_cli.py unblock 4      恢复上网
    python netctl_cli.py all 1          全部设备限速
    python netctl_cli.py qos off|manual|auto
    python netctl_cli.py setpass        修改路由器管理密码
    python netctl_cli.py whoami         自动识别本机 MAC

    # 光猫（插网线的设备在 192.168.1.1 那边）
    python netctl_cli.py ont            光猫设备列表（附封禁记录对照）
    python netctl_cli.py ont-block 2    光猫上封禁（会写本地记录）
    python netctl_cli.py ont-unblock 2  解封（记录里标解封时间）
    python netctl_cli.py ont-history    看封禁记录：谁被封过、现在还在不在黑名单
    python netctl_cli.py ont-reapply    被人解封/光猫被重置后，按记录一键封回去
    python netctl_cli.py setontpass     设置光猫管理密码

    # 间歇封禁（看起来像网络不稳定）
    python netctl_cli.py flap 2                封 5 秒 / 解 4 秒，一直循环（Ctrl+C 停）
    python netctl_cli.py flap 2 --on 5 --off 4 --cycles 10
    python netctl_cli.py flap 2 --pattern "5/4,6/5,7/6" --jitter 0.3
    python netctl_cli.py flap-log              看间歇封禁历史
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netctl_core as nc

BANNER = "=========== netctl 路由器管控 ==========="


def init_console():
    """Windows 控制台中文不乱码：控制台切 UTF-8 并把 stdout 设为 UTF-8。"""
    if sys.platform != "win32":
        return
    try:
        if sys.stdout and sys.stdout.isatty():
            os.system("chcp 65001 >nul")
        for stream in (sys.stdout, sys.stderr):
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def ensure_password(cfg):
    if cfg.password:
        return True
    print("第一次使用，需要录入路由器管理密码（就是登录 192.168.31.1 的密码）。")
    import getpass
    pw = getpass.getpass("管理密码（输入不显示）: ")
    if not pw:
        print("没有输入，已退出。")
        return False
    cfg.set_password(pw)
    cfg["host"] = cfg.get("host") or nc.DEFAULT_HOST
    if not cfg.get("self_mac"):
        mac = nc.detect_self_mac(cfg.host)
        if mac:
            cfg["self_mac"] = mac
            print("已自动识别本机 MAC:", mac)
    cfg.save()
    print("已保存到", cfg._path)
    return True


def print_devices(devs):
    if not devs:
        print("（没有设备）")
        return
    print("")
    print("%-4s %-26s %-18s %-16s %-4s %-9s %-11s %-15s %-11s %s" % (
        "序号", "设备名称", "MAC", "IP", "在线", "接入", "在线时长", "实时(上/下)", "限速", "状态"))
    print("-" * 136)
    for d in devs:
        print("%-5s %-26s %-18s %-16s %-5s %-9s %-11s %-15s %-11s %s" % (
            d.idx, (d.name or "")[:26], d.mac, d.ip or "-", "是" if d.online else "否",
            d.link_text, d.uptime_text, "%s/%s" % (d.up_text, d.down_text),
            d.limit_text, d.state_text))
    if any(not d.link for d in devs):
        print("")
        print("提示：接入方式显示“-”是因为路由器只在 QoS 开启时才返回该字段。")
        print("      想看有线/WiFi，运行：python netctl_cli.py list --link （临时开一下 QoS 再关回去）")
    print("")


def parse_target_and_value(text):
    """允许把「序号 速度」写在一起，比如 "4 1"。返回 (target, value|None)。"""
    parts = str(text or "").replace("，", ",").split()
    if len(parts) >= 2 and parts[1].replace(".", "", 1).isdigit():
        return parts[0], parts[1]
    return (parts[0] if parts else ""), None


def cmd_limit(router, target=None, value=None):
    devs = router.devices()
    print_devices(devs)
    if target is None:
        target, value = parse_target_and_value(input("输入设备序号或名称（也可以直接输入「4 1」）: "))
    dev = router.resolve(target)
    if value is None:
        value = input("限速多少 KB/s（回车 = 1）: ").strip() or "1"
    try:
        kb = float(value)
    except ValueError:
        print("限速值要是数字，比如 1")
        return
    kb = max(0, int(round(kb)))
    router.set_limit(dev.mac, kb, kb)
    print("已把「%s」限速为 上传 %d / 下载 %d KB/s" % (dev.name, kb, kb))


def cmd_free(router, target=None):
    if target is None:
        print_devices(router.devices())
        target = input("要取消哪台设备的限速（序号或名称）: ")
    dev = router.resolve(target)
    restored = router.clear_limit(dev.mac)
    print("已取消「%s」的限速%s" % (dev.name, "，QoS 也已恢复关闭" if restored else ""))


def cmd_block(router, target=None, blocked=True):
    if target is None:
        print_devices(router.devices())
        target = input("要%s哪台设备（序号或名称）: " % ("断网" if blocked else "恢复"))
    dev = router.resolve(target)
    router.set_blocked(dev.mac, blocked)
    print("「%s」已%s" % (dev.name, "禁止上网" if blocked else "恢复上网"))


def cmd_all(router, kb):
    kb = int(kb)
    devs = router.devices()
    for dev in devs:
        router.set_limit(dev.mac, kb, kb)
    print("已对 %d 台设备限速 %d KB/s（包括你自己这台）" % (len(devs), kb))


def cmd_status(router):
    st = router.qos_state()
    print("QoS: %s    模式: %s    被限速设备: %d 台" % (
        "开" if st["on"] else "关", st["mode_name"], len(st["limits"])))
    for d in st["limits"]:
        print("  %-28s %s  %s/%s KB/s" % (
            d.get("name", ""), d.get("mac", ""),
            (d.get("qos") or {}).get("upmax"), (d.get("qos") or {}).get("downmax")))


def cmd_setpass(cfg):
    import getpass
    pw = getpass.getpass("新的路由器管理密码（输入不显示）: ")
    if not pw:
        print("已取消")
        return
    cfg.set_password(pw)
    cfg.save()
    nc.Router(cfg).login()
    print("密码已更新并验证通过。")


# ---------------------------------------------------------------- 光猫

def new_ont(cfg):
    from ont_core import OntClient
    if not cfg.ont_password:
        raise nc.RouterError("还没有配置光猫管理密码，先运行：python netctl_cli.py setontpass")
    ont = OntClient(cfg.ont_host, cfg.ont_user, cfg.ont_password)
    try:
        ont.login()
    except Exception as exc:
        msg = str(exc)
        if "invalid_password" in msg:
            raise nc.RouterError(
                "光猫密码不对（invalid_password）。\n"
                "  可能原因：你改过光猫密码、或者光猫被恢复出厂（背面的默认密码）。\n"
                "  处理：用当前密码重新录入 → python netctl_cli.py setontpass")
        raise
    return ont


TYPE_NAME = {"1": "电脑", "2": "手机", "8": "网关/路由"}


def _print_ont_history_section(current=None):
    """打印本地封禁记录，并与设备当前黑名单对照。current=None 表示没连上、只显示本地记录。"""
    hist = nc.BlockHistory()
    entries = hist.entries("ont")
    open_cnt = len(hist.open_entries("ont"))
    print("封禁记录：历史 %d 条，仍处于封禁状态 %d 条（记录文件 %s）" % (
        len(entries), open_cnt, hist.path))
    if current is None:
        print("（本次没连上光猫，只显示本地记录；核对状态请恢复连接后重试）")
        return
    alive, gone = hist.diff(current, where="ont")
    if gone:
        print("⚠ 有 %d 条记录本应是封禁状态，但光猫黑名单里已经没有它们：" % len(gone))
        for e in gone:
            print("   - %-18s %-16s 封禁于 %s" % (
                e["mac"], e.get("name") or "", e.get("blocked_at") or "（后台手动/未知）"))
        print("   （可能被人手动解封、或光猫被重置；一键封回去：python netctl_cli.py ont-reapply）")
    elif open_cnt:
        print("✔ 记录里的封禁都还在光猫黑名单里，没有被改动")


def cmd_ont_list(cfg):
    ont = None
    rows = []
    blocked = None
    try:
        ont = new_ont(cfg)
        rows = ont.devices()
        try:
            blocked = {(i.get("MACAddress") or "").upper() for i in ont.mac_filter()["list"]}
        except Exception:
            blocked = None
    except Exception as exc:  # noqa: BLE001
        print("[警告] 连不上光猫：%s" % exc)
        print("       下面的封禁记录是本地保存的，仍然能看（恢复连接后可自动核对）")
    if rows:
        print("")
        print("%-4s %-22s %-15s %-18s %-7s %-10s %-8s %s" % (
            "序号", "名称", "IP", "MAC", "接入", "类型", "端口", "封禁"))
        print("-" * 110)
        for d in rows:
            link = "有线" if str(d["wlan"]) != "1" else "WiFi"
            is_blocked = blocked is not None and d["mac"].upper() in blocked
            print("%-5s %-22s %-15s %-18s %-7s %-10s %-8s %s" % (
                d["idx"], d["name"][:22], d["ip"] or "-", d["mac"] or "-", link,
                TYPE_NAME.get(str(d["type"]), "类型" + str(d["type"])),
                d["port"], "已封禁" if is_blocked else "正常"))
    print("")
    # 把光猫上"不是本程序封的"（比如你直接在后台手动加的）也同步进本地记录
    if blocked is not None:
        added = nc.BlockHistory().sync_from_device(blocked, rows, where="ont")
        if added:
            print("已从光猫同步 %d 条现有黑名单到本地记录" % added)
    _print_ont_history_section(blocked)
    print("")


def cmd_ont_block(cfg, target=None, blocked=True):
    ont = new_ont(cfg)
    rows = ont.devices()
    if target is None:
        cmd_ont_list(cfg)
        target = input("要%s哪台设备（序号/IP/名称）: " % ("封禁" if blocked else "解封"))
    dev = ont.resolve(target)
    changed = ont.block(dev["mac"], blocked)
    hist = nc.BlockHistory()
    if blocked:
        hist.record_block(dev["mac"], dev["name"], dev["ip"], where="ont")
    else:
        hist.record_unblock(dev["mac"], where="ont")
    print("光猫上「%s (%s)」已%s%s" % (
        dev["name"], dev["mac"], "封禁" if blocked else "解封",
        "" if changed else "（本来就是该状态）"))
    print("已写入本地封禁记录：", hist.path)


def cmd_ont_history(cfg=None):
    """显示本地封禁记录，并对照光猫当前黑名单。"""
    hist = nc.BlockHistory()
    entries = hist.entries("ont")
    current = set()
    note = ""
    if cfg is not None:
        try:
            ont = new_ont(cfg)
            current = {(i.get("MACAddress") or "").upper() for i in ont.mac_filter()["list"]}
        except Exception as exc:
            note = "（连不上光猫，只显示本地记录：%s）" % exc
    if not entries:
        print("还没有任何封禁记录。")
        return
    print("本地记录文件：", hist.path)
    if note:
        print(note)
    print("")
    print("%-18s %-20s %-15s %-20s %-20s %s" % (
        "MAC", "名称", "IP", "封禁时间", "解封时间", "当前"))
    print("-" * 120)
    for e in entries:
        if e.get("unblocked_at"):
            state = "已解封"
        elif current and e["mac"] not in current:
            state = "⚠ 记录在、黑名单里没有"
        elif current:
            state = "封禁生效中"
        else:
            state = "封禁中（未核对）"
        print("%-18s %-20s %-15s %-20s %-20s %s" % (
            e["mac"], (e.get("name") or "")[:20], e.get("ip") or "-",
            e.get("blocked_at") or "（后台手动/未知）", e.get("unblocked_at") or "-", state))
    print("")


def cmd_ont_reapply(cfg):
    """把"记录里还处于封禁状态、但设备上已经没有"的地址重新封回去。"""
    try:
        ont = new_ont(cfg)
        current = {(i.get("MACAddress") or "").upper() for i in ont.mac_filter()["list"]}
    except Exception as exc:
        print("[错误] 连不上光猫：", exc)
        return
    hist = nc.BlockHistory()
    alive, gone = hist.diff(current, where="ont")
    if not gone:
        print("记录里的封禁都还在光猫上，不需要恢复。")
        return
    for e in gone:
        ont.block(e["mac"], True)
        print("已重新封禁：%s %s" % (e["mac"], e.get("name") or ""))
    print("完成，共恢复 %d 条。" % len(gone))


def cmd_set_ont_pass(cfg):
    import getpass
    pw = getpass.getpass("光猫管理密码（输入不显示，默认账号 CMCCAdmin）: ")
    if not pw:
        print("已取消")
        return
    host = input("光猫地址（回车 = %s）: " % cfg.ont_host).strip() or cfg.ont_host
    cfg["ont_host"] = host
    cfg["ont_user"] = cfg.get("ont_user") or "CMCCAdmin"
    cfg.set_ont_password(pw)
    cfg.save()
    new_ont(cfg)
    print("光猫密码已保存并验证通过。")


# ---------------------------------------------------------------- 间歇封禁

FLAP_USAGE = """用法：
  python netctl_cli.py flap <设备> [--on 5] [--off 4] [--cycles 10] [--pattern "5/4,6/5"] [--jitter 0.3]

  设备：光猫或小米路由上的设备（序号/IP/名称/MAC 都行，先找光猫再找小米）
  --on SEC      封多少秒（默认 5）
  --off SEC     解多少秒（默认 4）
  --cycles N    循环多少轮（默认 0 = 一直循环，Ctrl+C 停止）
  --pattern     多组节奏，如 "5/4,6/5,7/6"（优先于 --on/--off）
  --jitter X    时间随机抖动比例（0.3 = ±30%，更像"网络不稳定"）
停掉（Ctrl+C）后会自动恢复成"能上网"，并把这次会话记到 flap_log.json。
"""


def _parse_flap_opts(args):
    opts = {"on": 5.0, "off": 4.0, "cycles": 0, "pattern": None, "jitter": 0.0}
    i = 0
    while i < len(args):
        a = args[i]
        try:
            if a == "--on" and i + 1 < len(args):
                opts["on"] = float(args[i + 1]); i += 2; continue
            if a == "--off" and i + 1 < len(args):
                opts["off"] = float(args[i + 1]); i += 2; continue
            if a == "--cycles" and i + 1 < len(args):
                opts["cycles"] = int(args[i + 1]); i += 2; continue
            if a == "--pattern" and i + 1 < len(args):
                opts["pattern"] = args[i + 1]; i += 2; continue
            if a == "--jitter" and i + 1 < len(args):
                opts["jitter"] = float(args[i + 1]); i += 2; continue
        except ValueError:
            raise SystemExit("参数值不对：%s" % a)
        raise SystemExit("没看懂的参数：%s\n%s" % (a, FLAP_USAGE))
    return opts


def _flap_log_path(cfg):
    base = os.path.dirname(cfg._path) if cfg._path else "."
    return os.path.join(base, "flap_log.json")


def cmd_flap(cfg, target=None, opts=None):
    import threading
    import time as _time
    opts = opts or {}
    pattern = nc.parse_pattern(opts.get("pattern")) if opts.get("pattern") else [
        (opts.get("on", 5.0), opts.get("off", 4.0))]

    # 先找光猫，再找小米路由
    where = None
    ont = None
    router = None
    mac = name = ip = ""
    try:
        ont = new_ont(cfg)
        if target is None:
            cmd_ont_list(cfg)
            target = input("要对哪台设备做间歇封禁（序号/IP/名称）: ")
        dev = ont.resolve(target)
        mac, name, ip, where = dev["mac"], dev["name"], dev.get("ip", ""), "ont"
    except Exception as exc:  # noqa: BLE001
        if target is None:
            raise
        try:
            router = nc.connect()
            dev = router.resolve(target)
            mac, name, ip, where = dev.mac, dev.name, dev.ip, "router"
        except Exception:
            raise SystemExit("光猫和小米路由上都找不到「%s」（光猫报错：%s）" % (target, exc))

    print("目标：%s（%s，%s）｜节奏：%s｜轮数：%s｜抖动：%.0f%%" % (
        name, mac, where, ", ".join("%.0f/%.0f" % p for p in pattern),
        opts.get("cycles") or "一直循环", opts.get("jitter", 0) * 100))

    if where == "ont":
        block_fn = lambda: ont.block(mac, True)
        unblock_fn = lambda: ont.block(mac, False)
    else:
        block_fn = lambda: router.set_blocked(mac, True)
        unblock_fn = lambda: router.set_blocked(mac, False)

    stop = threading.Event()
    flapper = nc.Flapper(block_fn, unblock_fn, pattern=pattern,
                         cycles=opts.get("cycles", 0), jitter=opts.get("jitter", 0),
                         stop_event=stop, log=lambda m: print("  " + m, flush=True))
    started = _time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        stats = flapper.run()
    except KeyboardInterrupt:
        stop.set()
        stats = flapper.stats
    ended = _time.strftime("%Y-%m-%d %H:%M:%S")
    print("结束：%d 轮，封 %0.f 秒 / 解 %0.f 秒，当前已解封（能上网）" % (
        stats["rounds"], stats["blocked_sec"], stats["unblocked_sec"]))
    nc.log_flap_session(_flap_log_path(cfg), {
        "target": name, "mac": mac, "ip": ip, "where": where,
        "started": started, "ended": ended, "rounds": stats["rounds"],
        "pattern": ["%.1f/%.1f" % p for p in pattern],
        "jitter": opts.get("jitter", 0),
        "blocked_sec": round(stats["blocked_sec"], 1),
        "unblocked_sec": round(stats["unblocked_sec"], 1),
    })


def cmd_flap_log(cfg):
    path = _flap_log_path(cfg)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        print("还没有间歇封禁记录。")
        return
    print("记录文件：", path)
    print("%-20s %-20s %-18s %-6s %-12s %s" % ("目标", "开始", "结束", "轮数", "节奏", "MAC"))
    print("-" * 110)
    for e in data[-30:]:
        print("%-20s %-20s %-18s %-6s %-12s %s" % (
            (e.get("target") or "")[:20], e.get("started") or "-", e.get("ended") or "-",
            e.get("rounds"), ",".join(e.get("pattern") or []), e.get("mac") or ""))


def menu(router, cfg):
    while True:
        print("")
        print(BANNER)
        print(" 1. 查看设备")
        print(" 2. 给某台设备限速")
        print(" 3. 取消某台设备的限速")
        print(" 4. 禁止某台设备上网（断网）")
        print(" 5. 恢复某台设备上网")
        print(" 6. 给所有设备限速")
        print(" 7. 暂停/恢复全部限速")
        print(" 8. 查看当前状态")
        print(" 9. 修改管理密码")
        print("10. 查看光猫设备（192.168.1.1，插网线的设备在那边）")
        print("11. 光猫封禁 / 解封设备")
        print("12. 设置光猫管理密码")
        print("13. 光猫封禁记录（含“可能被解封/被重置”检测）")
        print("14. 按记录恢复封禁（被解封后一键封回去）")
        print("15. 间歇封禁（封几秒/解几秒，循环，看起来像网络不稳定）")
        print("16. 间歇封禁记录")
        print(" 0. 退出")
        choice = input("请输入数字后回车: ").strip()
        try:
            if choice == "1":
                print_devices(router.devices())
            elif choice == "2":
                cmd_limit(router)
            elif choice == "3":
                cmd_free(router)
            elif choice == "4":
                cmd_block(router, blocked=True)
            elif choice == "5":
                cmd_block(router, blocked=False)
            elif choice == "6":
                kb = input("所有设备限速多少 KB/s（回车=1）: ").strip() or "1"
                cmd_all(router, kb)
            elif choice == "7":
                st = router.qos_state()
                if st["on"] and st["limits"]:
                    router.qos_switch(False)
                    print("已暂停全部限速（限速表还留着）")
                else:
                    router.qos_switch(True)
                    print("已恢复手工限速模式")
            elif choice == "8":
                cmd_status(router)
            elif choice == "9":
                cmd_setpass(cfg)
                router.cfg = cfg
            elif choice == "10":
                cmd_ont_list(cfg)
            elif choice == "11":
                a = input("1=封禁  2=解封 （默认 1）: ").strip() or "1"
                cmd_ont_block(cfg, blocked=(a != "2"))
            elif choice == "12":
                cmd_set_ont_pass(cfg)
            elif choice == "13":
                cmd_ont_history(cfg)
            elif choice == "14":
                cmd_ont_reapply(cfg)
            elif choice == "15":
                print(FLAP_USAGE)
                tgt = input("设备（序号/IP/名称，回车取消）: ").strip()
                if tgt:
                    a = input("封多少秒（回车=5）: ").strip() or "5"
                    b = input("解多少秒（回车=4）: ").strip() or "4"
                    n = input("循环几轮（回车=一直循环，Ctrl+C 停）: ").strip() or "0"
                    cmd_flap(cfg, tgt, {"on": float(a), "off": float(b),
                                        "cycles": int(n or 0), "jitter": 0.2})
            elif choice == "16":
                cmd_flap_log(cfg)
            elif choice == "0":
                return
        except nc.RouterError as exc:
            print("[错误]", exc)
        except Exception as exc:  # noqa: BLE001
            print("[错误]", exc)


def main(argv):
    init_console()
    cfg = nc.Config.load()
    args = argv[1:]
    # 光猫相关命令不需要先登录小米路由
    if args:
        cmd0 = args[0].lower()
        if cmd0 in ("setontpass", "setont"):
            cmd_set_ont_pass(cfg)
            return 0
        if cmd0 in ("ont", "ont-list", "光猫"):
            try:
                cmd_ont_list(cfg)
                return 0
            except Exception as exc:  # noqa: BLE001
                print("[错误]", exc)
                return 1
        if cmd0 in ("ont-block", "ontblock"):
            try:
                cmd_ont_block(cfg, args[1] if len(args) > 1 else None, True)
                return 0
            except Exception as exc:  # noqa: BLE001
                print("[错误]", exc)
                return 1
        if cmd0 in ("ont-unblock", "ontunblock"):
            try:
                cmd_ont_block(cfg, args[1] if len(args) > 1 else None, False)
                return 0
            except Exception as exc:  # noqa: BLE001
                print("[错误]", exc)
                return 1
        if cmd0 in ("ont-history", "onthistory", "ont-log"):
            try:
                cmd_ont_history(cfg)
                return 0
            except Exception as exc:  # noqa: BLE001
                print("[错误]", exc)
                return 1
        if cmd0 in ("ont-reapply", "ontreapply"):
            try:
                cmd_ont_reapply(cfg)
                return 0
            except Exception as exc:  # noqa: BLE001
                print("[错误]", exc)
                return 1
        if cmd0 in ("flap", "ont-flap", "flutter"):
            try:
                tgt = args[1] if len(args) > 1 and not args[1].startswith("--") else None
                rest = args[2:] if tgt else args[1:]
                cmd_flap(cfg, tgt, _parse_flap_opts(rest))
                return 0
            except SystemExit as exc:
                print(exc) if str(exc) else None
                return 1
            except Exception as exc:  # noqa: BLE001
                print("[错误]", exc)
                return 1
        if cmd0 in ("flap-log", "flaplog"):
            cmd_flap_log(cfg)
            return 0
    if len(argv) >= 2 and argv[1] in ("setpass", "pass"):
        if not ensure_password(cfg):
            return 1
        cmd_setpass(cfg)
        return 0
    if len(argv) >= 2 and argv[1] == "whoami":
        print("本机 MAC:", nc.detect_self_mac(cfg.host) or "没识别出来")
        return 0
    if not ensure_password(cfg):
        return 1

    router = nc.Router(cfg)
    try:
        router.login()
    except nc.RouterError as exc:
        print("[错误]", exc)
        return 1

    if not args:
        try:
            menu(router, cfg)
        except KeyboardInterrupt:
            print("\n已退出")
        return 0

    cmd = args[0].lower()
    try:
        if cmd == "list":
            print_devices(router.devices(with_link=("--link" in args)))
        elif cmd == "limit":
            cmd_limit(router, args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None)
        elif cmd in ("free", "unlimit"):
            cmd_free(router, args[1] if len(args) > 1 else None)
        elif cmd == "block":
            cmd_block(router, args[1] if len(args) > 1 else None, True)
        elif cmd in ("unblock", "allow"):
            cmd_block(router, args[1] if len(args) > 1 else None, False)
        elif cmd == "all":
            cmd_all(router, args[1] if len(args) > 1 else 1)
        elif cmd == "qos":
            what = args[1].lower() if len(args) > 1 else ""
            if what == "off":
                router.qos_switch(False)
                print("已暂停 QoS（所有限速失效，限速表保留）")
            elif what in ("manual", "on"):
                router.qos_switch(True)
                print("已恢复手工限速模式")
            elif what == "auto":
                router.qos_auto()
                print("已切回自动模式（不限速）")
            else:
                print("用法: netctl qos off|manual|auto")
        elif cmd == "status":
            cmd_status(router)
        else:
            print(__doc__)
    except nc.RouterError as exc:
        print("[错误]", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        print("[错误]", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
