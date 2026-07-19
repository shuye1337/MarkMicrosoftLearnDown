#!/usr/bin/env python3
"""
largest.py
查看 ./output 下最大的文件（递归扫描）。
"""

import os


def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    size = float(size)
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f} {units[idx]}"


def find_largest_files(root: str, top_n: int = 10):
    if not os.path.isdir(root):
        print(f"❌ 目录不存在：{root}")
        return

    files = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            files.append((path, size))

    if not files:
        print("未找到任何文件。")
        return

    files.sort(key=lambda item: item[1], reverse=True)
    print(f"📂 扫描目录：{root}")
    print(f"📄 文件总数：{len(files)}\n")
    print("📏 最大的文件：")
    for idx, (path, size) in enumerate(files[:top_n], start=1):
        print(f"{idx}. {path} ({human_size(size)})")


def main():
    root = os.path.join(".", "output")
    find_largest_files(root)


if __name__ == "__main__":
    main()
