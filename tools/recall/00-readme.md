# Life 本地语义检索

在这台 Mac 上给日记和 AI 对话记录建向量索引，按意思而不是关键词找过去的事。模型是 `microsoft/harrier-oss-v1-0.6b`，全程本地运行；第一次使用时会从 Hugging Face 下载模型（约 1.1GB）。

## 怎么用

- 搜索：`python3 tools/recall/recall.py search "在图书馆复习到很晚的那天" "stayed late studying in the library"`
- 每次搜索前会自动把新增或改过的文件补进索引，平时几秒钟；没有后台定时任务。
- 分析某一天时只看那天及以前的内容，避免用后来的内容解释当时：加 `--before YYYY-MM-DD`。
- 只看手写原文：加 `--kinds handwritten`。
- 手动全量重建：`python3 tools/recall/recall.py index --full`；看索引状态：`python3 tools/recall/recall.py status`。

## 怎么搜更准

- 用当时发生的具体细节去搜（在哪、和谁、做了什么），不要只用现在给这件事起的名字。
- 中文、英文各搜一次，日记两种语言都有。一次调用可以传多个查询。
- 结果只是候选。命中「转写」「分析」「对话记录」时，按它的日期回到当天的原始日记，引用原文。

## 索引了什么

- `journal/YYYY/MM/` 下的日记，和 `journal/ai-conversations/` 下的对话记录；不含记忆文件、resources、archives。
- 每一块标了来源：手写、转写（带「对话转写」标注的段落）、分析（Copilot 写的段落）、对话记录。
- `data/` 里是切块原文和向量，属于私密内容，已写进 `.gitignore`；工具代码和这篇说明会进 git。
