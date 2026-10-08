# Paper Figure Translator

翻译论文 PDF 图表内部的英文标签，再把中文写回原来的图表位置。支持原生文字、位图文字和混合架构图；不重新翻译正文。

## 启动

在现有 pdf2zh Windows 包旁的本项目目录，双击 `start.cmd`。界面地址为 http://127.0.0.1:7868 。复用现有运行时、轻量 RapidOCR 和本地版面模型，无需本地大语言模型。

独立安装：Python 3.12 环境运行 `python -m pip install -e .`，再运行 `paper-figures`。版面模型不自动下载；没有本地模型时可使用手动框选。

## 使用

1. 上传论文 PDF，填写页码（例如 `2,4-6`）。
2. 识别图内文字；自动定位不准时，在页面预览点选图框的两个角。
3. 检查原文与选中项，可改正 OCR 或直接填写译文。
4. 翻译并生成中文版 PDF、原文与译文交替排列的 PDF 和处理报告。

默认只读复用本机 PDFMathTranslate 配置。也可在界面填写兼容 OpenAI 格式的 API。密钥不保存到项目文件，不提交到 Git；本地输入、缓存、预览与输出均忽略。

每张图默认附带图注及附近正文给 API，可添加论文背景，也可关闭上下文。模型根据这些信息决定是否保留 ViT 等名称；**没有本地术语表或缩写替换规则**。发送的是图内标签和有限上下文，不是整篇 PDF。

## 当前限制

第一版适合白底、纯色底示意图。复杂背景、文字与曲线交叠、旋转标签或无法容纳的译文会保留原文并记录原因。OCR、翻译和排版仍需人工检查；不能保证任意论文图自动达到出版质量。

对损坏的 PDF 文字映射，使用 OCR 校验，并同时清理可见像素与原文字层，避免英文残留。正文和未选页保留，原 PDF 不覆盖。

## 开发与来源

运行测试：`python -m unittest discover -s tests -v`。提交前运行 `python tools/check_secrets.py --history`。

- [源码调研](docs/research.md)
- [实现与限制](docs/design.md)
- [验证记录](docs/validation.md)
- [第三方许可](THIRD_PARTY_NOTICES.md)

参考 PDFMathTranslate、pdf2zh-desktop、manga-translator、PDFFigures2 等实现路径。当前应用代码为原创实现，没有复制许可不明确的桌面端代码，也没有上传第三方模型或运行时。

本项目使用 [AGPL-3.0-only](LICENSE)。
