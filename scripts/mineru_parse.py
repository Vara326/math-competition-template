#!/usr/bin/env python3
"""上传 PDF/Word 到 MinerU 精准解析 API，下载 Markdown 和配套资源。"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import time
import zipfile

try:
    import requests
except ImportError:
    raise SystemExit("请先安装依赖：python -m pip install -r requirements-mineru.txt")

ROOT = Path(__file__).resolve().parents[1]
API = "https://mineru.net/api/v4"
EXTENSIONS = {".pdf", ".doc", ".docx"}
EXCLUDE = {".git", ".venv", "venv", "node_modules", "__pycache__"}


def request(method, url, **kwargs):
    """只重试读取和幂等上传；不自动重试创建任务，避免重复提交。"""
    for attempt in range(4):
        stream = kwargs.get("data")
        if hasattr(stream, "seek"):
            stream.seek(0)
        try:
            response = requests.request(method, url, timeout=(15, 120), **kwargs)
        except requests.RequestException:
            if method == "POST" or attempt == 3:
                raise RuntimeError("网络请求失败；请检查网络后重跑（签名链接和 Token 不输出）。") from None
        else:
            if response.ok:
                return response
            status = response.status_code
            response.close()
            if method == "POST" or status not in {429, 500, 502, 503, 504} or attempt == 3:
                raise RuntimeError(f"HTTP {status}；请检查 Token、额度和服务状态。")
        time.sleep(2 ** attempt)


def api(method, route, token, payload=None):
    with request(method, API + route, headers={"Authorization": f"Bearer {token}"},
                 json=payload) as response:
        result = response.json()
    if result.get("code") != 0:
        raise RuntimeError(f"MinerU 错误 {result.get('code')}: {result.get('msg')}")
    return result["data"]


def save_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def discover(inputs, output):
    files = set()
    for item in inputs:
        path = Path(item).resolve()
        if not path.exists():
            raise ValueError(f"路径不存在：{path}")
        if path.is_file():
            if path.suffix.lower() not in EXTENSIONS:
                raise ValueError(f"不支持的格式：{path}")
            files.add(path)
        else:
            for parent, dirs, names in os.walk(path):
                dirs[:] = [d for d in dirs if d not in EXCLUDE
                           and not (Path(parent) / d).resolve().is_relative_to(output)]
                for name in names:
                    candidate = Path(parent) / name
                    if candidate.suffix.lower() in EXTENSIONS and not name.startswith("~$"):
                        files.add(candidate.resolve())
    for path in files:
        if not 0 < path.stat().st_size <= 200 * 1024 * 1024:
            raise ValueError(f"文件为空或超过 200 MB：{path}")
    return sorted(files)


def download(url, destination):
    # 在临时目录完成下载与校验，避免半成品被当作成功结果。
    with tempfile.TemporaryDirectory(dir=destination) as scratch:
        scratch = Path(scratch)
        archive = scratch / "result.zip"
        with request("GET", url, stream=True) as response, archive.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                handle.write(chunk)
        unpacked = scratch / "content"
        unpacked.mkdir()
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                relative = PurePosixPath(member.filename)
                if (relative.is_absolute() or ".." in relative.parts
                        or "\\" in member.filename or ":" in member.filename
                        or (member.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("结果 ZIP 包含不安全路径。")
            package.extractall(unpacked)
        markdown = list(unpacked.rglob("*.md"))
        if not markdown:
            raise ValueError("解析结果中没有 Markdown 文件。")
        content = destination / "content"
        if content.exists():
            raise ValueError(f"结果目录已存在，请换一个输出目录：{content}")
        unpacked.rename(content)
        shutil.move(str(archive), destination / "result.zip")
    return [str(p.relative_to(unpacked)) for p in markdown]


def parse_file(source, options, token):
    config = {"model_version": options.model, "language": options.language,
              "enable_formula": True, "enable_table": True}
    with source.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    identity = hashlib.sha256((str(source) + digest + json.dumps(config)
                               + str(options.ocr)).encode()).hexdigest()[:16]
    destination = options.output / f"{source.name}-{identity}"
    destination.mkdir(parents=True, exist_ok=True)
    state_path = destination / "task.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    if state.get("markdown") and all((destination / "content" / p).is_file()
                                     for p in state["markdown"]):
        print(f"跳过已完成：{source}")
        return
    if not state.get("uploaded"):
        data = api("POST", "/file-urls/batch", token, {
            **config, "files": [{"name": source.name, "data_id": identity,
                                   "is_ocr": options.ocr}]})
        state = {"source": str(source), "sha256": digest, "config": config,
                 "is_ocr": options.ocr, "batch_id": data["batch_id"], "uploaded": False}
        save_state(state_path, state)
        urls = data["file_urls"]
        if len(urls) != 1:
            raise RuntimeError("MinerU 返回的上传链接数量不正确。")
        print(f"上传：{source.name}")
        # 对象存储使用签名 URL，不携带 API Token，不设置 Content-Type。
        with source.open("rb") as handle, request("PUT", urls[0], data=handle):
            pass
        state["uploaded"] = True
        save_state(state_path, state)
    print(f"等待解析：{source.name}（batch_id={state['batch_id']}）")
    deadline = time.monotonic() + options.wait_timeout
    previous = None
    while time.monotonic() < deadline:
        data = api("GET", f"/extract-results/batch/{state['batch_id']}", token)
        results = data.get("extract_result", [])
        item = next((r for r in results if r.get("data_id") == identity), None)
        if item is None:
            item = next((r for r in results if r.get("file_name") == source.name), {})
        status = item.get("state", "pending")
        if status != previous:
            print(f"  {status}")
            previous = status
        if status == "failed":
            raise RuntimeError(f"解析失败：{item.get('err_msg', '未知原因')}；"
                               "若为 Word 转换失败，请用 Word 导出 PDF 后重试。"
                               "重新提交原文件可使用新的 --output 目录。")
        if status == "done":
            state["markdown"] = download(item["full_zip_url"], destination)
            save_state(state_path, state)
            for relative in state["markdown"]:
                print(f"已保存：{destination / 'content' / relative}")
            return
        time.sleep(min(options.poll_interval, max(0, deadline - time.monotonic())))
    raise RuntimeError("等待解析超时；重新运行相同命令将继续查询已上传任务。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", default=[str(ROOT)], help="文件或目录；默认递归扫描项目")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "mineru", help="结果目录")
    parser.add_argument("--model", choices=["vlm", "pipeline"], default="vlm")
    parser.add_argument("--language", default="ch")
    parser.add_argument("--ocr", action="store_true", help="显式启动 OCR；用于扫描件或错误文本层")
    parser.add_argument("--poll-interval", type=float, default=5, help="轮询间隔秒数")
    parser.add_argument("--wait-timeout", type=float, default=1800, help="每个文件等待解析的秒数")
    parser.add_argument("--dry-run", action="store_true", help="仅列出待上传文件，无需 Token")
    options = parser.parse_args()
    if not (0 < options.poll_interval < float('inf') and 0 < options.wait_timeout < float('inf')):
        parser.error("轮询间隔和等待时间必须是有限正数。")
    options.output = options.output.resolve()
    files = discover(options.inputs, options.output)
    if not files:
        print("未找到 PDF、DOC 或 DOCX 文件。")
        return 0
    print(f"找到 {len(files)} 个文档；模型={options.model}，公式和表格识别已开启。")
    if options.dry_run:
        for source in files:
            print(source)
        return 0
    token = os.environ.get("MINERU_API_TOKEN", "").strip()
    if not token:
        raise ValueError("请设置环境变量 MINERU_API_TOKEN（只填 Token，不含 Bearer 前缀）。")
    failures = 0
    for source in files:
        try:
            parse_file(source, options, token)
        except (RuntimeError, ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
            failures += 1
            print(f"失败：{source.name}：{error}", file=sys.stderr)
    print(f"完成：{len(files) - failures}；失败：{failures}。")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已中断；重新运行可继续查询已上传任务。", file=sys.stderr)
        sys.exit(130)
