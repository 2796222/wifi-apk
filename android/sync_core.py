# -*- coding: utf-8 -*-
"""把上一层目录的核心模块复制到 android/ 里（buildozer 只会打包自己目录下的文件）。"""
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
MODULES = ("netctl_core.py", "ont_core.py", "crypto_compat.py")

for name in MODULES:
    src = os.path.join(SRC, name)
    dst = os.path.join(HERE, name)
    if not os.path.exists(src):
        raise SystemExit("找不到 %s" % src)
    shutil.copy2(src, dst)
    print("已复制", name)

print("\n完成。现在可以在 android/ 目录里跑：buildozer android debug")
