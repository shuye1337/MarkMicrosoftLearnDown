#!/usr/bin/env python3
"""
converter.py - 将 PDF/divided 下的所有 PDF 转换为 Markdown 格式。

- MD 输出到 MD/ 目录（镜像目录结构）
- 图片提取到 PIC/ 目录（镜像目录结构）
- 去除反馈部分
- 去除 #page-0 链接，保留链接文字
- 本地 PDF 引用转为 .md 引用
"""

import re
import sys
from collections import Counter
from pathlib import Path

import fitz  # pymupdf

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PDF_ROOT = BASE_DIR / "PDF" / "divided"
DEFAULT_MD_ROOT = BASE_DIR / "MD"
DEFAULT_PIC_ROOT = BASE_DIR / "PIC"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ── 常量 ───────────────────────────────────────────────────────
MONOSPACE_FONTS = {"Courier", "CourierNew", "Consolas", "Monaco",
                   "LucidaConsole", "SourceCodePro", "DejaVuSansMono",
                   "Menlo", "mono", "monospace"}
BOLD_MASK = 2**4  # 16
ITALIC_MASK = 2**1  # 2
H1_RATIO = 2.0
H2_RATIO = 1.7
H3_RATIO = 1.35
X_TOLERANCE = 6.0
Y_MERGE_GAP = 8.0
FEEDBACK_KEYWORDS = ["反馈", "此页面是否有帮助", "获取帮助", "Microsoft Q&A",
                     "Q&A", "本页内容"]
NOTE_KEYWORDS = ["备注", "注意", "重要", "警告", "提示", "Note:", "Warning:",
                 "Important:", "Tip:"]
LEADIN_PATTERN = re.compile(r"(包括|如下|以下|下列)[：:]\s*$")
METADATA_KEYWORDS = {"项目", "文章", "Article"}


# ── 工具函数 ───────────────────────────────────────────────────

def is_mono(font: str) -> bool:
    name = font.replace("-", "").replace("_", "").replace(" ", "").lower()
    return any(m.lower() in name for m in MONOSPACE_FONTS)


def is_bold(flags: int) -> bool:
    return bool(flags & BOLD_MASK)


def is_italic(flags: int) -> bool:
    return bool(flags & ITALIC_MASK)


def clean_text(text: str) -> str:
    text = text.replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r" {2,}", " ", text).strip()


# ── Span / Block 数据 ──────────────────────────────────────────

class Span:
    __slots__ = ("text", "font", "size", "flags", "color", "mono")
    def __init__(self, d: dict):
        self.text = d["text"]
        self.font = d["font"]
        self.size = d["size"]
        self.flags = d["flags"]
        self.color = d["color"]
        self.mono = is_mono(self.font)


class Block:
    __slots__ = ("page", "bbox", "spans", "text", "size", "bold", "mono",
                 "block_type", "level", "marker", "links", "note",
                 "page_links")
    def __init__(self, page_num: int, raw: dict, page_links: list[dict]):
        self.page = page_num
        self.bbox = raw["bbox"]
        self.spans: list[Span] = []
        self.links: list[dict] = []
        self.note = False
        self.page_links = page_links

        if raw["type"] == 0 and raw.get("lines"):
            for line in raw["lines"]:
                for sp in line["spans"]:
                    self.spans.append(Span(sp))

        texts = [s.text for s in self.spans]
        self.text = "".join(texts)
        self.size = self.spans[0].size if self.spans else 0
        non_empty = [s for s in self.spans if s.text.strip()]
        self.bold = all(is_bold(s.flags) for s in non_empty) if non_empty else False
        self.mono = all(s.mono for s in non_empty) if non_empty else False

        self.block_type = "p"
        self.level = 0
        self.marker = ""

    @property
    def x0(self): return self.bbox[0]
    @property
    def y0(self): return self.bbox[1]
    @property
    def x1(self): return self.bbox[2]
    @property
    def y1(self): return self.bbox[3]
    @property
    def clean(self) -> str: return clean_text(self.text)


# ── 主转换器 ───────────────────────────────────────────────────

class Converter:
    def __init__(self, pdf_root=None, md_root=None, pic_root=None):
        self.pdf_root = Path(pdf_root) if pdf_root else DEFAULT_PDF_ROOT
        self.md_root = Path(md_root) if md_root else DEFAULT_MD_ROOT
        self.pic_root = Path(pic_root) if pic_root else DEFAULT_PIC_ROOT
        self.stats = {"ok": 0, "err": 0}

    def run(self, restrict_to=None):
        """转换 pdf_root 下的 PDF。

        restrict_to 为章节相对路径集合（以 / 分隔，相对 pdf_root）时，
        仅转换这些 PDF，实现增量更新。
        """
        if restrict_to is not None:
            pdfs = []
            for rel in sorted(restrict_to):
                p = self.pdf_root / rel
                if p.is_file():
                    pdfs.append(p)
                else:
                    print(f"[跳过] 未找到章节文件：{rel}")
        else:
            pdfs = sorted(self.pdf_root.rglob("*.pdf"))
        print(f"找到 {len(pdfs)} 个 PDF 文件")
        for i, p in enumerate(pdfs):
            rel = p.relative_to(self.pdf_root)
            try:
                print(f"[{i+1}/{len(pdfs)}] {rel} ...", end=" ", flush=True)
                self.convert(p)
                self.stats["ok"] += 1
                print("OK")
            except Exception as e:
                self.stats["err"] += 1
                print(f"ERR: {e}")
        print(f"\n完成: 成功 {self.stats['ok']}, 错误 {self.stats['err']}")

    def convert(self, path: Path):
        doc = fitz.open(str(path))
        try:
            blocks, images = self._extract(doc, path)
            if not blocks:
                return
            body_size = self._body_size(blocks)
            margin = self._margin(blocks)
            self._classify(blocks, body_size, margin)
            md = self._render(blocks, images, path)
            rel = path.relative_to(self.pdf_root)
            out = self.md_root / rel.with_suffix(".md")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(md) + "\n", encoding="utf-8")
        finally:
            doc.close()

    # ── 提取 ──────────────────────────────────────────────

    def _extract(self, doc: fitz.Document, path: Path
                 ) -> tuple[list[Block], dict[int, list[str]]]:
        blocks: list[Block] = []
        images: dict[int, list[str]] = {}
        rel = path.relative_to(self.pdf_root)

        for pn in range(doc.page_count):
            page = doc[pn]
            page_links = page.get_links()
            for raw in page.get_text("dict")["blocks"]:
                if raw["type"] != 0:
                    continue
                b = Block(pn, raw, page_links)
                if not b.text.strip():
                    continue
                # 检测 "备注" 类块
                if any(kw in b.clean for kw in NOTE_KEYWORDS) and b.size < 14:
                    b.note = True
                blocks.append(b)

            # 图片
            imgs = doc.get_page_images(pn)
            if imgs:
                sub = self.pic_root / rel.parent / rel.stem
                sub.mkdir(parents=True, exist_ok=True)
                page_imgs: list[str] = []
                for idx, info in enumerate(imgs):
                    try:
                        base = doc.extract_image(info[0])
                        name = f"img_p{pn+1}_{idx+1}.{base['ext']}"
                        (sub / name).write_bytes(base["image"])
                        page_imgs.append(name)
                    except Exception:
                        pass
                if page_imgs:
                    images[pn] = page_imgs

        blocks.sort(key=lambda b: (b.page, b.y0, b.x0))
        return blocks, images

    # ── 分析 ──────────────────────────────────────────────

    def _body_size(self, blocks: list[Block]) -> float:
        # 只统计看起来像正文的块：非等宽、非粗体、文本较长
        sizes = [b.size for b in blocks
                 if 9 < b.size < 15 and not b.bold and not b.mono
                 and len(b.clean) > 10]
        if not sizes:
            sizes = [b.size for b in blocks if 9 < b.size < 15 and not b.mono
                     and len(b.clean) > 5]
        if not sizes:
            return 12.0
        return Counter(round(s, 1) for s in sizes).most_common(1)[0][0]

    def _margin(self, blocks: list[Block]) -> float:
        xs = [b.x0 for b in blocks if 30 < b.x0 < 300]
        if not xs:
            return 64.0
        return Counter(round(x, 1) for x in xs).most_common(1)[0][0]

    def _classify(self, blocks: list[Block], body: float, margin: float):
        in_list = False
        for i, b in enumerate(blocks):
            t = b.clean
            # 反馈
            if self._is_feedback(b):
                b.block_type = "skip"
                in_list = False
                continue
            # 标题
            if self._is_heading(b, body):
                r = b.size / body if body > 0 else 0
                if r >= H1_RATIO:
                    b.level = 1
                elif r >= H2_RATIO:
                    b.level = 2
                elif r >= H3_RATIO:
                    b.level = 3
                else:
                    b.level = 4
                b.block_type = "h"
                in_list = False
                continue
            # 代码：等宽字体块，或多数span等宽
            if self._is_code(b):
                b.block_type = "code"
                in_list = False
                continue
            # 列表标记
            mk = self._list_marker(t, b.x0, margin)
            if mk:
                b.block_type = "li"
                b.marker = mk
                in_list = True
                continue
            # 列表延续：在列表上下文中 + 缩进
            if in_list and b.x0 - margin >= 18:
                b.block_type = "li"
                b.marker = "-"
                continue
            in_list = False
            # 引导列表：前一块以"包括："等结尾 + 当前块缩进
            indent = b.x0 - margin
            if indent >= 18 and i > 0:
                prev = blocks[i - 1]
                if prev.block_type != "skip" and LEADIN_PATTERN.search(prev.clean):
                    b.block_type = "li"
                    b.marker = "-"
                    in_list = True
                    continue
            b.block_type = "p"

    def _is_code(self, b: Block) -> bool:
        """检测代码块：多数span使用等宽字体，或文本以常见代码模式开头。"""
        t = b.clean
        if len(t) < 5:
            return False
        non_empty = [s for s in b.spans if s.text.strip()]
        if not non_empty:
            return False
        mono_count = sum(1 for s in non_empty if s.mono)
        if mono_count >= len(non_empty) * 0.5:
            return True
        # 常见代码行开头
        code_starts = ("//", "#", "/*", "*/", "    ", "\t", "using ", "#include",
                       "class ", "struct ", "enum ", "int ", "void ", "HRESULT",
                       "if ", "for ", "while ", "return ", "#define", "#pragma")
        if any(t.strip().startswith(cs) for cs in code_starts):
            return True
        return False

    def _is_feedback(self, b: Block) -> bool:
        t = b.clean
        for kw in FEEDBACK_KEYWORDS:
            if kw in t:
                return True
        # 单独的是/否按钮，或包含这些字且很短
        if len(t) <= 4:
            for c in "是否":
                if c in t:
                    return True
        return False

    def _is_heading(self, b: Block, body: float) -> bool:
        if b.size <= 0:
            return False
        # 太长的文本不太可能是标题
        if len(b.clean) > 80:
            return False
        r = b.size / body if body > 0 else 0
        return (r >= H3_RATIO and b.bold) or r >= H1_RATIO

    def _list_marker(self, text: str, x0: float, margin: float) -> str:
        """检测列表标记。返回 '-' / '1.' 等或空字符串。"""
        indent = x0 - margin
        t = text.strip()
        # 无序列表标记
        m = re.match(r"^[●•○■□▪▫►→](?=\s)", t)
        if m:
            return "-"
        # 有序列表
        m = re.match(r"^(\d+)[\.\)、](?=\s)", t)
        if m:
            return f"{m.group(1)}."
        # 带有缩进且无标题特征 → 可能是无标记列表项
        # 仅当缩进明显（≥18pt）且前后文支持时才判定
        return ""

    # ── 渲染 ──────────────────────────────────────────────

    def _render(self, blocks: list[Block], images: dict[int, list[str]],
                path: Path) -> list[str]:
        lines: list[str] = []
        filtered = [b for b in blocks if b.block_type != "skip"]

        # 同类型段落合并
        merged = self._merge(filtered)

        # 按页分组
        pages: dict[int, list[Block]] = {}
        for b in merged:
            pages.setdefault(b.page, []).append(b)

        rel = path.relative_to(self.pdf_root)

        for pn in sorted(pages):
            # 页面图片放在页面正文之前（紧随页面顶部标题之后）
            page_blocks = pages[pn]
            img_inserted = False

            for i, b in enumerate(page_blocks):
                # 标题之后立即插入图片
                if not img_inserted and pn in images and b.block_type == "h":
                    for iname in images[pn]:
                        ref = (rel.parent / rel.stem / iname).as_posix()
                        lines.append(f"![图片]({ref})")
                        lines.append("")
                    img_inserted = True

                if b.block_type == "h":
                    lines.append(f"{'#' * b.level} {self._inline(b, path, no_bold=True)}")
                    lines.append("")
                elif b.block_type == "code":
                    lines.append(f"    {b.clean}")
                elif b.block_type == "li":
                    mk = b.marker or "-"
                    # 去除文本开头的列表标记（避免重复）
                    text = self._inline(b, path)
                    text = re.sub(r"^\d+[\.\)、]\s*", "", text).strip()
                    text = re.sub(r"^[●•○■□▪▫►→]\s*", "", text).strip()
                    lines.append(f"{mk} {text}")
                elif b.block_type == "p":
                    if self._is_metadata(b):
                        lines.append(f"**{self._inline(b, path, no_bold=True)}**")
                    else:
                        lines.append(self._inline(b, path))
                    lines.append("")

                # 为列表项之间添加空行分隔
                prev = page_blocks[i - 1] if i > 0 else None

            # 如果页面内有图片但还没插入（没有标题的情况），在开头插入
            if not img_inserted and pn in images:
                for iname in images[pn]:
                    ref = (rel.parent / rel.stem / iname).as_posix()
                    lines.append(f"![图片]({ref})")
                    lines.append("")

        # 空行清理
        result: list[str] = []
        prev_blank = False
        for line in lines:
            blank = (line == "")
            if blank and prev_blank:
                continue
            result.append(line)
            prev_blank = blank
        while result and result[0] == "":
            result.pop(0)
        while result and result[-1] == "":
            result.pop(-1)

        # 列表后加空行
        out: list[str] = []
        in_list = False
        for i, line in enumerate(result):
            is_li = bool(re.match(r"^\d+\. |^- ", line))
            if not is_li and in_list and line != "":
                out.append("")
            out.append(line)
            in_list = is_li
        return out

    def _merge(self, blocks: list[Block]) -> list[Block]:
        """合并相邻同类型块。"""
        if not blocks:
            return []
        result: list[Block] = [blocks[0]]
        for b in blocks[1:]:
            prev = result[-1]
            # 可合并条件：同类型、同页、x相近、不是标题/列表
            if (prev.block_type == b.block_type
                    and prev.block_type in ("p", "code")
                    and prev.page == b.page
                    and abs(prev.x0 - b.x0) < X_TOLERANCE):
                # 检查是否为特殊元数据行，不合并
                if self._is_metadata(prev) or self._is_metadata(b):
                    result.append(b)
                    continue
                prev.spans.extend(b.spans)
                prev.text += b.text
                prev.bbox = (prev.bbox[0], prev.bbox[1],
                             max(prev.bbox[2], b.bbox[2]), b.bbox[3])
            else:
                result.append(b)
        return result

    def _is_metadata(self, b: Block) -> bool:
        """检测元数据行（如 '项目 • 2023/06/13'）。"""
        t = b.clean
        # 字号明显小于正文
        if b.size <= 11 and any(kw in t for kw in METADATA_KEYWORDS):
            return True
        if "•" in t and b.size <= 11:
            return True
        return False

    # ── 内联格式化 ─────────────────────────────────────────

    def _inline(self, b: Block, path: Path, no_bold: bool = False) -> str:
        result: list[str] = []
        i = 0
        while i < len(b.spans):
            s = b.spans[i]
            txt = s.text
            if not txt.strip():
                result.append(txt)
                i += 1
                continue

            # 查找覆盖此 span 位置的链接
            link_uri = self._find_link_for_span(b, i)

            if link_uri:
                # 收集链接覆盖的所有连续 spans
                collected = [txt]
                j = i + 1
                while j < len(b.spans):
                    next_uri = self._find_link_for_span(b, j)
                    if next_uri and next_uri == link_uri:
                        collected.append(b.spans[j].text)
                        j += 1
                    else:
                        break
                display = "".join(collected).strip()
                if not display:
                    result.append(txt)
                    i += 1
                    continue

                if "#page-0" in link_uri or link_uri.startswith("#page="):
                    result.append(self._style(display, s, no_bold))
                else:
                    if link_uri.endswith(".pdf") and not link_uri.startswith(
                            ("http://", "https://", "ftp://")):
                        link_uri = link_uri[:-4] + ".md"
                    safe = link_uri.replace("(", "%28").replace(")", "%29")
                    result.append(f"[{self._style(display, s, no_bold)}]({safe})")
                i = j
            else:
                result.append(self._style(txt, s, no_bold))
                i += 1

        text = "".join(result)
        text = re.sub(r" {2,}", " ", text)
        text = text.replace("** **", " ")
        return text.strip()

    def _find_link_for_span(self, b: Block, span_idx: int) -> str:
        """查找覆盖指定 span 的链接 URI。"""
        if span_idx >= len(b.spans):
            return ""
        s = b.spans[span_idx]
        # 估算 span 在文本中的位置
        offset = sum(len(b.spans[k].text) for k in range(span_idx))
        span_width = len(s.text) * s.size * 0.5  # 粗略估计宽度
        # 构建 span 的大致矩形区域
        span_rect = fitz.Rect(
            b.x0 + offset * 0.3, b.y0,
            b.x0 + (offset + len(s.text)) * 0.3, b.y1
        )
        for link in b.page_links:
            uri = link.get("uri", "")
            if not uri:
                continue
            lr = fitz.Rect(link.get("from", ()))
            if lr.intersects(span_rect) or lr.intersects(fitz.Rect(b.bbox)):
                return uri
        return ""

    def _style(self, text: str, s: Span, no_bold: bool = False) -> str:
        t = text
        if no_bold:
            return t
        b = is_bold(s.flags)
        it = is_italic(s.flags)
        if b and it:
            t = f"***{t}***"
        elif b:
            t = f"**{t}**"
        elif it and t.strip():
            t = f"*{t}*"
        if s.mono and t.strip():
            t = f"`{t}`"
        return t


# ── 入口 ───────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("PDF -> Markdown 转换")
    print(f"源: {DEFAULT_PDF_ROOT}")
    print(f"输出: {DEFAULT_MD_ROOT}")
    print(f"图片: {DEFAULT_PIC_ROOT}")
    print("=" * 60)
    Converter().run()


if __name__ == "__main__":
    main()
