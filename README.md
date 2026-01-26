# HumanSignal to CVAT 数据转换工具

自动化将 HumanSignal 导出的 COCO 格式数据导入到 CVAT，并按 session 自动分组为 jobs。

## ✨ 功能特点

- ✅ 自动创建 CVAT 任务
- ✅ 按 session 自动分组创建 jobs（272个 session → 272个 jobs）
- ✅ 从云存储自动加载图片
- ✅ 自动上传标注数据（支持 COCO 格式）
- ✅ 生成 job-session 映射文件
- ✅ 完整的错误检查和日志记录

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

复制配置模板并填写你的信息：

```bash
cp config.example.json config.json
```

编辑 `config.json`：

```json
{
  "cvat": {
    "url": "https://app.cvat.ai",
    "api_key": "YOUR_API_KEY_HERE"
  },
  "organization": {
    "id": 12345,
    "slug": "your-org",
    "name": "Your Organization"
  },
  "cloud_storage": {
    "id": 1234,
    "name": "Your Cloud Storage"
  },
  "files": {
    "humansignal_json": "data/result.json"
  },
  "task": {
    "name": "Hand Detection - HumanSignal Import"
  },
  "use_job_file_mapping": true
}
```

### 3. 准备数据

将 HumanSignal 导出的 COCO 格式 JSON 文件放到 `data/` 目录：

```bash
cp /path/to/your/result.json data/
```

### 4. 运行导入

```bash
python cvat_auto_import.py
```

## 📁 项目结构

```
HumanSignal2CVAT-translation/
├── README.md                      # 本文件
├── config.example.json            # 配置文件模板
├── config.json                    # 你的配置（不会提交到 git）
├── requirements.txt               # Python 依赖
├── .gitignore                     # Git 忽略文件
│
├── cvat_auto_import.py            # 主程序：完整导入流程
├── upload_annotations_only.py     # 单独上传标注到现有任务
├── generate_job_mapping.py        # 生成 job-session 映射文件
│
├── data/                          # 数据目录
│   ├── .gitkeep
│   └── result.json               # HumanSignal 导出数据（不会提交）
│
├── logs/                          # 日志目录（自动生成）
│   ├── .gitkeep
│   ├── cvat_import_*.log         # 导入日志
│   └── job_session_mapping_*.json # 映射文件
│
└── sample/                        # 示例数据
    └── result.json               # 示例 COCO 格式数据
```

## 🛠️ 工具脚本

### 主导入脚本

```bash
python cvat_auto_import.py
```

完整流程：
1. 创建 CVAT 任务
2. 按 session 分组图片
3. 加载图片到任务（21,000+ 张，约 3-5 分钟）
4. 上传标注数据（39,000+ 个标注）
5. 生成 job-session 映射文件

### 单独上传标注

如果任务已创建，只需要上传标注：

```bash
python upload_annotations_only.py
```

会提示输入任务 ID。

### 生成映射文件

为现有任务生成 job-session 映射：

```bash
python generate_job_mapping.py
```

会提示输入任务 ID。

## 📊 输出文件

导入完成后会生成：

- `logs/cvat_import_YYYYMMDD_HHMMSS.log` - 详细的导入日志
- `logs/job_session_mapping_<task_id>.json` - job 和 session 的映射关系

### 映射文件示例

```json
[
  {
    "job_id": 3526678,
    "session_id": "13fa_session_20251203_090058",
    "start_frame": 0,
    "stop_frame": 129,
    "frame_count": 130,
    "image_count": 130
  },
  {
    "job_id": 3526679,
    "session_id": "13fa_session_20251209_122213",
    "start_frame": 130,
    "stop_frame": 159,
    "frame_count": 30,
    "image_count": 30
  }
]
```

## ⚙️ 配置说明

### CVAT API Key

1. 登录 https://app.cvat.ai/
2. 点击右上角头像 → Account
3. 找到 API Key 部分
4. 复制或生成新的 key

### 组织信息

- `id`: 组织 ID（数字）
- `slug`: 组织短名称（URL 中使用）
- `name`: 组织全名

### 云存储

需要提前在 CVAT 中配置好云存储：
1. Settings → Cloud Storages
2. 添加你的 S3/Azure/GCS 存储
3. 记录存储 ID

### 数据文件

- `humansignal_json`: HumanSignal 导出的 COCO 格式 JSON 文件路径

### 任务配置

- `name`: CVAT 任务名称
- `use_job_file_mapping`: 是否按 session 分组（建议设为 `true`）

## 📝 数据格式要求

### HumanSignal COCO 格式

```json
{
  "images": [
    {
      "id": 0,
      "file_name": "images/hash__session_id_timestamp.jpg",
      "width": 1920,
      "height": 1080
    }
  ],
  "annotations": [
    {
      "id": 0,
      "image_id": 0,
      "category_id": 0,
      "bbox": [x, y, width, height],
      "area": 12345.67,
      "iscrowd": 0
    }
  ],
  "categories": [
    {
      "id": 0,
      "name": "Left hand"
    },
    {
      "id": 1,
      "name": "Partial left hand"
    },
    {
      "id": 2,
      "name": "Partial right hand"
    },
    {
      "id": 3,
      "name": "Right hand"
    }
  ]
}
```

### Session ID 提取规则

从文件名提取 session ID：

- 文件名格式：`hash__session_id_timestamp.jpg`
- 提取规则：去掉 hash 前缀，取前 4 个下划线分隔的部分
- 示例：`461ff0b4__3748_session_20251210_221855_834176_0002_000000.jpg`
  → Session ID: `3748_session_20251210_221855`

## ⚠️ 重要说明

### Category ID 映射

**CVAT 要求 category_id 从 1 开始，而不是从 0 开始！**

脚本会自动处理这个转换：
- HumanSignal: `category_id: 0, 1, 2, 3`
- CVAT: `category_id: 1, 2, 3, 4`

### 图片路径转换

脚本会自动转换图片路径：
- 原始：`images/hash__session_id.jpg`
- 转换后：`test_1000/images/session_id.jpg`（去掉 hash 前缀）

### 执行时间

- 任务创建：几秒
- 图片加载：3-5 分钟（21,000+ 张图片）
- 标注上传：1-2 分钟（39,000+ 个标注）
- **总计：约 5-10 分钟**

## 🐛 常见问题

### Q: 标注导入失败，提示 "annotation has no label"

A: 这是因为 category_id 从 0 开始。脚本已经修复了这个问题，确保使用最新版本。

### Q: 图片路径不匹配

A: 检查云存储中的图片路径格式，确保与脚本中的路径转换逻辑一致。

### Q: 如何找到某个 session 对应的 job？

A: 打开 `logs/job_session_mapping_<task_id>.json`，搜索 session ID，找到对应的 job_id。

### Q: 可以不按 session 分组吗？

A: 可以，在 `config.json` 中设置 `"use_job_file_mapping": false`，所有图片会放在一个 job 中。

## 📄 许可证

MIT License

## 👥 贡献

欢迎提交 Issue 和 Pull Request！

## 📧 联系方式

如有问题请提交 Issue。
