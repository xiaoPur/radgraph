# IU-Xray 医学知识抽取使用手册

本文档说明如何在云服务器上使用本仓库对 IU-Xray 报告文本进行知识抽取。云服务器上的仓库路径假设为：

```bash
/root/autodl-tmp/radgraph
```

## 1. 功能概览

新增的 IU-Xray 适配脚本会完成以下流程：

```text
IU-Xray CSV 读取
-> findings/impression 分节抽取
-> RadGraph 实体关系抽取
-> MeSH/Problems 解析
-> 合并成 report-level 医学知识图谱
-> 关联 frontal/lateral 图像文件名
```

输出文件为 JSONL，每一行对应一份报告，包含报告级标签、分节 RadGraph 结果、图片映射和知识图谱节点/边。

## 2. 环境准备

进入仓库并创建虚拟环境：

```bash
cd /root/autodl-tmp/radgraph
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

安装项目依赖：

```bash
pip install -e .
pip install huggingface_hub
```

如果服务器环境没有 PyTorch，请按你的 CUDA 版本安装。例如 CUDA 12.1 可尝试：

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

CPU 环境可用：

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

## 3. 数据位置

默认使用以下文件：

```bash
/root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_reports.csv
/root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_projections.csv
```

`indiana_reports.csv` 提供 `uid, MeSH, Problems, image, indication, comparison, findings, impression`。

`indiana_projections.csv` 提供 `uid, filename, projection`，用于关联 frontal/lateral 图像文件名。

## 4. 首次试跑

首次运行会从 Hugging Face 下载 RadGraph 权重，建议先跑 10 条确认环境正常：

```bash
cd /root/autodl-tmp/radgraph
source .venv/bin/activate

mkdir -p outputs cache/radgraph cache/huggingface
export HF_HOME=/root/autodl-tmp/radgraph/cache/huggingface

python -m radgraph.iuxray \
  --reports-csv /root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_reports.csv \
  --projections-csv /root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_projections.csv \
  --output-jsonl /root/autodl-tmp/radgraph/outputs/iuxray_knowledge_sample.jsonl \
  --model-type modern-radgraph-xl \
  --cuda 0 \
  --model-cache-dir /root/autodl-tmp/radgraph/cache/radgraph \
  --limit 10
```

如果没有 GPU，把 `--cuda 0` 改成：

```bash
--cuda -1
```

## 5. 全量抽取

确认试跑成功后，执行全量抽取：

```bash
cd /root/autodl-tmp/radgraph
source .venv/bin/activate

mkdir -p outputs cache/radgraph cache/huggingface
export HF_HOME=/root/autodl-tmp/radgraph/cache/huggingface

nohup python -m radgraph.iuxray \
  --reports-csv /root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_reports.csv \
  --projections-csv /root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_projections.csv \
  --output-jsonl /root/autodl-tmp/radgraph/outputs/iuxray_knowledge.jsonl \
  --model-type modern-radgraph-xl \
  --cuda 0 \
  --model-cache-dir /root/autodl-tmp/radgraph/cache/radgraph \
  --resume \
  > /root/autodl-tmp/radgraph/outputs/iuxray_extract.log 2>&1 &
```

查看日志：

```bash
tail -f /root/autodl-tmp/radgraph/outputs/iuxray_extract.log
```

查看输出行数：

```bash
wc -l /root/autodl-tmp/radgraph/outputs/iuxray_knowledge.jsonl
```

`--resume` 会跳过输出文件里已经存在的 `uid`，适合断点续跑。

## 6. 输出结构

每行 JSON 大致结构如下：

```json
{
  "uid": "4",
  "image": "PA and lateral views of the chest",
  "indication": "patient with ...",
  "comparison": "None available",
  "problems": ["Pulmonary Fibrosis", "Opacity"],
  "mesh": [
    {
      "raw": "Opacity/lung/apex/left/irregular",
      "finding": "Opacity",
      "attributes": ["lung", "apex", "left", "irregular"],
      "anatomy": ["lung", "apex"],
      "laterality": ["left"],
      "severity": [],
      "modifiers": ["irregular"]
    }
  ],
  "images": {
    "all": [{"filename": "4_IM-2050-1001.dcm.png", "projection": "Frontal"}],
    "frontal": ["4_IM-2050-1001.dcm.png"],
    "lateral": ["4_IM-2050-2001.dcm.png"]
  },
  "sections": [
    {
      "name": "findings",
      "text": "...",
      "radgraph_annotations": {},
      "processed_annotations": []
    }
  ],
  "knowledge_graph": {
    "nodes": [],
    "edges": []
  }
}
```

其中 `knowledge_graph.edges` 常见关系包括：

```text
report -> has_problem -> problem
report -> has_mesh -> mesh
report -> linked_image -> image
report -> has_section -> section
section -> has_observation -> observation
observation -> located_at -> anatomy
observation -> suggestive_of -> suggestion
```

## 7. 快速检查输出

查看第一条结果的核心字段：

```bash
python - <<'PY'
import json
path = "/root/autodl-tmp/radgraph/outputs/iuxray_knowledge_sample.jsonl"
with open(path, "r", encoding="utf-8") as f:
    item = json.loads(next(f))
print("uid:", item["uid"])
print("problems:", item["problems"])
print("mesh first:", item["mesh"][:1])
print("sections:", [s["name"] for s in item["sections"]])
print("nodes:", len(item["knowledge_graph"]["nodes"]))
print("edges:", len(item["knowledge_graph"]["edges"]))
PY
```

## 8. 质量建议

- 推荐使用 `modern-radgraph-xl`，它的标签更清晰，例如 `Observation::definitely present`、`Observation::definitely absent`、`Observation::uncertain`。
- 脚本会分开处理 `findings` 和 `impression`，避免把结论和正文直接拼接后造成重复实体。
- `MeSH` 和 `Problems` 是报告级弱监督标签，适合用于知识融合、检索、多标签监督。
- RadGraph 输出更适合做细粒度实体关系，例如发现、部位、否定、不确定性和提示关系。
- `XXXX` 脱敏占位符已做轻量清洗，例如 `No XXXX of` 会变成 `No evidence of`，`x-XXXX` 会变成 `x-ray`。

## 9. 常见问题

如果 Hugging Face 下载失败，检查网络或提前下载 `StanfordAIMI/RRG_scorers` 中的 `modern-radgraph-xl.tar.gz`。脚本默认会把模型缓存到 `--model-cache-dir` 指定目录。

如果显存不足，使用 CPU：

```bash
--cuda -1
```

如果中途停止，重新运行同一条命令并保留：

```bash
--resume
```

如果只想调试少量样本，使用：

```bash
--limit 20
```
