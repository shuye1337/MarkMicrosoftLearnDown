#!/usr/bin/env python3
"""
relinker.py - 将 PDF 内对其他章节的超链接替换为本地路径。

默认替换 https://learn.microsoft.com/zh-cn/windows/win32/Direct2D/<slug>
形式的链接，使用 toc.json 的 href->toc_title 映射得到目录结构。
URL 前缀、toc.json 路径、PDF 根目录均可由调用方指定。
"""

import json
import os
import re
import sys
import shutil
from urllib.parse import unquote

import fitz  # pymupdf

# 确保 stdout 能处理中文
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TOC_PATH = os.path.join(BASE_DIR, "toc.json")
DEFAULT_PDF_ROOT = os.path.join(BASE_DIR, "PDF", "divided")
DEFAULT_BACKUP_DIR = os.path.join(BASE_DIR, "PDF", "backup")

DEFAULT_LINK_PREFIX = "https://learn.microsoft.com/zh-cn/windows/win32/Direct2D/"


def flatten_toc(data):
    """递归遍历 toc.json，返回 {href: local_rel_path_without_ext} 字典。"""
    mapping = {}

    def walk(node, parent_path=""):
        href = node.get("href", "")
        title = node.get("toc_title", "")
        children = node.get("children", [])

        cur_path = os.path.join(parent_path, title) if title else parent_path

        if href and not href.startswith("/"):
            mapping[href] = cur_path

        for child in children:
            walk(child, cur_path)

    for item in data.get("items", []):
        walk(item)

    return mapping


def find_pdf(mapping, slug, pdf_root):
    """根据 slug 查找本地 PDF 的绝对路径。"""
    if slug not in mapping:
        return None
    rel_path = mapping[slug]
    candidate = os.path.join(pdf_root, rel_path + ".pdf")
    return candidate if os.path.isfile(candidate) else None


def backup_pdf(pdf_path, pdf_root, backup_dir=DEFAULT_BACKUP_DIR):
    """备份原始 PDF 到 backup 目录。"""
    rel = os.path.relpath(pdf_path, pdf_root)
    backup = os.path.join(backup_dir, rel)
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    shutil.copy2(pdf_path, backup)
    return backup


def replace_links_in_pdf(pdf_path, mapping, pdf_root, link_pattern):
    """替换单个 PDF 中的超链接。

    返回 (modified: bool, total_matched: int, not_found: list[str])。
    """
    doc = fitz.open(pdf_path)
    modified = False
    total_matched = 0
    not_found = []

    for page in doc:
        links = page.get_links()
        for link in links:
            uri = link.get("uri", "")
            if not uri:
                continue

            m = link_pattern.match(uri)
            if not m:
                continue

            total_matched += 1
            slug = unquote(m.group(1))
            slug = slug.split("#")[0].split("?")[0].rstrip("/")

            target_pdf = find_pdf(mapping, slug, pdf_root)
            if target_pdf is None:
                not_found.append(slug)
                continue

            rel_path = os.path.relpath(target_pdf, os.path.dirname(pdf_path))
            rel_path = rel_path.replace("\\", "/")

            link["uri"] = rel_path
            page.update_link(link)
            modified = True

    if modified:
        doc.save(pdf_path, incremental=True, encryption=0)

    doc.close()
    return modified, total_matched, not_found


def _iter_pdf_files(pdf_root, restrict_to=None):
    """遍历 pdf_root 下的 PDF；restrict_to 为章节相对路径集合时仅返回这些文件。"""
    if restrict_to is not None:
        for rel in sorted(restrict_to):
            path = os.path.join(pdf_root, rel.replace("/", os.sep))
            if os.path.isfile(path):
                yield path
            else:
                print(f"[跳过] 未找到章节文件：{rel}")
        return

    for root, dirs, files in os.walk(pdf_root):
        dirs.sort()
        files.sort()
        for f in files:
            if f.lower().endswith(".pdf"):
                yield os.path.join(root, f)


def relink_all(pdf_root=None, toc_path=None, url_prefix=DEFAULT_LINK_PREFIX,
               restrict_to=None):
    """对 pdf_root 下的 PDF 执行超链接重映射。

    参数:
        pdf_root:    PDF 根目录，默认 PDF/divided。
        toc_path:    toc.json 路径，默认项目根 toc.json。
        url_prefix:  待替换的 URL 前缀（决定匹配规则）。
        restrict_to: 可选章节相对路径集合，仅处理这些章节（增量更新）。

    返回统计字典 {modified, total, matched, not_found}。
    """
    pdf_root = pdf_root or DEFAULT_PDF_ROOT
    toc_path = toc_path or DEFAULT_TOC_PATH

    print("=" * 60)
    print("PDF 超链接重映射工具")
    print("=" * 60)

    if not os.path.isfile(toc_path):
        print(f"Error: {toc_path} not found")
        return {"modified": 0, "total": 0, "matched": 0, "not_found": []}

    link_pattern = re.compile(r"^" + re.escape(url_prefix) + r"(.+)")

    print(f"Loading {os.path.basename(toc_path)} ...")
    with open(toc_path, "rb") as f:
        data = json.load(f)

    mapping = flatten_toc(data)
    print(f"Mapping built: {len(mapping)} entries")
    print(f"URL prefix: {url_prefix}")

    pdf_files = list(_iter_pdf_files(pdf_root, restrict_to))
    print(f"Found {len(pdf_files)} PDF files")
    print()

    total_modified = 0
    total_matched_all = 0
    total_not_found = []

    for pdf_path in pdf_files:
        rel = os.path.relpath(pdf_path, pdf_root)
        try:
            modified, matched, nf = replace_links_in_pdf(
                pdf_path, mapping, pdf_root, link_pattern)
            if matched > 0:
                status = "M" if modified else "-"
                print(f"[{status}] {rel}  ({matched} links, {len(nf)} not mapped)")
                if modified:
                    total_modified += 1
                total_matched_all += matched
                total_not_found.extend(nf)
            else:
                print(f"[ ] {rel}")
        except Exception as e:
            print(f"[E] {rel}  Error: {e}")

    print()
    print(f"Modified: {total_modified} / {len(pdf_files)} PDFs")
    print(f"Total links found: {total_matched_all}")
    if total_not_found:
        uniq = sorted(set(total_not_found))
        print(f"Unmapped slugs ({len(uniq)}):")
        for s in uniq:
            print(f"  - {s}")

    return {
        "modified": total_modified,
        "total": len(pdf_files),
        "matched": total_matched_all,
        "not_found": sorted(set(total_not_found)),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="PDF 超链接重映射工具")
    parser.add_argument("--pdf-root", default=None, help="PDF 根目录（默认 PDF/divided）")
    parser.add_argument("--toc", default=None, help="toc.json 路径（默认项目根 toc.json）")
    parser.add_argument("--url-prefix", default=DEFAULT_LINK_PREFIX,
                        help="待替换的 URL 前缀")
    args = parser.parse_args()

    relink_all(pdf_root=args.pdf_root, toc_path=args.toc, url_prefix=args.url_prefix)


if __name__ == "__main__":
    main()
