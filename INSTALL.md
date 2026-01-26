# 安装和运行指南

## 方法1：使用 run_simple.sh（推荐，自动配置虚拟环境）

这是最简单的方法，脚本会自动：
- 创建虚拟环境（.venv）
- 安装依赖（requests）
- 运行配置向导（如果需要）
- 测试连接
- 执行导入

```bash
./run_simple.sh
```

## 方法2：手动配置虚拟环境

```bash
# 1. 创建虚拟环境
python3 -m venv .venv

# 2. 激活虚拟环境
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置
python3 setup.py

# 5. 测试连接
python3 test_connection.py

# 6. 运行导入
python3 cvat_auto_import.py

# 7. 退出虚拟环境
deactivate
```

## 方法3：使用 uv（如果已安装）

```bash
# 直接运行，无需配置虚拟环境
uv run --no-project python3 setup.py
uv run --no-project python3 test_connection.py
uv run --no-project python3 cvat_auto_import.py
```

## 常见问题

### Q: pyproject.toml 报错？
A: 使用 `run_simple.sh` 或手动方法，不要使用 `uv run` 直接运行（项目结构不是标准 Python 包）

### Q: 虚拟环境在哪里？
A: `.venv/` 目录（已添加到 .gitignore）

### Q: 如何重新安装依赖？
A: 删除 `.venv/.installed` 文件，然后重新运行 `./run_simple.sh`

### Q: 如何清理虚拟环境？
A: 
```bash
rm -rf .venv
```

## 依赖说明

项目只依赖一个库：
- `requests>=2.31.0` - HTTP 请求库

非常轻量，安装速度快。
