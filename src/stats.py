#!/usr/bin/env python3
"""
stats.py - 拆分产物统计工具（合并自 largest.py 与 maxpage.py）。

提供三个能力：
  1. find_largest_files(root, top_n)   —— 按文件大小找出最大的文件
  2. max_single_file_pages(root)       —— 找出页数最多的单个拆分 PDF
  3. find_max_bookmark_gap(pdf_path)   —— 统计原 PDF 相邻书签最大页数间隔（可选诊断）

依赖:
    pip install pypdf
"""

import argparse
import io
import os

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError


# ── 通用工具 ───────────────────────────────────────────────────

def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    size = float(size)
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f} {units[idx]}"


def _clean_pdf_stream(file_path):
    """尝试清理 %%EOF 之后的多余垃圾数据。"""
    with open(file_path, "rb") as f:
        data = f.read()
    eof_index = data.rfind(b"%%EOF")
    if eof_index != -1:
        return io.BytesIO(data[:eof_index + 5])
    return None


def _open_reader(pdf_path):
    """读取 PDF（含自动修复），失败返回 None。"""
    try:
        return PdfReader(pdf_path, strict=False)
    except (PdfReadError, PdfStreamError):
        cleaned = _clean_pdf_stream(pdf_path)
        if cleaned:
            try:
                return PdfReader(cleaned, strict=False)
            except Exception:
                return None
    return None


# ── 1. 最大文件（按大小） ──────────────────────────────────────

def find_largest_files(root: str, top_n: int = 10):
    """递归扫描 root，按文件大小返回并打印最大的 top_n 个文件。

    返回 list[(path, size)]（已按大小降序）。
    """
    if not os.path.isdir(root):
        print(f"❌ 目录不存在：{root}")
        return []

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
        return []

    files.sort(key=lambda item: item[1], reverse=True)
    print(f"📂 扫描目录：{root}")
    print(f"📄 文件总数：{len(files)}\n")
    print("📏 最大的文件：")
    for idx, (path, size) in enumerate(files[:top_n], start=1):
        print(f"{idx}. {path} ({human_size(size)})")
    return files


# ── 2. 页数最多的单个拆分 PDF ──────────────────────────────────

def max_single_file_pages(root: str, top_n: int = 10):
    """扫描 root 下所有 PDF，统计每个文件页数，返回并打印页数最多者。

    返回 list[(path, page_count)]（已按页数降序）。
    """
    if not os.path.isdir(root):
        print(f"❌ 目录不存在：{root}")
        return []

    pdfs = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if not name.lower().endswith(".pdf"):
                continue
            path = os.path.join(dirpath, name)
            reader = _open_reader(path)
            if reader is None:
                print(f"  [警告] 无法读取：{path}")
                continue
            try:
                pdfs.append((path, len(reader.pages)))
            except Exception:
                print(f"  [警告] 无法统计页数：{path}")

    if not pdfs:
        print("未找到任何可读取的 PDF 文件。")
        return []

    pdfs.sort(key=lambda item: item[1], reverse=True)
    print(f"📂 扫描目录：{root}")
    print(f"📄 PDF 总数：{len(pdfs)}\n")
    print("📑 页数最多的单个文件：")
    for idx, (path, pages) in enumerate(pdfs[:top_n], start=1):
        print(f"{idx}. {path} ({pages} 页)")
    return pdfs


# ── 3. 原 PDF 相邻书签最大页数间隔（可选诊断） ─────────────────

def _extract_bookmarks_flat(outline, reader, result=None):
    """递归提取所有书签的页码和标题，返回扁平列表。"""
    if result is None:
        result = []

    i = 0
    while i < len(outline):
        item = outline[i]
        if isinstance(item, list):
            _extract_bookmarks_flat(item, reader, result)
            i += 1
            continue
        try:
            page_number = reader.get_destination_page_number(item)
            title = item.title.strip() if item.title else f"Untitled_p{page_number}"
            result.append({"title": title, "page": page_number})
            if (i + 1 < len(outline)) and isinstance(outline[i + 1], list):
                _extract_bookmarks_flat(outline[i + 1], reader, result)
                i += 2
            else:
                i += 1
        except Exception:
            i += 1

    return result


def find_max_bookmark_gap(pdf_path: str, threshold: int = 20):
    """统计原 PDF 中大于 threshold 页的相邻书签间隔并打印。"""
    reader = _open_reader(pdf_path)
    if reader is None:
        print("❌ 文件严重损坏，无法读取。")
        return []

    total_pages = len(reader.pages)
    if not reader.outline:
        print("❌ 该 PDF 没有书签。")
        return []

    bookmarks = _extract_bookmarks_flat(reader.outline, reader)
    bookmarks = [b for b in bookmarks if b["page"] is not None]

    if len(bookmarks) < 2:
        print(f"⚠️ 仅有 {len(bookmarks)} 个有效书签，无法计算间隔。")
        return []

    bookmarks.sort(key=lambda b: b["page"])
    seen = set()
    unique = []
    for b in bookmarks:
        if b["page"] not in seen:
            seen.add(b["page"])
            unique.append(b)
    bookmarks = unique

    if len(bookmarks) < 2:
        print("⚠️ 去重后仅剩 1 个书签，无法计算间隔。")
        return []

    large_gaps = []
    for i in range(len(bookmarks) - 1):
        gap = bookmarks[i + 1]["page"] - bookmarks[i]["page"]
        if gap > threshold:
            large_gaps.append({
                "start": bookmarks[i],
                "end": bookmarks[i + 1],
                "gap": gap,
            })

    last_gap = total_pages - bookmarks[-1]["page"]
    if last_gap > threshold:
        large_gaps.append({
            "start": bookmarks[-1],
            "end": {"title": "[文档末尾]", "page": total_pages},
            "gap": last_gap,
        })

    print(f"📄 PDF: {pdf_path}")
    print(f"📑 总页数: {total_pages}")
    print(f"🔖 有效书签数: {len(bookmarks)}")
    print(f"🔎 页数大于 {threshold} 的间隔数: {len(large_gaps)}")

    if not large_gaps:
        print(f"\n未发现页数大于 {threshold} 的相邻书签间隔。")
        return []

    print(f"\n📏 所有页数大于 {threshold} 的相邻书签间隔：")
    for idx, item in enumerate(large_gaps, start=1):
        print(f"{idx}. 间隔 {item['gap']} 页")
        print(f"   起始书签: 「{item['start']['title']}」 → 第 {item['start']['page'] + 1} 页")
        print(f"   结束书签: 「{item['end']['title']}」 → 第 {item['end']['page'] + 1} 页")
    return large_gaps


# ── 命令行入口 ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="拆分产物统计工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_largest = sub.add_parser("largest", help="按文件大小找最大文件")
    p_largest.add_argument("root", help="扫描目录")
    p_largest.add_argument("-n", "--top", type=int, default=10)

    p_pages = sub.add_parser("pages", help="找页数最多的单个 PDF")
    p_pages.add_argument("root", help="扫描目录")
    p_pages.add_argument("-n", "--top", type=int, default=10)

    p_gap = sub.add_parser("gap", help="统计原 PDF 书签最大页数间隔")
    p_gap.add_argument("pdf", help="PDF 文件路径")

    args = parser.parse_args()
    if args.cmd == "largest":
        find_largest_files(args.root, args.top)
    elif args.cmd == "pages":
        max_single_file_pages(args.root, args.top)
    elif args.cmd == "gap":
        if not os.path.isfile(args.pdf):
            print(f"❌ 文件不存在：{args.pdf}")
            return
        find_max_bookmark_gap(args.pdf)


if __name__ == "__main__":
    main()
