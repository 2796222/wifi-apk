# -*- coding: utf-8 -*-
"""
crypto_compat.py —— AES-256-CBC 兼容层

优先用 cryptography（桌面端已装、速度快）；
如果没装（比如 Android / buildozer 里不好编译 C 扩展），自动退回纯 Python 实现。
纯 Python 版只用于光猫那几个几百字节的小字段，性能完全够。
"""

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    HAVE_CRYPTO = True
except Exception:  # pragma: no cover
    HAVE_CRYPTO = False


# ------------------------------------------------------------------ 纯 Python AES
_SBOX = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
]
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36, 0x6c, 0xd8, 0xab, 0x4d]


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x1b) & 0xff
    return a


def _mul(a, b):
    res = 0
    for _ in range(8):
        if b & 1:
            res ^= a
        a = _xtime(a)
        b >>= 1
    return res


class _AES(object):
    """AES-256 分组加解密（纯 Python）"""

    def __init__(self, key):
        if len(key) not in (16, 24, 32):
            raise ValueError("key 长度必须是 16/24/32 字节")
        self.nk = len(key) // 4
        self.nr = self.nk + 6
        self._expand_key(key)

    def _expand_key(self, key):
        nb = 4
        total = nb * (self.nr + 1)
        w = [list(key[4 * i:4 * i + 4]) for i in range(self.nk)]
        for i in range(self.nk, total):
            temp = list(w[i - 1])
            if i % self.nk == 0:
                temp = temp[1:] + temp[:1]
                temp = [_SBOX[b] for b in temp]
                temp[0] ^= _RCON[i // self.nk - 1]
            elif self.nk > 6 and i % self.nk == 4:
                temp = [_SBOX[b] for b in temp]
            w.append([w[i - self.nk][j] ^ temp[j] for j in range(4)])
        self.w = w

    def _add_round_key(self, s, rnd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= self.w[rnd * 4 + c][r]

    def _encrypt_block(self, block):
        s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
        self._add_round_key(s, 0)
        for rnd in range(1, self.nr):
            for r in range(4):
                for c in range(4):
                    s[r][c] = _SBOX[s[r][c]]
            for r in range(1, 4):
                s[r] = s[r][r:] + s[r][:r]
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = _mul(a[0], 2) ^ _mul(a[1], 3) ^ a[2] ^ a[3]
                s[1][c] = a[0] ^ _mul(a[1], 2) ^ _mul(a[2], 3) ^ a[3]
                s[2][c] = a[0] ^ a[1] ^ _mul(a[2], 2) ^ _mul(a[3], 3)
                s[3][c] = _mul(a[0], 3) ^ a[1] ^ a[2] ^ _mul(a[3], 2)
            self._add_round_key(s, rnd)
        for r in range(4):
            for c in range(4):
                s[r][c] = _SBOX[s[r][c]]
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]
        self._add_round_key(s, self.nr)
        return bytes(s[r][c] for c in range(4) for r in range(4))

    def _decrypt_block(self, block):
        s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
        self._add_round_key(s, self.nr)
        for rnd in range(self.nr - 1, 0, -1):
            for r in range(1, 4):
                s[r] = s[r][-r:] + s[r][:-r]
            for r in range(4):
                for c in range(4):
                    s[r][c] = _INV_SBOX[s[r][c]]
            self._add_round_key(s, rnd)
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = _mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9)
                s[1][c] = _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13)
                s[2][c] = _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11)
                s[3][c] = _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]
        for r in range(4):
            for c in range(4):
                s[r][c] = _INV_SBOX[s[r][c]]
        self._add_round_key(s, 0)
        return bytes(s[r][c] for c in range(4) for r in range(4))


# ------------------------------------------------------------------ 对外 API（CBC + PKCS7）

def _pad(data):
    n = 16 - len(data) % 16
    return data + bytes([n]) * n


def _unpad(data):
    n = data[-1]
    if n < 1 or n > 16:
        raise ValueError("bad padding")
    return data[:-n]


def encrypt_cbc(key, iv, data):
    """AES-CBC + PKCS7 加密"""
    data = _pad(data)
    if HAVE_CRYPTO:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return cipher.update(data) + cipher.finalize()
    aes = _AES(key)
    out = b""
    prev = iv
    for i in range(0, len(data), 16):
        block = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
        prev = aes._encrypt_block(block)
        out += prev
    return out


def decrypt_cbc(key, iv, data):
    """AES-CBC + PKCS7 解密"""
    if HAVE_CRYPTO:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return _unpad(cipher.update(data) + cipher.finalize())
    aes = _AES(key)
    out = b""
    prev = iv
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(aes._decrypt_block(block), prev))
        prev = block
    return _unpad(out)
