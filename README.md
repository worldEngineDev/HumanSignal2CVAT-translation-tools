# CVAT 数据管理工具

CVAT 标注任务管理和进度跟踪工具集。

## 快速开始

### 1. 安装依赖
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. 配置
```bash
cp config.example.json config.json
# 编辑 config.json 填入你的 CVAT API Key 和云存储配置
```

### 3. 运行工作流
```bash
bash run_workflow.sh
```

## 工作流程

### 选项 1：从旧平台迁移（HumanSignal → CVAT）
- 一键导入旧平台的标注数据
- 自动创建任务、按 session 分组 jobs
- 上传已有标注

### 选项 2：核对云存储和标注状态
- 对比云存储（R2）和 CVAT 中的数据
- 找出已标注、未标注、未导入的数据
- 生成新数据列表供导入使用

### 选项 3：检查标注人员完成情况
- 查看每个标注人员的 jobs 完成情况
- 基于实际标注数据判断完成状态（不依赖 state 字段）
- 生成每日进度报告

### 选项 4：从云存储导入新数据
- 读取选项 2 生成的新数据列表
- 按 session 分组创建 jobs
- 自动轮询分配给标注人员

### 选项 5：列出标注人员
- 获取组织成员列表
- 自动更新 config.json 中的 assignees 配置

### 选项 6：查看报告
- 查看标注状态报告
- 查看人员进度报告
- 查看日志文件

## 核心脚本

| 脚本 | 功能 | 用法 |
|------|------|------|
| `cvat_auto_import.py` | 从旧平台迁移数据 | `python cvat_auto_import.py` |
| `check_annotation_status.py` | 核对标注状态 | `python check_annotation_status.py [task_id...]` |
| `check_progress.py` | 检查人员进度 | `python check_progress.py [task_id...]` |
| `import_new_data.py` | 导入新数据 | `python import_new_data.py [new_images_file]` |
| `list_annotators.py` | 管理标注人员 | `python list_annotators.py` |

## 配置说明

`config.json` 主要配置项：

```json
{
  "cvat": {
    "url": "https://app.cvat.ai",
    "api_key": "你的API密钥"
  },
  "s3": {
    "bucket_name": "fpv-anno",
    "account_id": "Cloudflare R2 Account ID",
    "aws_access_key_id": "R2 Access Key",
    "aws_secret_access_key": "R2 Secret Key"
  },
  "assignees": [
    {"id": 用户ID, "name": "用户名"}
  ]
}
```

## 注意事项

1. **使用虚拟环境**：脚本会自动使用 `.venv/bin/python`
2. **任务 ID 参数**：检查脚本支持指定任务 ID，不指定则检查所有任务
3. **标注判断逻辑**：基于实际标注数据（`/api/jobs/{id}/annotations`），不依赖 `state` 字段
4. **云存储**：使用 Cloudflare R2，bucket 为 `fpv-anno`

详细历史记录见 `SUMMARY.md`
