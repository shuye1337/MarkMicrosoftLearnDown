# direct_2D_docs

将 Microsoft Direct2D 官方文档的 PDF 转换为结构化、可离线阅读的 Markdown 文档集的工具链。

工具会按 PDF 书签把整份文档拆分为一份份章节文件，把文档内指向 learn.microsoft.com 的超链接重映射为本地相对路径，再逐章转换为 Markdown（同时提取图片），并支持在文档更新后**仅重新处理发生变化的章节**。

## 功能特性

- **按书签拆分**：依据 PDF 大纲（Outline）递归拆分，自动按书签层级创建目录结构；内置对损坏 PDF 尾部数据的自动清理。
- **超链接重映射**：借助目录映射 JSON 的 `href → toc_title` 映射，把文档内的官方站点链接替换为拆分后本地 PDF 的相对路径。
- **PDF → Markdown**：基于字号 / 字体 / 位置启发式识别标题、正文、列表、代码块与内联样式（粗体 / 斜体 / 等宽），提取页面图片到 `PIC/`，并剔除页面反馈区等噪声。
- **增量更新**：为已处理章节记录文本哈希基线（`.manifest.json`），对比新 PDF 得出新增 / 修改 / 删除章节，仅对变化章节执行重映射与转换。
- **产物统计**：按文件大小、单文件页数、书签页数间隔等维度对拆分产物做统计诊断。

## 环境要求

- Python ≥ 3.13
- 依赖：[`pymupdf`](https://pymupdf.readthedocs.io/)（fitz）、[`pypdf`](https://pypdf.readthedocs.io/)

推荐使用 [uv](https://github.com/astral-sh/uv) 管理环境：

```powershell
uv sync
```

或使用 pip：

```powershell
pip install pymupdf pypdf
```

## 目录结构

```
direct_2D_docs/
├── src/                 # 源码
│   ├── main.py          # 交互式向导入口（串联全流程 / 增量更新）
│   ├── splitter.py      # 按书签拆分 PDF
│   ├── relinker.py      # 超链接重映射
│   ├── converter.py     # PDF → Markdown 转换
│   ├── differ.py        # 章节差异检测与基线管理
│   └── stats.py         # 拆分产物统计
├── toc.json             # 官方文档目录映射 JSON（href → 标题映射来源）
├── PDF/
│   ├── divided/         # 拆分产物（工作根目录，含 .manifest.json 基线）
│   ├── backup/          # 重映射前的 PDF 备份
│   └── _incoming/       # 增量更新时的临时拆分目录
├── MD/                  # Markdown 输出（镜像 PDF/divided 目录结构）
├── PIC/                 # 提取的图片（镜像目录结构）
└── example/             # 单章示例（PDF 与对应 Markdown）
```

## 快速开始

运行交互式向导，按提示选择模式：

```powershell
python src/main.py
```

- **[1] 全量处理**：输入完整 PDF 路径 → 按书签拆分 → （可选）统计 → 超链接重映射 → 转 Markdown → 记录基线清单。
- **[2] 增量更新**：输入新版 PDF 路径 → 与基线对比找出变化章节 → 仅对变化章节执行重映射 + 转换 → 更新基线清单。

> 增量更新前需先完成过一次全量处理，以生成 `PDF/divided/.manifest.json` 基线。

## 单模块命令行用法

各模块也可独立运行：

```powershell
# 按书签拆分 PDF
python src/splitter.py input.pdf -o PDF/divided

# 超链接重映射（默认读取项目根目录映射 JSON，处理 PDF/divided）
python src/relinker.py --toc toc.json --url-prefix "https://learn.microsoft.com/zh-cn/windows/win32/Direct2D/"

# PDF → Markdown（PDF/divided → MD/，图片 → PIC/）
python src/converter.py

# 生成基线清单 / 对比新 PDF
python src/differ.py build --root PDF/divided
python src/differ.py diff new.pdf --root PDF/divided

# 统计：最大文件 / 页数最多的文件 / 书签页数间隔
python src/stats.py largest PDF/divided -n 10
python src/stats.py pages PDF/divided -n 10
python src/stats.py gap input.pdf
```

## 处理流程

```
完整 PDF
   │  splitter：按书签拆分
   ▼
PDF/divided/…（章节 PDF，镜像书签层级）
   │  relinker：站点链接 → 本地相对路径（原文件备份至 PDF/backup）
   ▼
重映射后的 PDF
   │  converter：解析版面 → Markdown（图片提取至 PIC/）
   ▼
MD/…（Markdown 文档集）
   │  differ：记录文本哈希基线 .manifest.json
   ▼
增量更新时：新 PDF → 拆分至 PDF/_incoming → 对比基线 → 仅处理变化章节
```

## 说明

- 转换基于启发式规则，复杂版面（多列、表格、混排代码）可能需要人工校订。
- 超链接重映射会以增量方式写回原 PDF，执行前会将原文件备份到 `PDF/backup/`。
- 目录映射 JSON 为链接重映射的映射来源，来自官方文档目录树，其 `href` 需与拆分产物的目录 / 文件名一致才能命中。
