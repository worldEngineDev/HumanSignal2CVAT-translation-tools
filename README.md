# CVAT HumanSignal 自动化导入工具

自动化将HumanSignal导出的COCO格式数据导入到CVAT，并按session自动分组为jobs。

## 功能特点

- ✅ 自动创建CVAT任务
- ✅ 按session自动分组创建jobs（232个session → 232个jobs）
- ✅ 从AWS S3云存储自动加载图片
- ✅ 自动上传标注数据
- ✅ 生成job-session映射文件
- ✅ 完整的错误检查和日志记录

## 快速开始

### 方法1：一键运行（推荐，自动配置虚拟环境）✨

```bash
./run_simple.sh
```

脚本会自动：
- ✅ 创建虚拟环境（.venv）
- ✅ 安装依赖（requests）
- ✅ 运行配置向导
- ✅ 测试连接
- ✅ 执行导入

### 方法2：手动配置虚拟环境

```bash
# 1. 创建虚拟环境
python3 -m venv .venv

# 2. 激活虚拟环境
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 准备数据
mkdir -p data
cp /path/to/result.json data/

# 5. 配置
python3 setup.py

# 6. 测试连接
python3 test_connection.py

# 7. 运行导入
python3 cvat_auto_import.py

# 8. 退出虚拟环境
deactivate
```

### 方法3：使用 uv（如果已安装）

```bash
# 直接运行，无需配置虚拟环境
uv run --no-project python3 setup.py
uv run --no-project python3 test_connection.py
uv run --no-project python3 cvat_auto_import.py
```

> 💡 详细安装说明请查看 [INSTALL.md](INSTALL.md)

## 输出文件
# 4. 测试连接
python3 test_connection.py

# 5. 运行导入
python3 cvat_auto_import.py
```

### 方法3：一键运行

```bash
./run.sh
```

脚本会自动检测 uv 并使用最佳方式运行。

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

# 上传标注到现有任务
uv run python upload_annotations_only.py <task_id> <annotation_file>
```

详细说明请查看 `UV使用说明.md`

## 输出文件

导入完成后会生成：

- `logs/cvat_import_YYYYMMDD_HHMMSS.log` - 详细的导入日志
- `logs/job_session_mapping_<task_id>.json` - job和session的映射（JSON格式）
- `logs/job_session_mapping_<task_id>.csv` - job和session的映射（CSV格式，方便查看）

## 映射文件说明

由于CVAT界面不显示session名称，我们生成映射文件来记录对应关系：

**CSV格式示例：**
```csv
job_id,session_id,job_url,start_frame,stop_frame,frame_count,image_count
3523456,13fa_session_20251203_090058,https://app.cvat.ai/tasks/1964457/jobs/3523456,0,129,130,130
3523457,13fa_session_20251209_122213,https://app.cvat.ai/tasks/1964457/jobs/3523457,130,159,30,30
```

**使用方法：**
1. 打开CSV文件
2. 搜索session ID
3. 点击 `job_url` 直接打开对应的标注页面

## 工具脚本

### 检查任务状态

```bash
uv run cvat-check-status <task_id>
# 或
python3 check_task_status.py <task_id>
```

### 生成映射文件

如果需要为现有任务重新生成映射：

```bash
uv run cvat-generate-mapping <task_id>
# 或
python3 generate_job_mapping.py <task_id>
```

### 检查导入错误

```bash
uv run cvat-check-errors <task_id>
# 或
python3 check_import_errors.py <task_id>
```

### 上传标注到现有任务

```bash
python3 upload_annotations_only.py <task_id> <annotation_file>
```

## 项目结构

```
cvat-humansignal-import/
├── README.md                    # 本文件
├── QUICKSTART.md                # 快速开始指南
├── UV使用说明.md                # uv详细使用说明
├── 使用说明.md                  # 中文使用说明
├── pyproject.toml               # uv项目配置
├── requirements.txt             # Python依赖
├── .gitignore                   # Git忽略文件
├── config.example.json          # 配置文件模板
├── run.sh                       # 一键运行脚本
├── setup.py                     # 配置向导
├── cvat_auto_import.py          # 主程序
├── test_connection.py           # 连接测试
├── check_task_status.py         # 任务状态检查
├── generate_job_mapping.py      # 生成映射文件
├── check_import_errors.py       # 错误检查
├── upload_annotations_only.py   # 仅上传标注
├── data/                        # 数据目录（需自行创建）
│   └── result.json             # HumanSignal导出数据
└── logs/                        # 日志目录（自动创建）
    ├── cvat_import_*.log       # 导入日志
    └── job_session_mapping_*.csv  # 映射文件
```

## 注意事项

### 1. CVAT账号限制

- 免费账号最多5个任务
- 需要在组织中有相应权限
- 云存储需要提前配置好

### 2. 数据要求

- HumanSignal导出的COCO格式JSON
- 图片已上传到AWS S3（路径：`s3://fpv/test_1000/images/`）
- 标签名称：Left hand, Partial left hand, Partial right hand, Right hand

### 3. Session分组规则

Session ID从文件名提取，格式：`{id}_session_{date}_{time}`

例如：`7393_session_20251209_060300_671305_0000_000000.jpg`
→ Session ID: `7393_session_20251209_060300`

### 4. 执行时间

- 任务创建：几秒
- 图片加载：1-2分钟
- 标注上传：1-2分钟
- **总计：约5分钟**

## 常见问题

### Q: API Key在哪里获取？

A: 
1. 登录 https://app.cvat.ai/
2. 点击右上角头像 → Account
3. 找到 API Key 部分
4. 复制或生成新的key

### Q: 如何切换到组织工作区？

A: 在CVAT界面，点击左上角的组织名称（如"wp"），确保不是"Personal workspace"。

### Q: 标注导入失败怎么办？

A: 
1. 检查日志文件中的错误信息
2. 运行 `uv run cvat-check-errors <task_id>` 查看详细错误
3. 常见原因：图片路径不匹配、标签名称不一致

### Q: 如何找到某个session对应的job？

A: 打开 `logs/job_session_mapping_<task_id>.csv`，搜索session ID，点击对应的job_url。

## 技术细节

### 关键API调用

1. **创建任务**：`POST /api/tasks?org=wp`
2. **加载图片**：`POST /api/tasks/{id}/data` with `job_file_mapping`
3. **上传标注**：`POST /api/tasks/{id}/annotations`

### job_file_mapping参数

这是实现按session分组的关键参数：

```python
job_file_mapping = [
    ["path/to/session1/img1.jpg", "path/to/session1/img2.jpg"],  # Job 1
    ["path/to/session2/img1.jpg", "path/to/session2/img2.jpg"],  # Job 2
    ...
]
```

CVAT会根据这个映射创建对应数量的jobs。

## 更新日志

### v1.0 (2026-01-26)
- ✅ 初始版本
- ✅ 支持按session自动分组
- ✅ 自动错误检查
- ✅ 生成job-session映射文件
- ✅ 支持uv包管理器

## 许可证

内部使用

## 联系方式

如有问题请联系团队。
