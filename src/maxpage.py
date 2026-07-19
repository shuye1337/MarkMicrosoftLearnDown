#!/usr/bin/env python3
"""
max_bookmark_gap.py
统计 PDF 中相邻书签之间最大的页数间隔，并定位该间隔的位置。

用法:
    python max_bookmark_gap.py input.pdf

依赖:
    pip install pypdf
"""

import argparse
import os
import io
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError


def clean_pdf_stream(file_path):
    """尝试清理 %%EOF 之后的多余垃圾数据"""
    with open(file_path, 'rb') as f:
        data = f.read()
    eof_index = data.rfind(b'%%EOF')
    if eof_index != -1:
        return io.BytesIO(data[:eof_index + 5])
    return None


def extract_bookmarks_flat(outline, reader, result=None):
    """递归提取所有书签的页码和标题，返回扁平列表"""
    if result is None:
        result = []

    i = 0
    while i < len(outline):
        item = outline[i]
        if isinstance(item, list):
            extract_bookmarks_flat(item, reader, result)
            i += 1
            continue
        try:
            page_number = reader.get_destination_page_number(item)
            title = item.title.strip() if item.title else f"Untitled_p{page_number}"
            result.append({"title": title, "page": page_number})
            # 检查是否有子节点列表
            if (i + 1 < len(outline)) and isinstance(outline[i + 1], list):
                extract_bookmarks_flat(outline[i + 1], reader, result)
                i += 2
            else:
                i += 1
        except Exception:
            i += 1

    return result


def find_max_bookmark_gap(pdf_path: str):
    # 1. 读取 PDF（含自动修复）
    reader = None
    try:
        reader = PdfReader(pdf_path, strict=False)
    except (PdfReadError, PdfStreamError):
        cleaned = clean_pdf_stream(pdf_path)
        if cleaned:
            try:
                reader = PdfReader(cleaned, strict=False)
            except Exception as e:
                print(f"❌ 自动清理后依然无法读取: {e}")
                return
        else:
            print("❌ 文件严重损坏，无法读取。")
            return

    total_pages = len(reader.pages)
    if not reader.outline:
        print("❌ 该 PDF 没有书签。")
        return

    # 2. 提取并过滤有效书签
    bookmarks = extract_bookmarks_flat(reader.outline, reader)
    bookmarks = [b for b in bookmarks if b["page"] is not None]

    if len(bookmarks) < 2:
        print(f"⚠️ 仅有 {len(bookmarks)} 个有效书签，无法计算间隔。")
        return

    # 3. 按页码排序去重
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
        return

    # 4. 收集所有大于 20 页的相邻书签间隔
    large_gaps = []

    for i in range(len(bookmarks) - 1):
        gap = bookmarks[i + 1]["page"] - bookmarks[i]["page"]
        if gap > 20:
            large_gaps.append({
                "start": bookmarks[i],
                "end": bookmarks[i + 1],
                "gap": gap,
            })

    # 同时检查最后一个书签到文档末尾的间隔
    last_gap = total_pages - bookmarks[-1]["page"]
    if last_gap > 20:
        large_gaps.append({
            "start": bookmarks[-1],
            "end": {"title": "[文档末尾]", "page": total_pages},
            "gap": last_gap,
        })

    # 5. 输出结果
    print(f"📄 PDF: {pdf_path}")
    print(f"📑 总页数: {total_pages}")
    print(f"🔖 有效书签数: {len(bookmarks)}")
    print(f"🔎 页数大于 20 的间隔数: {len(large_gaps)}")

    if not large_gaps:
        print("\n未发现页数大于 20 的相邻书签间隔。")
        return

    print("\n📏 所有页数大于 20 的相邻书签间隔：")
    for idx, item in enumerate(large_gaps, start=1):
        print(f"{idx}. 间隔 {item['gap']} 页")
        print(f"   起始书签: 「{item['start']['title']}」 → 第 {item['start']['page'] + 1} 页")
        print(f"   结束书签: 「{item['end']['title']}」 → 第 {item['end']['page'] + 1} 页")


def main():
    parser = argparse.ArgumentParser(description="统计 PDF 相邻书签最大页数间隔")
    parser.add_argument("pdf", help="PDF 文件路径")
    args = parser.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"❌ 文件不存在：{args.pdf}")
        return

    find_max_bookmark_gap(args.pdf)


if __name__ == "__main__":
    main()