[app]

# 应用名（手机上显示）
title = netctl

# 包名：org.home.netctl  → 安装后是 org.home.netctl
package.name = netctl
package.domain = org.home

# 源码目录 = 当前 android/ 目录
source.dir = .

# 只打包这些后缀的文件（避免把临时文件、文档塞进去）
# ttf/otf 是给中文字体用的，必须有，否则界面全是方块
source.include_exts = py,png,jpg,kv,atlas,json,ttf,otf

# 别把带密码的配置打进去
source.exclude_patterns = netctl.json, __pycache__, *.pyc

version = 0.1

# 依赖：python3 + kivy 就够（AES 用纯 Python 兜底，不需要编译 cryptography）
requirements = python3,kivy

orientation = portrait
fullscreen = 0

# 需要联网权限（访问 192.168.31.1 / 192.168.1.1）
android.permissions = INTERNET

# 目标/最低 Android 版本
android.api = 31
android.minapi = 21

# 架构：现在手机基本都是 arm64
android.archs = arm64-v8a

android.allow_backup = True
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
