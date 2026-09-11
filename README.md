# translate-academic-pdf-zh

把英文学术论文 PDF 翻译成逐页中英对照 PDF 的 Codex Skill。

每一页先保留英文原页，再生成对应的中文页，并尽量保留原来的页面尺寸、分栏、图片、表格、公式、题注和参考文献。
翻译与审校一般由运行该 Skill 的模型完成。

[![Tests](https://github.com/woai66/translate-academic-pdf-zh/actions/workflows/test.yml/badge.svg)](https://github.com/woai66/translate-academic-pdf-zh/actions/workflows/test.yml)

## 安装

### 安装到用户 Skill 目录（推荐）

Windows PowerShell：

```powershell
$skillDir = Join-Path $HOME ".codex\skills\translate-academic-pdf-zh"
git clone https://github.com/woai66/translate-academic-pdf-zh.git $skillDir
```

macOS / Linux：

```bash
git clone https://github.com/woai66/translate-academic-pdf-zh.git ~/.codex/skills/translate-academic-pdf-zh
```

### 安装到自定义 Codex 目录

如果你设置了 `CODEX_HOME`，把仓库克隆到：

```text
$CODEX_HOME/skills/translate-academic-pdf-zh
```

Windows 也可以从 [Releases](https://github.com/woai66/translate-academic-pdf-zh/releases) 下载 ZIP，解压后将文件夹放入：

```text
%USERPROFILE%\.codex\skills\translate-academic-pdf-zh
```

安装后重新打开 Codex，让它加载新的 Skill。

## 使用

把论文交给 Codex，然后直接说：

```text
使用 $translate-academic-pdf-zh 翻译这篇英文论文。
请保留英文原页，生成逐页中英对照 PDF，并完成版式和内容检查。
```

也可以直接说：

```text
调用 translate-academic-pdf-zh，把我上传的论文制作成中英对照 PDF。
```

你不需要自己运行 Python 脚本、制作清单或填写配置。Codex 会根据论文情况完成翻译、排版、检查和修正，并在完成后告诉你最终 PDF 的位置、页数和检查结果。

## 完成标准

Codex 会在交付前检查：

- 英文原页和中文页是否按顺序交错排列。
- 页面尺寸、图片、表格、公式和题注是否保留。
- 参考文献是否保持英文。
- 是否存在漏译、文字溢出、空白页、引用或数字异常。
- 渲染后的页面是否需要人工修正。

扫描件如果没有文字层，需要先进行 OCR。复杂图表、非常规分栏和混合公式页面可能需要人工复核。自动检查通过不代表译文在所有论文上都绝对无误。

## 许可证

本项目使用 [AGPL-3.0-or-later](LICENSE)。
