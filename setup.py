#!/usr/bin/env python3
"""
初始化配置文件
"""
import json
import os
from pathlib import Path

def setup_config():
    """创建配置文件"""
    print("="*60)
    print("CVAT自动化导入工具 - 配置向导")
    print("="*60)
    
    # 检查是否已存在配置文件
    if os.path.exists('config.json'):
        print("\n⚠️  配置文件已存在: config.json")
        response = input("是否覆盖? (y/n): ").strip().lower()
        if response != 'y':
            print("已取消")
            return
    
    print("\n请输入以下信息:")
    print("-"*60)
    
    # 1. CVAT服务器地址
    print("\n1. CVAT服务器地址")
    print("   示例: https://app.cvat.ai")
    print("   提示: 打开CVAT网页，查看浏览器地址栏")
    cvat_url = input("   URL: ").strip()
    
    # 2. API Key
    print("\n2. API Key")
    print("   提示: 在CVAT中获取（Settings → API Key）")
    api_key = input("   API Key: ").strip()
    
    # 3. 云存储ID
    print("\n3. 云存储ID")
    print("   当前值: 4837")
    cloud_storage_id = input("   云存储ID (直接回车使用4837): ").strip()
    if not cloud_storage_id:
        cloud_storage_id = 4837
    else:
        cloud_storage_id = int(cloud_storage_id)
    
    # 4. 数据文件路径
    print("\n4. HumanSignal数据文件")
    print("   示例: data/result.json")
    print("   或: export_221984_project-221984-at-2026-01-26-02-11-461f6d87/result.json")
    data_file = input("   文件路径 (直接回车使用data/result.json): ").strip()
    if not data_file:
        data_file = "data/result.json"
    
    # 5. 任务名称
    print("\n5. CVAT任务名称")
    task_name = input("   任务名称 (直接回车使用默认): ").strip()
    if not task_name:
        task_name = "Hand Detection - HumanSignal Import"
    
    # 创建配置
    config = {
        "cvat": {
            "url": cvat_url,
            "api_key": api_key
        },
        "cloud_storage": {
            "id": cloud_storage_id,
            "name": "Annotation"
        },
        "files": {
            "humansignal_json": data_file
        },
        "task": {
            "name": task_name
        }
    }
    
    # 保存配置
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print("✅ 配置文件已创建: config.json")
    print("="*60)
    print("\n📋 配置摘要:")
    print(f"   CVAT URL: {cvat_url}")
    print(f"   API Key: {api_key[:20]}...")
    print(f"   云存储ID: {cloud_storage_id}")
    print(f"   数据文件: {data_file}")
    print(f"   任务名称: {task_name}")
    
    print("\n🔒 安全提示:")
    print("   - config.json 已添加到 .gitignore")
    print("   - 不要将此文件提交到git仓库")
    print("   - 不要分享给他人")
    
    print("\n🚀 下一步:")
    print("   1. 测试连接: python3 test_connection.py")
    print("   2. 运行导入: python3 cvat_auto_import.py")


def main():
    """命令行入口"""
    setup_config()


if __name__ == "__main__":
    main()
