"""Make a decompiled original function readable (dev tool).

Decodes "\\ddd" UTF-8 escapes in string literals and idXXXX hex identifiers
back to their Chinese names, and names well-known SDK command numbers.

    uv run python tools/legacy_extract/readable.py 收远征.lua out.lua
"""
import re
import sys
from pathlib import Path

SDK = {229: '多点比色', 2: '单点比色', 66: '多点找色', 168: '区域找色', 65: '点击', 219: '触摸',
       15: '延时', 13: '截图', 10: '日志', 74: '日志2', 84: '毫秒', 29: 'DPI', 44: '屏幕尺寸',
       191: '设置画布', 193: '读配置', 1: '取色', 119: '取色2', 88: '变速'}


def decode_string(body):
    raw = re.sub(r'\\(\d{1,3})', lambda m: chr(int(m.group(1))), body)
    try:
        return raw.encode('latin1').decode('utf-8')
    except UnicodeError:
        return body


def decode_identifier(match):
    try:
        return bytes.fromhex(match.group(1)).decode('utf-8')
    except (ValueError, UnicodeError):
        return match.group(0)


def readable(source):
    source = re.sub(r'"((?:[^"\\]|\\.)*)"', lambda m: '"' + decode_string(m.group(1)) + '"', source)
    source = re.sub(r'\bid((?:[0-9a-f]{2})+)\b', decode_identifier, source)
    # LuaAuxLid(N, ...) calls appear as `Lx = N` right after `Lx = Lx.LuaAuxLid`.
    source = source.replace('\r\n', '\n')
    source = re.sub(r'(L\d+_1) = \1\.LuaAuxLid\n(\s*)(L\d+_1) = (\d+)\n',
                    lambda m: f'{m.group(1)} = {m.group(1)}.LuaAuxLid\n{m.group(2)}{m.group(3)} = {m.group(4)}'
                              f'  -- {SDK.get(int(m.group(4)), "SDK")}\n', source)
    return source


if __name__ == '__main__':
    text = Path(sys.argv[1]).read_bytes().decode('latin1')
    Path(sys.argv[2]).write_text(readable(text), encoding='utf-8')
