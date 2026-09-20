# Life 本地语义检索

在这台 Mac 上给日记和 AI 对话记录建向量索引，按意思而不是关键词找过去的事。模型是 `microsoft/harrier-oss-v1-0.6b`，检索和索引计算全程本地运行，也不会联网检查模型更新。

## 怎么用

- 首次使用或缓存缺文件时，在可联网的环境运行 `python3 tools/recall/recall.py download-model`，从 Hugging Face 下载模型（约 1.1GB）；已有完整缓存则不需要。
- 搜索：`python3 tools/recall/recall.py search "在图书馆复习到很晚的那天" "stayed late studying in the library"`
- 每次搜索前会自动把新增或改过的文件补进索引，平时几秒钟；没有后台定时任务。
- 分析某一天时只看那天及以前的内容，避免用后来的内容解释当时：加 `--before YYYY-MM-DD`。
- 只看手写原文：加 `--kinds handwritten`。
- 手动全量重建：`python3 tools/recall/recall.py index --full`；看索引状态：`python3 tools/recall/recall.py status`。

## 加载与等待

- 普通搜索只加载本机缓存；缓存缺失会直接提示下载命令，不会在后台反复尝试联网。
- 加载时会显示使用 CPU 还是 MPS，以及模型就绪所用时间；受限运行环境可能只能使用 CPU。
- 另一个检索正在更新索引时，会显示等待提示，最多等 30 秒后退出；稍后重试即可。若明确接受尚未更新的内容，可以用 `search --no-update` 搜索已经保存的索引。

## 怎么搜更准

- 用当时发生的具体细节去搜（在哪、和谁、做了什么），不要只用现在给这件事起的名字。
- 中文、英文各搜一次，日记两种语言都有。一次调用可以传多个查询。
- 结果只是候选。命中「转写」「分析」「对话记录」时，按它的日期回到当天的原始日记，引用原文。

## 索引了什么

- `journal/YYYY/MM/` 下的日记，和 `journal/ai-conversations/` 下的对话记录；不含记忆文件、resources、archives。
- 每一块标了来源：手写、转写（带「对话转写」标注的段落）、分析（Copilot 写的段落）、对话记录。
- `data/` 里是切块原文和向量，属于私密内容，已写进 `.gitignore`；工具代码和这篇说明会进 git。
