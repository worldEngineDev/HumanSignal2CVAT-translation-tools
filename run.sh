#!/bin/bash
# CVAT自动化导入 - 简化版一键运行脚本（自动配置虚拟环境）

set -e

echo "======================================"
echo "CVAT HumanSignal 自动化导入工具"
echo "======================================"
echo ""

# 检查 Python 版本
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3，请先安装 Python 3.8+"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "🐍 Python 版本: $PYTHON_VERSION"
echo ""

# 检查并创建虚拟环境
if [ ! -d ".venv" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv .venv
    echo "✅ 虚拟环境创建完成"
    echo ""
fi

# 激活虚拟环境
echo "🔧 激活虚拟环境..."
source .venv/bin/activate

# 检查并安装依赖
if [ ! -f ".venv/.installed" ]; then
    echo "📦 安装依赖..."
    # 使用虚拟环境的 pip
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q -r requirements.txt
    touch .venv/.installed
    echo "✅ 依赖安装完成"
    echo ""
fi

# 检查配置文件
if [ ! -f "config.json" ]; then
    echo "❌ 配置文件不存在"
    echo "📝 运行配置向导..."
    echo ""
    python3 setup.py
    echo ""
fi

# 测试连接
echo "🔍 测试CVAT连接..."
echo ""
python3 test_connection.py
echo ""

# 确认运行
read -p "是否继续运行导入？(y/n): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "已取消"
    deactivate
    exit 0
fi

# 运行导入
echo ""
echo "🚀 开始导入..."
echo ""
python3 cvat_auto_import.py

echo ""
echo "======================================"
echo "✅ 完成！"
echo "======================================"

# 退出虚拟环境
deactivate
