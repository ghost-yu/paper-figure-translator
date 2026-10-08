# 来源与许可证记录

核对日期：2026-10-08。

当前仓库只有原创调研与设计文档，以及标准 AGPL v3 许可证正文。
尚未纳入第三方实现代码、模型、字体或运行时。
本项目原创内容采用 AGPL-3.0-only；后续纳入的第三方文件保留其各自适用的许可证和版权声明。

| 参考来源 | 核对到的许可证 | 当前使用状态 |
| --- | --- | --- |
| PDFMathTranslate/PDFMathTranslate | [AGPL v3](https://github.com/PDFMathTranslate/PDFMathTranslate/blob/main/LICENSE) | 阅读源码；尚未复制实现 |
| Antratech-Studios/manga-translator | [GPL v3](https://github.com/Antratech-Studios/manga-translator/blob/main/LICENSE) | 阅读流程；尚未复制实现 |
| allenai/pdffigures2 | [Apache 2.0](https://github.com/allenai/pdffigures2/blob/master/LICENSE.txt) | 阅读图表抽取；尚未复制实现 |
| FertayLageeze/translate-academic-pdf | [MIT](https://github.com/FertayLageeze/translate-academic-pdf/blob/main/LICENSE) | 阅读文字标签回填；尚未复制实现 |
| AaronGIG/pdf2zh-desktop | 未在仓库顶层检测到独立 LICENSE 文件 | 阅读实现；不据公开可见性认定全部新增代码可以复用 |

pdf2zh-desktop 包含多种第三方包，其各自许可证不能自动授权桌面版作者新增的 UI/工作线程代码。
需要复用其中实现时，应逐文件确认原始来源与适用许可证；授权未明确的新增部分先独立实现。

引入代码时记录：原仓库、固定提交、原路径、复制后的路径、修改摘要、版权声明与许可证文件。
不删除上游声明，也不将 GPL/AGPL 文件改标为 MIT。
发布包包含的 OCR 模型、中文字体和运行时另行建立许可证清单。
