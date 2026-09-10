# translate-academic-pdf-zh

将英文学术 PDF 制作为逐页中英对照稿的 Codex Skill。
每页英文原稿之后插入一页中文复刻页，尽量保留原来的分栏、图表、公式与页面尺寸。

[![Tests](https://github.com/woai66/translate-academic-pdf-zh/actions/workflows/test.yml/badge.svg)](https://github.com/woai66/translate-academic-pdf-zh/actions/workflows/test.yml)

它由 Skill 指令、排版脚本、离线译文接口和三组自动检查组成。
**翻译与审校由运行 Skill 的模型或人工完成；Python 脚本负责排版与检查。**
自动检查是辅助工具，不能证明任何论文都不存在漏译、误译或版式问题。

## 安装

需要 Python 3.11+。在任意工作目录执行：

```sh
git clone https://github.com/woai66/translate-academic-pdf-zh.git
cd translate-academic-pdf-zh
python -m venv .venv
```

激活虚拟环境：Windows PowerShell 使用 `.venv\Scripts\Activate.ps1`；
macOS / Linux 使用 `source .venv/bin/activate`。然后安装依赖：

```sh
python -m pip install -r requirements.txt
```

将仓库目录复制到 `~/.codex/skills/translate-academic-pdf-zh`，或直接克隆到这个位置。
如果已安装旧版，先备份旧目录，再替换。不要把私有论文、译文缓存或整个虚拟环境复制进去。
安装后开启新的 Codex 任务并调用：

> 使用 $translate-academic-pdf-zh 翻译这篇英文论文，保留原版式并完成逐页验收。

脚本使用 PyMuPDF 提供的内置字体，不依赖 Windows 字体目录。
最终渲染需要另装 Poppler：Ubuntu/Debian 安装 `poppler-utils`，macOS 可用 `brew install poppler`；
Windows 安装 Poppler 后将 `pdftoppm.exe` 放入 PATH，或向渲染脚本传入 `--pdftoppm` 的完整路径。

## 先运行离线演示

```sh
python -m unittest discover -s tests -v
python examples/run_demo.py
python scripts/render_pdf_pages.py --manifest tmp/demo/manifest.json --render-root tmp/demo-render
python scripts/qa_rendered_pages.py --manifest tmp/demo/manifest.json --render-root tmp/demo-render --report tmp/demo-pixel.json
```

演示生成一篇自制的 3 页测试论文和 6 页中英对照稿，包括图、公式、双栏参考文献、附录和旋转页。
不下载论文，不调用外部翻译服务。输出目录必须是新目录，重复演示时请换用 `--output-dir`。

## 翻译自己的论文

1. 在工作目录创建 `manifest.json`。相对路径均相对于清单文件，而非脚本所在目录。

```json
{
  "papers": [
    {
      "id": "paper-a",
      "source": "input/paper.pdf",
      "output": "output/pdf/paper_bilingual.pdf",
      "title_en": "Exact English Title",
      "title_zh": "经过审校的中文题名",
      "translations": "tmp/paper-a.translations.json",
      "skip_first_pages": 0,
      "preserve_regions": []
    }
  ]
}
```

2. 导出待译文本。清单中的 `translations` 文件此时可以尚不存在。

```sh
python scripts/layout_preserving_bilingual_pdf.py --manifest manifest.json --id paper-a --export-text tmp/paper-a-source.json
```

3. 由 Codex 或人工填写导出的 JSON 值，保存到清单指定的 `tmp/paper-a.translations.json`。
键是规范化的原文块，值是完整中文译文。保留键、数字、公式、引用和技术名词；跨栏断句需要结合整页审校。
空字符串代表尚未翻译，生成时会报错。正式中文题名通过 `title_zh` 提供；可用 `\n` 指定经审校的断行。

4. 生成和检查：

```sh
python scripts/layout_preserving_bilingual_pdf.py --manifest manifest.json --cache-dir tmp/cache --report tmp/generation.json
python scripts/qa_bilingual_pdfs.py --manifest manifest.json --report tmp/structure.json
python scripts/qa_translation_content.py --manifest manifest.json --report tmp/content.json
python scripts/render_pdf_pages.py --manifest manifest.json --render-root tmp/render-v1
python scripts/qa_rendered_pages.py --manifest manifest.json --render-root tmp/render-v1 --report tmp/pixel.json
```

多篇论文使用不同的 `id` 和输出路径。所有步骤都支持 `--id` 选择论文。
使用 `--output-tag _reviewed` 时，生成、结构 QA、内容 QA、渲染和像素 QA 必须传入相同后缀。
QA 的错误或警告都会返回非零退出码。排版溢出不会覆盖已有最终 PDF。
渲染器记录 PDF 指纹；像素 QA 会拒绝旧文件的渲染结果。

独立处理单篇 PDF 也可使用 `--source`、`--output`、`--title-en`、`--title-zh` 和 `--translations`。
完整参数见各脚本的 `--help`。详细验收约定见 [quality-standard.md](references/quality-standard.md)。

## 保护图表和复杂区域

独立公式、小标签、非水平文字、参考文献条目通常保持原样。
位图内部文字自动保护。复杂矢量图、伪代码、混合表格应在清单中明确指定保护区域：

```json
"preserve_regions": [
  {"page": 4, "bbox": [45, 210, 290, 440]}
]
```

页码从 1 开始。坐标单位为 PDF 点，使用去除页面旋转后的页面坐标。
与区域相交的整个文本块都会保留，应在渲染图上核对范围。

## 可选在线后端（实验性）

默认不会向额外的翻译网站发送文本。加入 `--allow-network` 后，缺少人工译文或缓存的正文块会发送到
Google 的网页翻译接口；它不是官方付费 API，也没有可用性承诺。
连接/读取超时分别设置为 10/30 秒，不自动重试限流和服务错误。
不能访问该服务时请使用离线译文，不需要配置 API Key。

此版本在发布机器上的联网测试遇到网络不可达，**未验证真实服务成功返回**；离线流程、请求解析、超时参数、
错误停止和占位符保护使用自动测试验证。模型本身的数据处理方式仍取决于你使用的 Codex/模型环境。

## 已知范围

- 面向有文本层、常规单栏或双栏的英文论文；不内置 OCR。无文本层页面会要求先 OCR 或人工处理。
- 标题、正文、表格和参考文献识别使用启发式规则。混合文本块、非常规多栏、复杂行内数学可能需要手工调整。
- 保持英文页的显示与文本内容，不承诺输出 PDF 的字节与原文件相同。目录映射到英文页；跨页链接、交互表单、
  数字签名与 PDF/A 合规性不在当前保证范围内。
- 中文使用内置通用字体，字体风格和粗体效果未必与原稿一致；过密的源版式可能需要更短的审校译文。
- QA 与生成器共用部分文本区域判断，可能同时漏判。必须逐页视觉检查，并对照全文核查漏译、数字和术语。
- 不承诺任何输入均能自动达到出版质量。当前版本是可审校的辅助流程。

## 许可证

代码与 Skill 指令采用 [AGPL-3.0-or-later](LICENSE)。Copyright (C) 2026 woai66。
PyMuPDF 使用 AGPL 或商业双重许可；本项目选择与其开源使用方式兼容的 AGPL。
依赖包及其字体保留各自许可证；本仓库不分发系统字体、第三方论文、用户译文或缓存。

缺陷报告请附最小可复现的自制样例、Python/依赖版本和对应 QA 结果，避免上传无权公开的论文。
