---
title: "使用 MinerU 解析题目文档"
format: html
execute:
  eval: false
---

脚本 `scripts/mineru_parse.py` 递归查找 PDF、DOC、DOCX，将原文件上传到 MinerU，等待解析后下载完整结果包，并解压 Markdown、图片及 JSON。需要 Python 3.11 或更新版本。

## 解析方式

默认使用精准解析 API 的 `vlm` 模型，开启公式和表格识别，语言为中文。对于 Word 文档应直接上传，官方接口已支持 DOC/DOCX，如果服务端转换失败，或结果中的公式、版式明显异常，则使用 Microsoft Word 将原文件导出为 PDF，确认显示正确后再上传 PDF。不要先将 Word 栅格化为图片。

默认不强制 OCR；遇到扫描件或错误文本层，可以加 `--ocr` 重新解析。不同参数会生成不同结果目录，便于比较。数学公式和表格仍应对照原文核对，模型输出不能保证完全正确。

依据：[MinerU API 文档](https://mineru.net/apiManage/docs)。使用 `/api/v4/file-urls/batch` 申请上传链接，PUT 上传后由服务端自动提交，再通过 `/api/v4/extract-results/batch/{batch_id}` 查询。本脚本每次只提交一个文件，依次处理，以便独立恢复和定位错误。

## 安装与运行

在项目根目录的 PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-mineru.txt
```

在 MinerU API 管理页创建 Token，再通过隐藏输入设置当前会话环境变量；不会写入脚本或项目文件：

```powershell
$mineruSecret = Read-Host 'MinerU API Token' -AsSecureString
$env:MINERU_API_TOKEN = [System.Net.NetworkCredential]::new('', $mineruSecret).Password
Remove-Variable mineruSecret
```

先查看将要上传的文件，再执行解析：

```powershell
.\.venv\Scripts\python.exe scripts/mineru_parse.py --dry-run
.\.venv\Scripts\python.exe scripts/mineru_parse.py
```

也可以指定一个或多个文件、目录；包含空格的路径需要引号：

```powershell
.\.venv\Scripts\python.exe scripts/mineru_parse.py "data/题目.pdf" "data/附件.docx"
.\.venv\Scripts\python.exe scripts/mineru_parse.py "data/题目" --ocr
.\.venv\Scripts\python.exe scripts/mineru_parse.py "data/题目" --output data/mineru-reparse
```

不指定路径时扫描整个项目，跳过 Git、虚拟环境、输出目录及 Word 临时文件。执行正式命令会将匹配的原文档发送到 MinerU。Token 只发送给 MinerU API，不发送给文件存储服务。

## 输出与恢复

默认输出到 `data/mineru/<原文件名>-<标识>/`。标识由源路径、内容哈希及解析参数生成，避免同名文件覆盖。目录内包含：

- `content/`：解压后的原始目录结构，其中 `full.md` 为 Markdown，图片保留在其原有相对位置。
- `result.zip`：完整解析结果包。
- `task.json`：源文件、哈希、解析参数、批次 ID 及结果路径，不保存 Token 或签名链接。

同样的命令再次执行时，已完成的结果会跳过；已成功上传的任务会继续查询。上传阶段被中断时，重跑可能创建新任务。默认每 5 秒查询一次，每个文件最多等待 30 分钟；可用 `--poll-interval` 和 `--wait-timeout` 调整。请求自身还有连接和读取超时，因此等待上限不是严格的总运行时限。

网络错误、HTTP 429 和常见服务端错误会对查询、上传、下载请求进行有限重试。创建任务不会自动重试。单个文档失败不会阻止其他文档处理；有失败时退出码为 1。服务端已经失败的任务需换一个 `--output` 目录重新提交；结果目录损坏或人工删除部分输出时也应使用新的输出目录。

本地校验文件非空且不超过 200 MB；200 页限制由服务端判断。无需安装本地 MinerU、Word 或 PDF 转换器。默认 `data/` 已被 Git 忽略。
