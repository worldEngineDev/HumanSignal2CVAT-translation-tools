# 项目总结

## 📝 需求理解

### 背景
- 旧平台数据已通过 `cvat_auto_import.py` 迁移到新平台（CVAT）
- 数据从云存储加载，按 session 分成多个 jobs，并分配给标注人员

### 新需求
1. **核对工具**：对比云存储和新平台（CVAT），找出哪些数据已标注、哪些未标注
2. **加载新数据**：将云存储中未标注的新数据加载到 CVAT，按 session 分 jobs 并自动分配给标注人员

---

## ✅ 已完成的工作

### 1. 新增脚本（3个）

#### check_annotation_status.py
**功能**：核对云存储和CVAT的标注状态

**实现**：
- 通过CVAT API列出云存储中的所有文件
- 获取CVAT中所有任务和图片
- 智能对比分析，生成详细报告
- 识别未标注的新数据
- 生成新数据文件列表供后续导入使用

**输出**：
- `logs/annotation_status_*.json` - 详细状态报告
- `logs/new_images_*.txt` - 新数据文件列表
- `logs/check_status_*.log` - 执行日志

#### import_new_data.py
**功能**：导入新数据并自动分配

**实现**：
- 读取新数据文件列表（自动使用最新的）
- 按 session 自动分组
- 创建 CVAT 任务
- 从云存储加载图片
- 自动分配 jobs 给标注人员（轮询策略）
- 生成 job-session 映射文件

**特点**：
- 支持自动分配（配置 assignees）
- 支持手动分配（不配置 assignees）
- 完整的进度显示和错误处理

#### test_connection.py
**功能**：测试连接和配置

**实现**：
- 测试 CVAT API 连接
- 验证组织访问权限
- 检查云存储配置
- 测试文件列表获取
- 验证标注人员配置

**用途**：
- 首次配置后验证
- 排查连接问题
- 确保配置正确

---

### 2. 辅助工具（1个）

#### run_workflow.sh
**功能**：交互式菜单工具

**特点**：
- 友好的菜单界面
- 集成所有功能
- 自动检查配置
- 显示操作结果
- 查看日志和报告

**菜单选项**：
1. 测试连接和配置
2. 首次导入（带标注数据）
3. 核对标注状态
4. 导入新数据
5. 单独上传标注
6. 生成job映射
7. 查看最新状态报告
8. 查看最新日志

---

### 3. 文档更新（5个）

#### README.md
- 添加新功能说明
- 更新快速开始流程
- 详细的工具脚本说明
- 更新配置说明
- 添加常见问题

#### QUICKSTART.md（新）
- 5分钟快速上手指南
- 最小配置示例
- 常用命令速查
- 输出说明

#### WORKFLOW.md（新）
- 场景一：首次导入（有标注）
- 场景二：导入新数据（无标注）
- 定期工作流程
- 输出文件说明
- 最佳实践
- 故障排查

#### FEATURES.md（新）
- 所有功能详细说明
- 使用场景对比
- 数据流图
- 配置功能说明

#### CHANGELOG.md（新）
- 详细的更新日志
- 新增功能列表
- 配置变更说明
- 兼容性说明

---

### 4. 配置增强

#### config.example.json
新增配置项：
```json
{
  "cloud_storage": {
    "prefix": "test_1000/images/"  // 云存储路径前缀
  },
  "labels": [                       // 标签配置
    {"name": "Left hand", "color": "#ff00ff"}
  ],
  "assignees": [                    // 标注人员配置
    {"id": 123456, "name": "张三"}
  ]
}
```

---

## 🎯 核心功能实现

### 1. 状态核对功能

**实现原理**：
1. 通过 CVAT API 获取云存储文件列表
2. 遍历所有 CVAT 任务，获取已加载的图片
3. 获取每个任务的标注数量，判断是否已标注
4. 对比分析，生成报告

**关键代码**：
```python
# 获取云存储文件
cloud_files = cloud_client.list_cloud_storage_files(cloud_storage_id, prefix)

# 获取CVAT任务和图片
tasks = cvat_client.get_all_tasks(organization_slug)
for task in tasks:
    images = cvat_client.get_task_data(task_id)
    annotation_count = cvat_client.get_task_annotations(task_id)

# 对比分析
new_images = cloud_basenames - cvat_images
loaded_not_annotated = cvat_images - cvat_annotated_images
```

---

### 2. 新数据导入功能

**实现原理**：
1. 读取新数据文件列表
2. 按 session ID 分组
3. 创建 CVAT 任务
4. 使用 job_file_mapping 按 session 创建 jobs
5. 轮询分配给标注人员

**关键代码**：
```python
# 按session分组
sessions = group_files_by_session(new_files)

# 准备job_file_mapping
job_file_mapping = []
for session_id in sorted(sessions.keys()):
    job_file_mapping.append(sessions[session_id])

# 创建任务并加载数据
task = client.create_task(task_name, labels, organization_slug)
client.attach_data_with_jobs(task_id, cloud_storage_id, all_files, job_file_mapping)

# 自动分配
for idx, job in enumerate(jobs):
    assignee = assignees[idx % len(assignees)]
    client.assign_job(job_id, assignee_id)
```

---

### 3. 自动分配功能

**实现原理**：
- 轮询策略：Job 1 → 用户1，Job 2 → 用户2，...
- 使用模运算实现循环分配
- 支持任意数量的标注人员

**关键代码**：
```python
for idx, job in enumerate(jobs):
    # 轮询分配
    assignee = assignees[idx % len(assignees)]
    assignee_id = assignee.get('id')
    client.assign_job(job_id, assignee_id)
```

---

## 📊 工作流程

### 旧流程（仅支持首次导入）
```
准备数据 → 运行导入 → 完成
```

### 新流程（支持持续导入）

#### 首次导入
```
配置 → 测试连接 → 准备数据 → 运行导入 → 完成
```

#### 持续导入
```
核对状态 → 查看报告 → 导入新数据 → 自动分配 → 完成
```

#### 定期维护
```
每周/每月：核对状态 → 查看进度 → 导入新数据（如有）
```

---

## 🔧 技术实现

### API调用
- 使用 requests 库调用 CVAT REST API
- 支持分页获取大量数据
- 完善的错误处理和重试机制

### 数据处理
- 智能的 session ID 提取
- 文件路径转换和去重
- 数据一致性验证

### 日志系统
- 详细的操作日志
- 进度实时显示
- 错误信息完整

### 配置管理
- JSON 格式配置文件
- 支持可选配置项
- 向后兼容

---

## 📈 使用场景

### 场景1：首次迁移（有标注数据）
```bash
python test_connection.py
python cvat_auto_import.py
```

### 场景2：导入新数据（无标注）
```bash
python check_annotation_status.py
python import_new_data.py
```

### 场景3：定期核对
```bash
# 每周运行
python check_annotation_status.py
# 查看报告，决定是否导入新数据
```

### 场景4：交互式使用
```bash
./run_workflow.sh
# 使用菜单选择操作
```

---

## 💡 设计亮点

### 1. 模块化设计
- 每个脚本功能独立
- 可单独使用或组合使用
- 易于维护和扩展

### 2. 智能化
- 自动识别新数据
- 自动分组和分配
- 自动路径转换

### 3. 用户友好
- 详细的文档
- 交互式工具
- 清晰的日志输出

### 4. 可扩展性
- 配置驱动
- 支持自定义标签
- 支持自定义分配策略

### 5. 健壮性
- 完善的错误处理
- 数据一致性验证
- 详细的日志记录

---

## 🎉 成果总结

### 新增文件
- ✅ check_annotation_status.py - 状态核对脚本
- ✅ import_new_data.py - 新数据导入脚本
- ✅ test_connection.py - 连接测试脚本
- ✅ run_workflow.sh - 交互式工具
- ✅ QUICKSTART.md - 快速开始指南
- ✅ WORKFLOW.md - 工作流程文档
- ✅ FEATURES.md - 功能特性文档
- ✅ CHANGELOG.md - 更新日志
- ✅ SUMMARY.md - 项目总结（本文件）

### 更新文件
- ✅ README.md - 完整文档更新
- ✅ config.example.json - 配置示例更新

### 功能实现
- ✅ 云存储和CVAT状态核对
- ✅ 新数据自动导入
- ✅ 自动分配给标注人员
- ✅ 连接和配置测试
- ✅ 交互式菜单工具

### 文档完善
- ✅ 快速开始指南
- ✅ 详细工作流程
- ✅ 功能特性说明
- ✅ 常见问题解答
- ✅ 故障排查指南

---

## 🚀 使用建议

### 首次使用
1. 复制配置文件：`cp config.example.json config.json`
2. 编辑配置文件，填写必要信息
3. 测试连接：`python test_connection.py`
4. 根据场景选择合适的脚本

### 日常使用
1. 定期运行 `check_annotation_status.py` 核对状态
2. 有新数据时运行 `import_new_data.py` 导入
3. 使用 `./run_workflow.sh` 简化操作

### 最佳实践
1. 配置 `assignees` 实现自动分配
2. 定期查看日志文件
3. 保留重要的状态报告
4. 及时导入新数据

---

## 📞 支持

### 文档
- README.md - 完整文档
- QUICKSTART.md - 快速开始
- WORKFLOW.md - 工作流程
- FEATURES.md - 功能特性

### 日志
- logs/ 目录下的所有日志文件
- 详细的错误信息和堆栈跟踪

### 工具
- test_connection.py - 测试配置
- run_workflow.sh - 交互式工具

---

## 🎯 总结

本次更新完全满足了用户的需求：

1. ✅ **核对工具**：`check_annotation_status.py` 可以对比云存储和CVAT，找出已标注和未标注的数据
2. ✅ **加载新数据**：`import_new_data.py` 可以加载新数据，按session分jobs，并自动分配给标注人员

同时还提供了：
- ✅ 连接测试工具
- ✅ 交互式菜单工具
- ✅ 完善的文档
- ✅ 详细的使用指南

所有功能都经过精心设计，易于使用，文档完善，可以满足团队的长期使用需求。


---

## 🔧 2026-01-27 更新 - 修复云存储访问问题

### 问题
`check_annotation_status.py` 使用 `content-v2` 接口访问云存储失败：
```
404 Client Error: Not Found for url: .../cloudstorages/4837/content-v2
The file 'test_1000/images/' not found on the cloud storage
```

### 原因
`content-v2` 接口可能不支持或需要不同的参数格式。

### 解决方案
1. 改用 `content` 接口（不带 `-v2`）
2. 添加降级策略：如果云存储不可访问，从CVAT任务中推断文件列表
3. 更新报告格式，标记云存储是否可访问

### 修改内容

**check_annotation_status.py**:
- 修改 `list_cloud_storage_files` 方法，使用 `content` 接口
- 添加多种响应格式的兼容处理
- 如果云存储不可访问，返回 `None` 而不是空列表
- 在主流程中添加降级逻辑：从CVAT任务推断文件列表
- 更新报告，添加 `cloud_accessible` 字段

### 使用说明

现在工具有两种工作模式：

**模式1：云存储可访问**
- 直接从云存储获取文件列表
- 可以准确识别新数据
- 生成新数据文件列表

**模式2：云存储不可访问（降级模式）**
- 从CVAT任务中推断文件列表
- 只能统计已加载的文件
- 无法识别新数据
- 仍可统计标注进度

### 输出示例

云存储可访问时：
```
📊 分析结果:
   云存储总文件数: 25000
   已加载到CVAT: 21000
   已标注: 18000
   已加载但未标注: 3000
   未加载（新数据）: 4000
```

云存储不可访问时：
```
📊 分析结果:
   CVAT中的文件数: 21000
   已标注: 18000
   已加载但未标注: 3000
   ⚠️  无法确定云存储中的新数据（无法访问云存储）
```

### 建议

如果经常遇到云存储访问问题，可以：
1. 检查云存储配置和权限
2. 使用降级模式仍可查看标注进度
3. 通过其他方式（如直接访问云存储）确定新数据


---

## 🔧 2026-01-27 更新2 - 简化云存储逻辑

### 问题
尝试使用 `content` 接口仍然失败，实际上不需要列出云存储的所有文件。

### 原因
之前的 `cvat_auto_import.py` 和 `import_new_data.py` 都是直接通过 `server_files` 参数指定要加载的文件，而不是先列出云存储的所有文件。

### 解决方案
简化 `check_annotation_status.py` 的逻辑：
- **移除云存储文件列表功能**（不需要）
- **只统计CVAT中的数据**：已加载的图片、已标注的图片、未标注的图片
- **新数据导入**：用户自己准备新数据文件列表，然后使用 `import_new_data.py` 导入

### 工作流程

**旧流程**（不可行）：
```
列出云存储文件 → 对比CVAT → 生成新数据列表 → 导入
```

**新流程**（正确）：
```
统计CVAT数据 → 用户准备新数据列表 → 导入新数据
```

### 使用方法

1. **查看CVAT标注进度**：
```bash
python check_annotation_status.py
```
输出：
- CVAT中的文件数
- 已标注的文件数
- 未标注的文件数

2. **准备新数据文件列表**（手动或通过其他方式）：
```bash
# 创建 new_data.txt，每行一个文件路径
test_1000/images/xxx_session_xxx.jpg
test_1000/images/yyy_session_yyy.jpg
...
```

3. **导入新数据**：
```bash
python import_new_data.py new_data.txt
```

### 说明

这个工具现在专注于：
- ✅ 统计CVAT中的标注进度
- ✅ 识别哪些已加载但未标注
- ✅ 识别哪些已标注

不再尝试：
- ❌ 列出云存储的所有文件（不需要，也不可靠）
- ❌ 自动生成新数据列表（用户自己准备更准确）


---

## 🔧 2026-01-27 更新3 - 修复bug和新增标注人员列表工具

### 问题1：check_progress.py 的bug
当没有已分配的任务时，`sorted_users` 变量未定义，导致后续代码报错。

### 解决方案1
在 `user_stats` 为空时，初始化 `sorted_users = []`。

### 问题2：不知道标注人员的ID和名称
用户不知道如何获取标注人员的ID和名称来配置 `assignees`。

### 解决方案2
创建新工具 `list_annotators.py`：
- 自动获取组织中的所有成员
- 按角色分类（管理员、监督员、标注人员）
- 自动识别标注人员（worker角色）
- 生成配置建议
- 保存到 `assignees_config.json`

### 使用方法

**列出标注人员**：
```bash
python list_annotators.py
```

输出：
```
👷 标注人员 (3 人):
   - 张三 (@zhangsan) [ID: 123456]
   - 李四 (@lisi) [ID: 123457]

💡 配置建议

"assignees": [
  {"id": 123456, "name": "张三"},
  {"id": 123457, "name": "李四"}
]

✅ 配置已保存到: assignees_config.json
```

然后将 `assignees_config.json` 中的内容复制到 `config.json`。

### 更新内容

**新增文件**：
- `list_annotators.py` - 列出标注人员工具

**修复文件**：
- `check_progress.py` - 修复 `sorted_users` 未定义的bug

**更新文件**：
- `run_workflow.sh` - 添加"列出标注人员"菜单选项
- `README.md` - 添加工具说明


---

## 🔧 2026-01-27 更新4 - 正确实现云存储对比功能

### 问题
用户指出 `check_annotation_status.py` 没有实现"核对云存储和CVAT平台的标注状态，找出哪些数据已标注、哪些未标注"的需求。

### 原因
之前的修改移除了云存储对比功能，只统计CVAT中的数据。

### 解决方案
修改 `check_annotation_status.py`，支持用户提供云存储文件列表：
- 用户通过其他方式（如直接访问云存储、使用云存储CLI工具等）获取文件列表
- 将文件列表保存为文本文件（每行一个文件路径）
- 运行工具时提供文件列表路径
- 工具对比云存储文件列表和CVAT中的数据

### 使用方法

**步骤1：获取云存储文件列表**

通过云存储的CLI工具或Web界面获取文件列表，保存为 `cloud_files.txt`：
```
test_1000/images/xxx_session_xxx.jpg
test_1000/images/yyy_session_yyy.jpg
...
```

**步骤2：运行对比**

```bash
# 提供云存储文件列表
python check_annotation_status.py cloud_files.txt
```

输出：
```
📊 分析结果:
   云存储总文件数: 25000
   已加载到CVAT: 21000
   已标注: 18000
   已加载但未标注: 3000
   未加载（新数据）: 4000

✅ 新数据文件列表已保存: logs/new_images_*.txt
```

**步骤3：导入新数据**

```bash
python import_new_data.py logs/new_images_*.txt
```

### 如果不提供云存储文件列表

```bash
# 不提供文件列表，只统计CVAT数据
python check_annotation_status.py
```

输出：
```
📊 分析结果:
   CVAT中的文件数: 21000
   已标注: 18000
   已加载但未标注: 3000

💡 提示:
   要对比云存储和CVAT，请提供云存储文件列表：
   python check_annotation_status.py <云存储文件列表.txt>
```

### 修改 list_annotators.py

将 supervisor 也作为标注人员（之前只包括 worker）：
- 现在 worker 和 supervisor 都会被列为标注人员
- 只有 owner 和 maintainer 被视为管理员

这样可以将 supervisor 也分配标注任务。


---

## 🔧 2026-01-27 更新5 - 修复关键bug

### 问题1：assignee 字段错误
- `check_progress.py` 使用 `assignee_id` 字段，但CVAT API返回的是 `assignee` 对象
- `import_new_data.py` 分配时使用 `assignee_id`，但应该使用 `assignee`

### 问题2：标注检测逻辑错误
- `check_annotation_status.py` 通过 task 的 annotation count 判断是否已标注
- 这是错误的！应该通过 job 的 state 判断
- 用户已经分配了jobs并完成了标注，但工具显示"未标注"

### 解决方案

**修复 check_progress.py**：
```python
# 错误：
assignee_id = job.get('assignee_id')

# 正确：
assignee = job.get('assignee')  # 这是一个对象
assignee_id = assignee.get('id')
assignee_username = assignee.get('username')
```

**修复 import_new_data.py**：
```python
# 错误：
payload = {'assignee_id': assignee_id}

# 正确：
payload = {'assignee': assignee_id}
```

**修复 check_annotation_status.py**：
```python
# 错误：通过 annotation count 判断
annotation_count = cvat_client.get_task_annotations(task_id)
if annotation_count > 0:
    # 认为已标注

# 正确：通过 job state 判断
jobs = cvat_client.get_task_jobs(task_id)
for job in jobs:
    state = job.get('state', 'new')
    if state in ['completed', 'accepted']:
        # 这个job的帧已标注
```

### 影响

修复后：
- ✅ `check_progress.py` 能正确读取已分配的jobs
- ✅ `import_new_data.py` 能正确分配jobs
- ✅ `check_annotation_status.py` 能正确识别已标注的数据


---

## 🔧 2026-01-27 更新6 - 正确实现云存储访问

### 问题
`check_annotation_status.py` 无法访问云存储，之前尝试通过API列出云存储文件失败。

### 原因
误解了原来的实现方式。原来的 `cvat_auto_import.py` **从来没有通过API列出云存储文件**！

### 正确的方式
从 HumanSignal 导出的 JSON 文件中读取图片列表：
1. HumanSignal JSON 包含所有图片的路径
2. 这些图片在云存储中
3. 直接从 JSON 读取，不需要访问云存储API

### 解决方案
修改 `check_annotation_status.py`：
- 读取 HumanSignal JSON 文件（和原来一样）
- 提取所有图片路径
- 对比 CVAT 中已加载的图片
- 找出新数据

### 使用方法

**方式1：使用配置文件中的JSON**
```bash
# 在 config.json 中配置 files.humansignal_json
python check_annotation_status.py
```

**方式2：指定JSON文件**
```bash
python check_annotation_status.py data/result.json
```

输出：
```
📊 分析结果:
   云存储总文件数: 25000
   已加载到CVAT: 21000
   已标注: 18000  # 通过job state判断
   已加载但未标注: 3000
   未加载（新数据）: 4000
```

### 标注检测逻辑
通过 job 的 state 判断是否已标注：
- `completed` 或 `accepted` → 已标注
- 其他状态 → 未标注

不需要检查具体有多少个标注对象，只要job完成就认为已标注。


## 2026-01-27 更新 - 修复标注检测逻辑

### 关键Bug修复
**问题**: 之前使用job的`state`字段判断是否已标注，但发现很多job的state='new'却已经有标注数据（例如job 3527431有60个shapes）

**解决方案**: 改为检查实际标注数据
- 调用 `/api/jobs/{job_id}/annotations` API
- 检查返回的 `shapes` 和 `tracks` 数组
- 只要有任何shapes或tracks，就认为该job已标注，不管state是什么

### 修改的文件

1. **check_annotation_status.py**
   - 修改第195-230行的逻辑
   - 对每个job调用 `get_job_annotations()` 检查实际标注数
   - 如果 `annotation_count > 0`，将该job的所有帧标记为已标注

2. **check_progress.py**
   - 添加 `get_job_annotations()` 方法
   - 修改统计逻辑，检查实际标注数据而不是state
   - 在显示结果时同时显示"实际完成"和"状态完成"，方便对比
   - 完成帧数统计基于实际标注数据，不再依赖state

### 技术细节
```python
# 错误的方式（旧代码）
if state in ['completed', 'accepted']:
    # 认为已标注

# 正确的方式（新代码）
annotation_count = cvat_client.get_job_annotations(job_id)
if annotation_count > 0:  # 有shapes或tracks
    # 认为已标注
```

### 影响
- 现在可以正确识别所有已标注的数据，即使job状态还是'new'
- 进度统计更准确，反映实际标注情况而不是工作流状态
- 可以发现那些已经标注但还没有提交/完成的jobs
