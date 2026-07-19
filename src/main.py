#!/usr/bin/env python3
"""
main.py - PDF 文档处理工作链交互式向导。

串联五个环节：
    输入 PDF 路径 -> 按书签拆分 -> (可选)统计 -> 超链接重映射 -> 转 Markdown
并提供增量更新：
    输入新 PDF -> 与基线对比找出变化章节 -> 仅对变化章节重映射+转换

运行:
    python src/main.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from splitter import split_pdf_by_bookmarks, DEFAULT_WORK_ROOT  # noqa: E402
from stats import find_largest_files, max_single_file_pages  # noqa: E402
from relinker import relink_all, DEFAULT_TOC_PATH, DEFAULT_LINK_PREFIX  # noqa: E402
from converter import Converter, DEFAULT_MD_ROOT, DEFAULT_PIC_ROOT  # noqa: E402
from differ import build_manifest, diff_new_pdf, manifest_path  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK_ROOT = DEFAULT_WORK_ROOT


# ── 输入辅助 ───────────────────────────────────────────────────

def ask(prompt: str, default: str = None) -> str:
    """带默认值的文本输入。"""
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"{prompt}{suffix}: ").strip()
        if val:
            return val
        if default is not None:
            return default
        print("  输入不能为空，请重试。")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    """是/否确认，默认值由 default 决定。"""
    hint = "Y/n" if default else "y/N"
    while True:
        val = input(f"{prompt} ({hint}): ").strip().lower()
        if not val:
            return default
        if val in ("y", "yes", "是"):
            return True
        if val in ("n", "no", "否"):
            return False
        print("  请输入 y 或 n。")


def ask_pdf_path(prompt: str) -> str:
    """要求输入存在的 PDF 文件路径。"""
    while True:
        val = ask(prompt)
        val = val.strip().strip('"').strip("'")
        if os.path.isfile(val):
            return val
        print(f"  文件不存在：{val}，请重试。")


# ── 公共步骤：重映射 + 转 Markdown ────────────────────────────

def _relink_and_convert(restrict_to=None):
    """执行超链接重映射与 Markdown 转换（可限定章节集合）。"""
    # 超链接重映射
    print("\n── 步骤：超链接重映射 ──")
    toc_path = ask("toc.json 路径", default=DEFAULT_TOC_PATH)
    url_prefix = ask("待替换的 URL 前缀", default=DEFAULT_LINK_PREFIX)
    if ask_yes_no("即将写回 PDF 文件，是否继续？", default=True):
        relink_all(pdf_root=WORK_ROOT, toc_path=toc_path,
                   url_prefix=url_prefix, restrict_to=restrict_to)
    else:
        print("  已跳过超链接重映射。")

    # 转 Markdown
    print("\n── 步骤：转换 Markdown ──")
    print(f"  MD 输出: {DEFAULT_MD_ROOT}")
    print(f"  图片输出: {DEFAULT_PIC_ROOT}")
    Converter(pdf_root=WORK_ROOT).run(restrict_to=restrict_to)


# ── 全量流程 ───────────────────────────────────────────────────

def full_pipeline():
    print("\n" + "=" * 60)
    print("全量处理流程")
    print("=" * 60)

    pdf_path = ask_pdf_path("请输入完整 PDF 文件路径")

    # 1. 按书签拆分
    print("\n── 步骤：按书签拆分 ──")
    if os.path.isdir(WORK_ROOT) and os.listdir(WORK_ROOT):
        if not ask_yes_no(f"工作目录 {WORK_ROOT} 已存在内容，拆分可能覆盖同名文件，是否继续？",
                          default=False):
            print("已取消。")
            return
    manifest = split_pdf_by_bookmarks(pdf_path, output_dir=WORK_ROOT)
    if not manifest:
        print("拆分失败，流程终止。")
        return

    # 2. 可选统计
    if ask_yes_no("\n是否统计最大文件与最大单文件页数？", default=False):
        print("\n── 统计：最大文件（按大小） ──")
        find_largest_files(WORK_ROOT, top_n=10)
        print("\n── 统计：页数最多的单个文件 ──")
        max_single_file_pages(WORK_ROOT, top_n=10)

    # 3. 重映射 + 4. 转 Markdown
    _relink_and_convert(restrict_to=None)

    # 5. 记录基线
    print("\n── 步骤：记录基线清单 ──")
    build_manifest(WORK_ROOT)

    print("\n🎉 全量流程完成。")


# ── 增量流程 ───────────────────────────────────────────────────

def incremental_pipeline():
    print("\n" + "=" * 60)
    print("增量更新流程")
    print("=" * 60)

    if not os.path.isfile(manifest_path(WORK_ROOT)):
        print(f"⚠️ 未找到基线清单：{manifest_path(WORK_ROOT)}")
        print("   请先运行一次全量处理以生成基线。")
        return

    new_pdf = ask_pdf_path("请输入新的 PDF 文件路径")

    # 1. 差异检测
    result = diff_new_pdf(new_pdf, work_root=WORK_ROOT)
    changed = result["changed"]

    if not changed:
        print("\n✅ 未检测到变化章节，无需后续处理。")
        return

    # 2. 确认后仅处理变化章节
    if not ask_yes_no(f"\n将对 {len(changed)} 个变化章节执行重映射+转换，是否继续？",
                      default=True):
        print("已取消。")
        return

    _relink_and_convert(restrict_to=changed)

    # 3. 更新基线清单
    print("\n── 步骤：更新基线清单 ──")
    build_manifest(WORK_ROOT)

    print("\n🎉 增量流程完成。")


# ── 入口 ───────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("PDF 文档处理工作链")
    print("=" * 60)
    print(f"工作根目录: {WORK_ROOT}")
    print()
    print("请选择模式：")
    print("  [1] 全量处理（处理一份新文档）")
    print("  [2] 增量更新（对比新 PDF，仅处理变化章节）")

    while True:
        choice = input("请输入 1 或 2: ").strip()
        if choice == "1":
            full_pipeline()
            break
        if choice == "2":
            incremental_pipeline()
            break
        print("  无效选择，请输入 1 或 2。")


if __name__ == "__main__":
    main()
