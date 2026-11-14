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
"""
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
    ont.login()
    return ont


TYPE_NAME = {"1": "电脑", "2": "手机", "8": "网关/路由"}


def cmd_ont_list(cfg):
    ont = new_ont(cfg)
    rows = ont.devices()
    blocked = set()
    try:
        blocked = {(i.get("MACAddress") or "").upper() for i in ont.mac_filter()["list"]}
    except Exception:
        pass
    print("")
    print("%-4s %-22s %-15s %-18s %-7s %-10s %-8s %s" % (
        "序号", "名称", "IP", "MAC", "接入", "类型", "端口", "封禁"))
    print("-" * 110)
    for d in rows:
        link = "有线" if str(d["wlan"]) != "1" else "WiFi"
        print("%-5s %-22s %-15s %-18s %-7s %-10s %-8s %s" % (
            d["idx"], d["name"][:22], d["ip"] or "-", d["mac"] or "-", link,
            TYPE_NAME.get(str(d["type"]), "类型" + str(d["type"])),
            d["port"], "已封禁" if d["mac"].upper() in blocked else "正常"))
    print("")


def cmd_ont_block(cfg, target=None, blocked=True):
    ont = new_ont(cfg)
    rows = ont.devices()
    if target is None:
        cmd_ont_list(cfg)
        target = input("要%s哪台设备（序号/IP/名称）: " % ("封禁" if blocked else "解封"))
    dev = ont.resolve(target)
    ont.block(dev["mac"], blocked)
    print("光猫上「%s (%s)」已%s" % (dev["name"], dev["mac"], "封禁" if blocked else "解封"))


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
