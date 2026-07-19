#!/usr/bin/env python3
"""
splitter.py
按 PDF 书签（大纲/Outlines）将 PDF 拆分为多个文件，并按书签层级自动创建文件夹。

用法:
    python splitter.py input.pdf [-o output_dir] [--level 1]

依赖:
    pip install pypdf
"""

import argparse
import os
import re
import io
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError, PdfStreamError

# 统一工作根目录：拆分产物默认输出到 PDF/divided/，供 relink 与 toMD 复用
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_WORK_ROOT = os.path.join(BASE_DIR, "PDF", "divided")


# ──────────────────────────────────────────────
# 1. 递归提取书签，支持嵌套层级和文件夹路径
# ──────────────────────────────────────────────
def extract_bookmarks(outline, reader, parent_path="", result=None):
    """
    递归解析 PDF 大纲（outline），返回扁平列表:
    [
        {"title": str, "page": int, "folder_path": str},
        ...
    ]
    """
    if result is None:
        result = []

    for item in outline:
        if isinstance(item, list):
            # 遇到嵌套列表，说明进入了下一层。
            # 注意：pypdf 的 outline 结构中，列表通常紧跟在父节点后面。
            # 为了简化，我们在这里递归，但需要知道父节点的标题。
            # 由于这里的 item 只是子节点列表，我们无法直接获取父节点标题，
            # 所以我们需要改变遍历方式。
            pass

    # 重新设计遍历逻辑以正确获取父节点标题
    i = 0
    while i < len(outline):
        item = outline[i]
        
        if isinstance(item, list):
            # 理论上不应该在没有父节点的情况下遇到 list，
            # 但如果遇到，我们只能忽略或用空路径
            extract_bookmarks(item, reader, parent_path, result)
            i += 1
            continue

        # item 是一个 Destination 对象
        try:
            page_number = reader.get_destination_page_number(item)
            title = item.title.strip() if item.title else f"Untitled_p{page_number}"
            
            # 检查下一个元素是否是 list（即当前 item 是否有子节点）
            # 如果有子节点，当前 item 的标题将作为子节点的文件夹名
            has_children = (i + 1 < len(outline)) and isinstance(outline[i + 1], list)
            
            # 当前节点的完整路径（用于显示）
            # current_path = os.path.join(parent_path, title) if parent_path else title
            
            # 当前文件应该放在哪个文件夹下？
            # 如果当前节点有子节点，我们通常希望把当前节点的文件放在 parent_path 下，
            # 而它的子节点放在以它命名的文件夹下。
            # 或者，我们可以把当前节点的文件也放在以它命名的文件夹下？
            # 通常的逻辑是：章节文件放在父文件夹，小节文件放在章节文件夹。
            # 所以当前文件的 folder_path 就是 parent_path。
            
            result.append({
                "title": title,
                "page": page_number,
                "folder_path": parent_path,
            })

            # 如果下一个元素是 list，说明当前 item 有子节点
            if has_children:
                # 递归处理子节点，子节点的 parent_path 是 当前 parent_path + 当前 title
                child_parent_path = os.path.join(parent_path, sanitize_filename(title)) if parent_path else sanitize_filename(title)
                extract_bookmarks(outline[i + 1], reader, child_parent_path, result)
                i += 2 # 跳过已经处理的 list
            else:
                i += 1

        except Exception as e:
            print(f"  [警告] 无法解析书签 '{item}': {e}")
            i += 1

    return result


# ──────────────────────────────────────────────
# 2. 清理文件名中的非法字符
# ──────────────────────────────────────────────
def sanitize_filename(name: str, max_len: int = 80) -> str:
    """移除文件名中不合法的字符，截断过长名称。"""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip().strip('.')
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "untitled"


# ──────────────────────────────────────────────
# 3. 尝试清理损坏的 PDF 流
# ──────────────────────────────────────────────
def clean_pdf_stream(file_path):
    """尝试清理 %%EOF 之后的多余垃圾数据"""
    with open(file_path, 'rb') as f:
        data = f.read()
    
    eof_index = data.rfind(b'%%EOF')
    if eof_index != -1:
        clean_data = data[:eof_index + 5]
        return io.BytesIO(clean_data)
    return None


# ──────────────────────────────────────────────
# 4. 核心：按书签分割 PDF
# ──────────────────────────────────────────────
def split_pdf_by_bookmarks(
    pdf_path: str,
    output_dir: str = None,
    max_level: int = None, # 保留参数，但在新逻辑中可能需要调整
):
    """按书签拆分 PDF。

    返回拆分清单 list[dict]，每项包含：
        {"title", "rel_path", "start_page", "end_page", "page_count"}
    rel_path 为相对 output_dir 的 PDF 文件路径（以 / 分隔）。
    出错时返回空列表。
    """
    reader = None
    
    # 1. 尝试正常读取
    try:
        reader = PdfReader(pdf_path, strict=False)
    except (PdfReadError, PdfStreamError) as e:
        print(f"⚠️ 标准读取失败: {e}")
        print("🛠️ 正在尝试自动清理文件尾部多余数据...")
        
        cleaned_stream = clean_pdf_stream(pdf_path)
        if cleaned_stream:
            try:
                reader = PdfReader(cleaned_stream, strict=False)
                print("✅ 自动清理并读取成功！")
            except Exception as e2:
                print(f"❌ 自动清理后依然无法读取: {e2}")
                return []
        else:
            print("❌ 找不到 %%EOF 标记，文件可能已严重损坏。")
            return []

    total_pages = len(reader.pages)

    if not reader.outline:
        print("❌ 该 PDF 没有书签（大纲），无法按书签分割。")
        return []

    # 2. 提取所有书签
    bookmarks = extract_bookmarks(reader.outline, reader)

    # 过滤掉页码为 None 的无效书签
    bookmarks = [b for b in bookmarks if b["page"] is not None]

    if not bookmarks:
        print("❌ 过滤后没有符合条件的书签。")
        return []

    # 按页码排序并去重
    bookmarks.sort(key=lambda b: b["page"])
    seen_pages = set()
    unique_bookmarks = []
    for b in bookmarks:
        if b["page"] not in seen_pages:
            seen_pages.add(b["page"])
            unique_bookmarks.append(b)
    bookmarks = unique_bookmarks

    # 3. 准备输出目录（默认统一为 PDF/divided/）
    if output_dir is None:
        output_dir = DEFAULT_WORK_ROOT
    os.makedirs(output_dir, exist_ok=True)

    # 4. 打印书签信息
    print(f"📄 PDF: {pdf_path}")
    print(f"📑 总页数: {total_pages}")
    print(f"🔖 找到 {len(bookmarks)} 个有效书签:\n")
    for i, b in enumerate(bookmarks):
        level = b["folder_path"].count(os.sep) + 1 if b["folder_path"] else 0
        print(f"  {i+1:>3}. {'  ' * level}{b['title']}  →  第 {b['page']+1} 页  [{b['folder_path'] or '根目录'}]")
    print()

    # 5. 逐个书签拆分
    # 用于跟踪每个文件夹下已使用的文件名，防止重名覆盖
    used_filenames = {} 
    manifest = []

    for i, bm in enumerate(bookmarks):
        start_page = bm["page"]
        end_page = bookmarks[i + 1]["page"] if i + 1 < len(bookmarks) else total_pages

        if start_page >= end_page and i + 1 < len(bookmarks):
            print(f"  ⏭  跳过 '{bm['title']}'（页码范围为空）")
            continue

        writer = PdfWriter()
        for p in range(start_page, end_page):
            writer.add_page(reader.pages[p])

        # 构建输出路径
        safe_title = sanitize_filename(bm["title"])
        folder_path = os.path.join(output_dir, bm["folder_path"]) if bm["folder_path"] else output_dir
        os.makedirs(folder_path, exist_ok=True)

        # 处理同名文件
        base_filename = f"{safe_title}.pdf"
        if folder_path not in used_filenames:
            used_filenames[folder_path] = set()
            
        final_filename = base_filename
        counter = 1
        while final_filename in used_filenames[folder_path]:
            final_filename = f"{safe_title}_{counter}.pdf"
            counter += 1
        used_filenames[folder_path].add(final_filename)

        filepath = os.path.join(folder_path, final_filename)

        with open(filepath, "wb") as f:
            writer.write(f)

        page_count = end_page - start_page
        rel_path = os.path.relpath(filepath, output_dir)
        print(f"  ✅ {rel_path}  (第 {start_page+1}-{end_page} 页, 共 {page_count} 页)")

        manifest.append({
            "title": bm["title"],
            "rel_path": rel_path.replace(os.sep, "/"),
            "start_page": start_page,
            "end_page": end_page,
            "page_count": page_count,
        })

    print(f"\n🎉 完成！共生成 {len(manifest)} 个文件，保存在: {output_dir}")
    return manifest


# ──────────────────────────────────────────────
# 6. 命令行入口
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="按书签（大纲）分割 PDF 文件，自动创建层级文件夹",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python pdf.py book.pdf
  python pdf.py book.pdf -o ./chapters
        """,
    )
    parser.add_argument("pdf", help="输入的 PDF 文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出目录（默认: <pdf 名>_split/）")

    args = parser.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"❌ 文件不存在：{args.pdf}")
        return

    split_pdf_by_bookmarks(args.pdf, args.output)


if __name__ == "__main__":
    main()