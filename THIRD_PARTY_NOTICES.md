# 来源与许可证记录

本项目原创 PDF、API 与界面代码使用 AGPL-3.0-only。下列第三方源文件保留原许可证，不改标为本项目原创。

## 已引入 Comic Translate 代码

来源：https://github.com/ogkalu2/comic-translate

固定提交：`8977b91a4f7a40c3917c5a268e9e7d78e1d818da`。

作者项目：ogkalu2 / Comic Translate 及其贡献者。许可证 Apache-2.0，完整正文保存在 `licenses/comic-translate-Apache-2.0.txt`。

| 原路径与函数 | 本项目路径 | 修改 |
| --- | --- | --- |
| modules/detection/utils/content.py：detect_content_mask_in_bbox、_mask_from_component_stats | paper_figures/vendor/comic_mask.py | 提取两个函数；imkit 的灰度/连通组件及 mahotas Otsu 改为已有 OpenCV 对应接口 |
| modules/rendering/render.py：_wrap_no_space_text_greedily、pil_word_wrap | paper_figures/vendor/comic_render.py | 提取两个函数；PIL 排版使用上游中文逐字符换行函数，移除 Qt 依赖 |
| modules/inpainting/mi_gan.py：MIGAN.forward 的 ONNX pipeline 分支 | paper_figures/vendor/comic_migan.py | 提取 pipeline 分支为独立函数，传入现有 CPU ONNX session |

每个文件头记录上游、固定提交、许可及修改。没有复制整套桌面 UI、模型下载框架或本地翻译模型。

## 可选本地 MI-GAN 权重

来自 Picsart AI Research 作者模型仓库 `andraniksargsyan/migan`，固定修订 `406830d0fa60666da0071c342ad2fbc8f30c5c64`。ONNX pipeline 文件约 26.78 MiB；SHA-256 在 `tools/setup_migan.py` 校验。该模型仓库提供 MIT 许可，安装时保留其 LICENSE。

模型仅下载到 Git 忽略的 workspace/models，不随本仓库上传。纯色背景默认使用像素掩膜及背景色清理；复杂背景的模型修补需要人工复查。

中文字体使用本机已安装字体，或 PyMuPDF 自带 CJK 字体；没有复制或分发 Microsoft 字体文件。OCR、PDF、图像处理及界面依赖遵循其各自许可证。

## 仅参考、未复制实现

PDFMathTranslate（AGPL v3）、manga-image-translator（GPL v3）、PDFFigures2（Apache 2.0）、translate-academic-pdf（MIT）用于流程调研。

AaronGIG/pdf2zh-desktop 未检测到独立根 LICENSE；未复制作者新增 UI 或工作线程代码。
