#!/usr/bin/env python3
"""
differ.py - 新旧 PDF 章节差异检测（按拆分后章节文本对比）。

思路：
  - 首次全量处理后，为工作根目录内每个拆分 PDF 记录 {文本哈希, 页数} 到 .manifest.json。
  - 增量更新时，将新 PDF 拆分到临时目录，逐章计算文本哈希，与旧 manifest 对比，
    得出 新增 / 修改 / 删除 章节，并把新增+修改章节同步回工作根目录。

依赖:
    pip install pymupdf
"""

import hashlib
import json
import os
import re
import shutil
import sys

import fitz  # pymupdf

# 允许在 src/ 内直接导入拆分模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from splitter import split_pdf_by_bookmarks, DEFAULT_WORK_ROOT  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INCOMING_DIR = os.path.join(BASE_DIR, "PDF", "_incoming")
MANIFEST_NAME = ".manifest.json"

_WS_RE = re.compile(r"\s+")


# ── 章节文本哈希 ───────────────────────────────────────────────

def chapter_text_hash(pdf_path: str) -> str:
    """提取整章文本，归一化（去除所有空白）后返回 SHA-256。"""
    doc = fitz.open(pdf_path)
    try:
        parts = [doc[pn].get_text("text") for pn in range(doc.page_count)]
    finally:
        doc.close()
    text = _WS_RE.sub("", "".join(parts))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iter_chapter_pdfs(root: str):
    """遍历 root 下所有 PDF，yield (rel_path_posix, abs_path)。"""
    for dirpath, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            if not name.lower().endswith(".pdf"):
                continue
            abs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
            yield rel, abs_path


# ── manifest 读写 ─────────────────────────────────────────────

def manifest_path(root: str) -> str:
    return os.path.join(root, MANIFEST_NAME)


def build_manifest(root: str = None) -> dict:
    """扫描 root 下所有拆分 PDF，生成并写入 {rel_path: {hash, page_count}}。"""
    root = root or DEFAULT_WORK_ROOT
    manifest = {}
    for rel, abs_path in _iter_chapter_pdfs(root):
        try:
            doc = fitz.open(abs_path)
            page_count = doc.page_count
            doc.close()
            manifest[rel] = {
                "hash": chapter_text_hash(abs_path),
                "page_count": page_count,
            }
        except Exception as e:
            print(f"  [警告] 无法处理 {rel}: {e}")

    with open(manifest_path(root), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"📝 已记录基线清单：{manifest_path(root)}（{len(manifest)} 个章节）")
    return manifest


def load_manifest(root: str = None) -> dict:
    """读取 root 下的 .manifest.json，不存在时返回空字典。"""
    root = root or DEFAULT_WORK_ROOT
    path = manifest_path(root)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 差异检测 ───────────────────────────────────────────────────

def diff_new_pdf(new_pdf_path: str, work_root: str = None,
                 incoming_dir: str = None):
    """将新 PDF 与工作目录基线对比，返回差异结果。

    步骤：
      1. 将新 PDF 拆分到临时目录 incoming_dir。
      2. 逐章计算文本哈希。
      3. 与旧 manifest 对比，得出 新增 / 修改 / 删除。
      4. 将新增+修改章节覆盖同步到 work_root。

    返回 dict:
        {"added": [...], "modified": [...], "removed": [...],
         "changed": set(added+modified), "new_manifest": {...}}
    """
    work_root = work_root or DEFAULT_WORK_ROOT
    incoming_dir = incoming_dir or DEFAULT_INCOMING_DIR

    old_manifest = load_manifest(work_root)
    if not old_manifest:
        print("⚠️ 未找到基线清单（.manifest.json），无法增量对比。")
        print("   请先对原 PDF 执行一次全量处理以生成基线。")
        return {"added": [], "modified": [], "removed": [],
                "changed": set(), "new_manifest": {}}

    # 1. 拆分新 PDF 到临时目录（先清空避免残留）
    if os.path.isdir(incoming_dir):
        shutil.rmtree(incoming_dir)
    os.makedirs(incoming_dir, exist_ok=True)

    print(f"🔪 拆分新 PDF 到临时目录：{incoming_dir}")
    new_split = split_pdf_by_bookmarks(new_pdf_path, output_dir=incoming_dir)
    if not new_split:
        print("❌ 新 PDF 拆分失败或无有效书签。")
        return {"added": [], "modified": [], "removed": [],
                "changed": set(), "new_manifest": {}}

    # 2. 计算新章节哈希
    new_manifest = {}
    for rel, abs_path in _iter_chapter_pdfs(incoming_dir):
        try:
            doc = fitz.open(abs_path)
            page_count = doc.page_count
            doc.close()
            new_manifest[rel] = {
                "hash": chapter_text_hash(abs_path),
                "page_count": page_count,
            }
        except Exception as e:
            print(f"  [警告] 无法处理新章节 {rel}: {e}")

    # 3. 对比
    old_keys = set(old_manifest)
    new_keys = set(new_manifest)

    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    modified = sorted(
        rel for rel in (new_keys & old_keys)
        if new_manifest[rel]["hash"] != old_manifest[rel]["hash"]
    )

    changed = set(added) | set(modified)

    # 4. 将新增+修改章节同步到工作目录
    for rel in sorted(changed):
        src = os.path.join(incoming_dir, rel.replace("/", os.sep))
        dst = os.path.join(work_root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

    # 打印摘要
    print("\n" + "=" * 60)
    print("章节差异摘要")
    print("=" * 60)
    print(f"  新增: {len(added)}")
    for rel in added:
        print(f"    + {rel}")
    print(f"  修改: {len(modified)}")
    for rel in modified:
        print(f"    ~ {rel}")
    print(f"  删除: {len(removed)}")
    for rel in removed:
        print(f"    - {rel}")
    print(f"\n  需后续处理（新增+修改）章节数: {len(changed)}")

    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "changed": changed,
        "new_manifest": new_manifest,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="新旧 PDF 章节差异检测")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="为工作目录生成基线清单")
    p_build.add_argument("--root", default=None, help="工作根目录（默认 PDF/divided）")

    p_diff = sub.add_parser("diff", help="对比新 PDF 与基线")
    p_diff.add_argument("pdf", help="新 PDF 路径")
    p_diff.add_argument("--root", default=None, help="工作根目录（默认 PDF/divided）")

    args = parser.parse_args()
    if args.cmd == "build":
        build_manifest(args.root)
    elif args.cmd == "diff":
        if not os.path.isfile(args.pdf):
            print(f"❌ 文件不存在：{args.pdf}")
            return
        diff_new_pdf(args.pdf, args.root)


if __name__ == "__main__":
    main()

