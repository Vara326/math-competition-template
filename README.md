# math-competition-template

数学竞赛项目模板。Fork（或 "Use this template"）本仓库即可快速开启新的竞赛项目。

## 使用方法

1. Fork 本仓库，重命名为新项目（或使用 GitHub 的 "Use this template" 一键复制）
2. Clone 到本地，在 Positron / VS Code 中打开
3. 修改 `AGENTS.md`，填入本次竞赛的背景、数据与约定
4. 按需增删 `skills/` 中的 skill

## 目录结构

| 路径 | 说明 |
|------|------|
| `AGENTS.md` | 项目级 AI 助手记忆文件（Positron Assistant 会自动读取，用于跨会话保持上下文） |
| `skills/` | 自定义 AI 助手 skill，每个 skill 一个子目录，入口为 `SKILL.md` |
| `.gitignore` | 数据分析项目常用忽略规则（Python / R / 数据文件 / 密钥） |

## 约定

- 原始数据放在 `data/`（默认不入库；小规模参考数据可 `git add -f`）
- 代码、 notebook、报告入库存放，保持可复现
- 涉及模型或推断时，记录关键假设与结论，写入 `AGENTS.md` 的"项目进展"一节
