# 快速开始指南

## 使用 uv（推荐）

### 1. 安装 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 进入项目目录

```bash
cd cvat-humansignal-import
```

### 3. 配置

```bash
uv run cvat-setup
```

按提示输入：
- CVAT服务器地址：`https://app.cvat.ai`
- API Key：从CVAT账号设置中获取
- 云存储ID：`4837`（默认）
- 数据文件路径：`data/result.json`
- 任务名称：自定义或使用默认

### 4. 准备数据

```bash
mkdir -p data
cp /path/to/result.json data/
```

将HumanSignal导出的 `result.json` 放入 `data/` 目录。

### 5. 测试连接

```bash
uv run cvat-test
```

看到 "✅ 所有测试通过！" 即可继续。

### 6. 运行导入

```bash
uv run cvat-import
```

或使用一键脚本：

```bash
./run.sh
```

等待5-10分钟完成。

### 7. 查看结果

- 打开CVAT任务链接（日志中会显示）
- 查看 `logs/job_session_mapping_<task_id>.csv` 了解job和session的对应关系

---

## 使用 pip（传统方式）

### 1. 进入项目目录

```bash
cd cvat-humansignal-import
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

```bash
python3 setup.py
```

按提示输入配置信息。

### 4. 准备数据

```bash
mkdir -p data
cp /path/to/result.json data/
```

### 5. 测试连接

```bash
python3 test_connection.py
```

看到 "✅ 所有测试通过！" 即可继续。

### 6. 运行导入

```bash
python3 cvat_auto_import.py
```

等待5-10分钟完成。

### 7. 查看结果

- 打开CVAT任务链接（日志中会显示）
- 查看 `logs/job_session_mapping_<task_id>.csv` 了解job和session的对应关系

---

## uv 命令速查

```bash
# 配置
uv run cvat-setup

# 测试连接
uv run cvat-test

# 运行导入
uv run cvat-import

# 检查任务状态
uv run cvat-check-status <task_id>

# 检查导入错误
uv run cvat-check-errors <task_id>

# 生成映射文件
uv run cvat-generate-mapping <task_id>
```

详细说明请查看 `UV使用说明.md`

---

## 日常使用

### 导入新数据

1. 更新 `data/result.json`
2. 运行 `uv run cvat-import`

### 查看任务状态

```bash
uv run cvat-check-status <task_id>
```

### 检查错误

```bash
uv run cvat-check-errors <task_id>
```

### 生成映射文件

```bash
uv run cvat-generate-mapping <task_id>
```

---

## 常见问题

### API Key过期

重新运行 `uv run cvat-setup` 更新配置。

### 任务数量达到上限

删除旧任务或升级CVAT账号。

### 标注导入失败

1. 检查日志文件
2. 运行 `uv run cvat-check-errors <task_id>`
3. 确认图片路径和标签名称正确

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `cvat_auto_import.py` | 主程序 |
| `setup.py` | 配置向导 |
| `test_connection.py` | 连接测试 |
| `check_task_status.py` | 任务状态检查 |
| `generate_job_mapping.py` | 生成映射文件 |
| `check_import_errors.py` | 错误检查 |
| `upload_annotations_only.py` | 仅上传标注 |
| `config.json` | 配置文件（不提交到git） |
| `data/result.json` | HumanSignal导出数据 |
| `logs/` | 日志和映射文件 |

---

## 获取帮助

遇到问题请：
1. 查看日志文件
2. 运行错误检查脚本
3. 联系团队
