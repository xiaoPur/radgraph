# AutoDL 上运行 IU-Xray 医学知识抽取手册

本文档针对你的 AutoDL 实例编写：

```text
镜像：PyTorch 2.8.0
Python：3.12, Ubuntu 22.04
CUDA：12.8
GPU：vGPU 48GB * 1
CPU：25 vCPU
内存：92GB
硬盘：系统盘 30GB，数据盘 /root/autodl-tmp 50GB
仓库位置：/root/autodl-tmp/radgraph
```

这个实例配置很充足，可以直接跑 IU-Xray 全量文本知识抽取。因为实例即用即删，下面不创建虚拟环境，直接使用镜像自带的 Python 和 PyTorch。

## 1. 先进入仓库

```bash
cd /root/autodl-tmp/radgraph
```

确认当前 Python 和 PyTorch：

```bash
python - <<'PY'
import torch
print("torch:", torch.__version__)
print("cuda available:", torch.cuda.is_available())
print("cuda version:", torch.version.cuda)
print("gpu:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU")
PY
```

正常情况下应看到 `cuda available: True`。

## 2. 安装缺失依赖

不要重装 PyTorch。你的镜像已经有 PyTorch 2.8.0 + CUDA 12.8，只需要补本项目依赖。

```bash
cd /root/autodl-tmp/radgraph

python -m pip install -U pip
python -m pip install -e .
python -m pip install "transformers>=4.39.0,<5.0.0" huggingface_hub numpy
```

如果网络慢，可以加清华源：

```bash
python -m pip install -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m pip install "transformers>=4.39.0,<5.0.0" huggingface_hub numpy -i https://pypi.tuna.tsinghua.edu.cn/simple
```

检查依赖是否齐全：

```bash
python - <<'PY'
mods = [
    "torch",
    "transformers",
    "appdirs",
    "jsonpickle",
    "filelock",
    "h5py",
    "nltk",
    "dotmap",
    "huggingface_hub",
    "numpy",
]
for m in mods:
    try:
        mod = __import__(m)
        print(m, "OK", getattr(mod, "__version__", ""))
    except Exception as e:
        print(m, "MISSING", e)
PY
```

如果某个包显示 `MISSING`，单独安装即可，例如：

```bash
python -m pip install dotmap
```

## 3. 把缓存放到数据盘

AutoDL 系统盘只有 30GB，不建议把模型缓存放到 `/root/.cache`。建议全部放到 `/root/autodl-tmp/radgraph/cache`。

```bash
cd /root/autodl-tmp/radgraph

mkdir -p outputs
mkdir -p cache/radgraph
mkdir -p cache/huggingface

export HF_HOME=/root/autodl-tmp/radgraph/cache/huggingface
export TRANSFORMERS_CACHE=/root/autodl-tmp/radgraph/cache/huggingface
```

这两个 `export` 只对当前终端有效。如果你重新打开终端，需要重新执行。

## 4. 确认数据文件存在

```bash
ls -lh /root/autodl-tmp/radgraph/IU-Xray_only_text/
```

应能看到：

```text
indiana_reports.csv
indiana_projections.csv
images_normalized/
```

其中：

- `indiana_reports.csv`：报告文本、MeSH、Problems
- `indiana_projections.csv`：uid 和 frontal/lateral 图像文件名映射
- `images_normalized/`：你当前只放了少量图片样例，不影响文本知识抽取

## 5. 先试跑 10 条

第一次运行会自动下载 RadGraph 权重 `modern-radgraph-xl.tar.gz`，需要等一会儿。

```bash
cd /root/autodl-tmp/radgraph

export HF_HOME=/root/autodl-tmp/radgraph/cache/huggingface
export TRANSFORMERS_CACHE=/root/autodl-tmp/radgraph/cache/huggingface

python -m radgraph.iuxray \
  --reports-csv /root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_reports.csv \
  --projections-csv /root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_projections.csv \
  --output-jsonl /root/autodl-tmp/radgraph/outputs/iuxray_knowledge_sample.jsonl \
  --radgraph-only-jsonl /root/autodl-tmp/radgraph/outputs/iuxray_radgraph_only_sample.jsonl \
  --model-type modern-radgraph-xl \
  --cuda 0 \
  --model-cache-dir /root/autodl-tmp/radgraph/cache/radgraph \
  --limit 10
```

你的 GPU 有 48GB 显存，`--cuda 0` 可以直接使用。

如果命令最后输出类似下面内容，说明试跑完成：

```json
{
  "total_reports": 10,
  "processed_reports": 10,
  "skipped_reports": 0
}
```

检查输出：

```bash
wc -l /root/autodl-tmp/radgraph/outputs/iuxray_knowledge_sample.jsonl
wc -l /root/autodl-tmp/radgraph/outputs/iuxray_radgraph_only_sample.jsonl
head -n 1 /root/autodl-tmp/radgraph/outputs/iuxray_knowledge_sample.jsonl
```

## 6. 查看一条抽取结果

```bash
python - <<'PY'
import json

path = "/root/autodl-tmp/radgraph/outputs/iuxray_knowledge_sample.jsonl"
with open(path, "r", encoding="utf-8") as f:
    item = json.loads(next(f))

print("uid:", item["uid"])
print("problems:", item["problems"])
print("mesh 前 3 个:", item["mesh"][:3])
print("sections:", [s["name"] for s in item["sections"]])
print("nodes:", len(item["knowledge_graph"]["nodes"]))
print("edges:", len(item["knowledge_graph"]["edges"]))

for sec in item["sections"]:
    print("\nSECTION:", sec["name"])
    for obs in sec["processed_annotations"][:5]:
        print(obs)
PY
```

重点看：

- `problems`：报告级疾病标签
- `mesh`：拆解后的 IU-Xray MeSH 知识
- `sections`：分开的 `findings` / `impression`
- `processed_annotations`：RadGraph 抽出的 observation、location、tag
- `knowledge_graph`：融合后的节点和边

## 7. 全量抽取

试跑正常后，执行全量抽取：

```bash
cd /root/autodl-tmp/radgraph

export HF_HOME=/root/autodl-tmp/radgraph/cache/huggingface
export TRANSFORMERS_CACHE=/root/autodl-tmp/radgraph/cache/huggingface

nohup python -m radgraph.iuxray \
  --reports-csv /root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_reports.csv \
  --projections-csv /root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_projections.csv \
  --output-jsonl /root/autodl-tmp/radgraph/outputs/iuxray_knowledge.jsonl \
  --radgraph-only-jsonl /root/autodl-tmp/radgraph/outputs/iuxray_radgraph_only.jsonl \
  --model-type modern-radgraph-xl \
  --cuda 0 \
  --model-cache-dir /root/autodl-tmp/radgraph/cache/radgraph \
  --resume \
  > /root/autodl-tmp/radgraph/outputs/iuxray_extract.log 2>&1 &
```

查看运行日志：

```bash
tail -f /root/autodl-tmp/radgraph/outputs/iuxray_extract.log
```

查看已输出多少条：

```bash
wc -l /root/autodl-tmp/radgraph/outputs/iuxray_knowledge.jsonl
wc -l /root/autodl-tmp/radgraph/outputs/iuxray_radgraph_only.jsonl
```

IU-Xray 当前有 3851 条报告，其中有些报告没有 `findings` 和 `impression`，脚本会跳过空文本报告。

## 8. 断点续跑

如果 AutoDL 实例中断或你手动停止，保留输出文件后重新运行同一条全量命令即可。因为命令里带了：

```bash
--resume
```

脚本会读取已有 JSONL 中的 `uid`，跳过已经完成的报告。

## 9. 输出文件说明

输出路径：

```bash
/root/autodl-tmp/radgraph/outputs/iuxray_knowledge.jsonl
/root/autodl-tmp/radgraph/outputs/iuxray_radgraph_only.jsonl
```

`iuxray_knowledge.jsonl` 是最终融合结果，包含 IU-Xray 的 `MeSH`、`Problems`、正常标签、图片映射、RadGraph 分节结果和 report-level 知识图谱。每一行是一份报告，结构大致如下：

```json
{
  "uid": "4",
  "image": "PA and lateral views of the chest",
  "indication": "patient with ...",
  "comparison": "None available",
  "normal_labels": {
    "mesh": false,
    "problems": false,
    "is_normal": false
  },
  "problems": ["Pulmonary Disease, Chronic Obstructive", "Opacity"],
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
    "all": [
      {"filename": "4_IM-2050-1001.dcm.png", "projection": "Frontal"}
    ],
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

常见图谱关系：

```text
report -> has_problem -> problem
report -> has_mesh -> mesh
report -> linked_image -> image
report -> has_section -> section
section -> has_observation -> observation
report -> has_observation -> observation
observation -> located_at -> anatomy
observation -> suggestive_of -> suggestion
```

`iuxray_radgraph_only.jsonl` 是中间结果，只保留 RadGraph 对 `findings` / `impression` 的分节抽取结果，不包含 `MeSH`、`Problems` 和融合知识图谱。它适合以后迁移到私有报告数据集时复用。结构大致如下：

```json
{
  "uid": "4",
  "image": "PA and lateral views of the chest",
  "indication": "patient with ...",
  "comparison": "None available",
  "images": {
    "all": [
      {"filename": "4_IM-2050-1001.dcm.png", "projection": "Frontal"}
    ],
    "frontal": ["4_IM-2050-1001.dcm.png"],
    "lateral": ["4_IM-2050-2001.dcm.png"]
  },
  "sections": [
    {
      "name": "findings",
      "text": "...",
      "radgraph_annotations": {},
      "processed_annotations": [
        {
          "observation": "pneumothorax",
          "located_at": [],
          "tags": ["definitely absent"],
          "suggestive_of": null
        }
      ]
    }
  ]
}
```

对于私有报告，如果没有 IU-Xray 的 `MeSH` 和 `Problems`，优先参考这个中间结果文件格式。

## 10. 常见问题

### 10.1 ModuleNotFoundError: dotmap / appdirs / transformers

说明依赖没装完整，执行：

```bash
cd /root/autodl-tmp/radgraph
python -m pip install -e .
python -m pip install "transformers>=4.39.0,<5.0.0" huggingface_hub numpy
```

如果你已经装过一次依赖，并遇到 `TokenizersBackend has no attribute encode_plus`，说明当前环境安装了 Transformers v5 或 v5 预览版。直接执行：

```bash
python -m pip install "transformers>=4.39.0,<5.0.0"
python - <<'PY'
import transformers
print(transformers.__version__)
assert transformers.__version__.split(".")[0] == "4"
PY
```

### 10.2 Hugging Face 下载失败

先确认网络能访问 Hugging Face。也可以重新运行，`hf_hub_download` 会复用已下载部分。

缓存目录建议一直使用：

```bash
--model-cache-dir /root/autodl-tmp/radgraph/cache/radgraph
```

并设置：

```bash
export HF_HOME=/root/autodl-tmp/radgraph/cache/huggingface
```

### 10.3 系统盘快满了

检查：

```bash
df -h
du -sh /root/.cache || true
du -sh /root/autodl-tmp/radgraph/cache || true
```

如果 `/root/.cache` 很大，可以删掉后重新用数据盘缓存：

```bash
rm -rf /root/.cache/huggingface
```

然后重新设置：

```bash
export HF_HOME=/root/autodl-tmp/radgraph/cache/huggingface
export TRANSFORMERS_CACHE=/root/autodl-tmp/radgraph/cache/huggingface
```

### 10.4 想先少量调试

使用：

```bash
--limit 20
```

### 10.5 想用 CPU

你的 GPU 足够，不建议用 CPU。除非 GPU 不可用，才把：

```bash
--cuda 0
```

改成：

```bash
--cuda -1
```

## 11. 最推荐执行顺序

```bash
cd /root/autodl-tmp/radgraph

python -m pip install -U pip
python -m pip install -e .
python -m pip install "transformers>=4.39.0,<5.0.0" huggingface_hub numpy

mkdir -p outputs cache/radgraph cache/huggingface
export HF_HOME=/root/autodl-tmp/radgraph/cache/huggingface
export TRANSFORMERS_CACHE=/root/autodl-tmp/radgraph/cache/huggingface

python -m radgraph.iuxray \
  --reports-csv /root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_reports.csv \
  --projections-csv /root/autodl-tmp/radgraph/IU-Xray_only_text/indiana_projections.csv \
  --output-jsonl /root/autodl-tmp/radgraph/outputs/iuxray_knowledge_sample.jsonl \
  --radgraph-only-jsonl /root/autodl-tmp/radgraph/outputs/iuxray_radgraph_only_sample.jsonl \
  --model-type modern-radgraph-xl \
  --cuda 0 \
  --model-cache-dir /root/autodl-tmp/radgraph/cache/radgraph \
  --limit 10
```

试跑成功后，再运行全量抽取命令。
