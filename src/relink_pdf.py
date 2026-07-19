#!/usr/bin/env python3
"""
relink_pdf.py - Replace MS Learn Direct2D hyperlinks in PDFs with local paths.

Replaces https://learn.microsoft.com/zh-cn/windows/win32/Direct2D/<slug>
links in PDF/divided/ PDFs with relative paths to local PDF files.
Uses toc.json href->toc_title mapping for the directory structure.
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
TOC_PATH = os.path.join(BASE_DIR, "toc.json")
PDF_ROOT = os.path.join(BASE_DIR, "PDF", "divided")
DIRECT2D_DIR = os.path.join(PDF_ROOT, "Direct2D")
BACKUP_DIR = os.path.join(BASE_DIR, "PDF", "backup")

LINK_PREFIX = "https://learn.microsoft.com/zh-cn/windows/win32/Direct2D/"
LINK_PATTERN = re.compile(r"^" + re.escape(LINK_PREFIX) + r"(.+)")


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


def find_pdf(mapping, slug):
    """根据 slug 查找本地 PDF 的绝对路径。"""
    if slug not in mapping:
        return None
    rel_path = mapping[slug]
    # 映射路径以 Direct2D/ 开头，PDF_ROOT = PDF/divided
    candidate = os.path.join(PDF_ROOT, rel_path + ".pdf")
    return candidate if os.path.isfile(candidate) else None


def backup_pdf(pdf_path):
    """备份原始 PDF 到 backup 目录。"""
    rel = os.path.relpath(pdf_path, PDF_ROOT)
    backup = os.path.join(BACKUP_DIR, rel)
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    shutil.copy2(pdf_path, backup)
    return backup


def replace_links_in_pdf(pdf_path, mapping):
    """替换单个 PDF 中的超链接，返回 (modified_count, total_matched, not_found_list)。"""
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

            m = LINK_PATTERN.match(uri)
            if not m:
                continue

            total_matched += 1
            slug = unquote(m.group(1))
            slug = slug.split("#")[0].split("?")[0].rstrip("/")

            target_pdf = find_pdf(mapping, slug)
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


def main():
    print("=" * 60)
    print("Direct2D PDF 超链接重映射工具")
    print("=" * 60)

    if not os.path.isfile(TOC_PATH):
        print(f"Error: {TOC_PATH} not found")
        sys.exit(1)

    print("Loading toc.json ...")
    with open(TOC_PATH, "rb") as f:
        data = json.load(f)

    mapping = flatten_toc(data)
    print(f"Mapping built: {len(mapping)} entries")

    pdf_files = []
    for root, dirs, files in os.walk(PDF_ROOT):
        dirs.sort()
        files.sort()
        for f in files:
            if f.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, f))

    print(f"Found {len(pdf_files)} PDF files")
    print()

    total_modified = 0
    total_matched_all = 0
    total_not_found = []

    for pdf_path in pdf_files:
        rel = os.path.relpath(pdf_path, PDF_ROOT)
        try:
            modified, matched, nf = replace_links_in_pdf(pdf_path, mapping)
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
    print(f"Total Direct2D links found: {total_matched_all}")
    if total_not_found:
        uniq = sorted(set(total_not_found))
        print(f"Unmapped slugs ({len(uniq)}):")
        for s in uniq:
            print(f"  - {s}")


if __name__ == "__main__":
    main()
