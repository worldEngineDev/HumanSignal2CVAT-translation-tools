#!/usr/bin/env python3
"""
列出组织中的标注人员
自动识别权限较低的成员（通常是标注人员）
"""
import requests
import json
import sys

def list_annotators(config_file='config.json'):
    """列出标注人员"""
    print("="*60)
    print("获取组织成员列表")
    print("="*60)
    
    # 1. 加载配置
    print("\n📖 加载配置文件...")
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"❌ 配置文件不存在: {config_file}")
        return
    
    cvat_url = config['cvat']['url'].rstrip('/')
    api_key = config['cvat']['api_key']
    organization_slug = config.get('organization', {}).get('slug')
    
    if not organization_slug:
        print("❌ 配置中未找到组织slug")
        return
    
    headers = {'Authorization': f'Token {api_key}'}
    
    # 2. 获取组织成员
    print(f"\n👥 获取组织成员...")
    url = f'{cvat_url}/api/memberships'
    params = {'org': organization_slug, 'page_size': 100}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        members = data.get('results', [])
        
        print(f"✅ 找到 {len(members)} 个成员\n")
        
        # 3. 分类成员
        admins = []
        annotators = []  # 包括 worker 和 supervisor
        
        for member in members:
            user = member.get('user', {})
            role = member.get('role', 'worker')
            
            user_id = user.get('id')
            username = user.get('username')
            email = user.get('email', '')
            first_name = user.get('first_name', '')
            last_name = user.get('last_name', '')
            
            # 构建显示名称
            if first_name or last_name:
                display_name = f"{first_name} {last_name}".strip()
            else:
                display_name = username
            
            member_info = {
                'id': user_id,
                'username': username,
                'display_name': display_name,
                'email': email,
                'role': role
            }
            
            if role == 'owner' or role == 'maintainer':
                admins.append(member_info)
            else:  # worker 或 supervisor 都作为标注人员
                annotators.append(member_info)
        
        # 4. 显示结果
        print("="*60)
        print("成员列表（按角色分类）")
        print("="*60)
        
        if admins:
            print(f"\n🔑 管理员 ({len(admins)} 人):")
            for m in admins:
                print(f"   - {m['display_name']} (@{m['username']}) [ID: {m['id']}]")
                print(f"     角色: {m['role']}, 邮箱: {m['email']}")
        
        if annotators:
            print(f"\n👷 标注人员 ({len(annotators)} 人，包括 worker 和 supervisor):")
            for m in annotators:
                print(f"   - {m['display_name']} (@{m['username']}) [ID: {m['id']}]")
                print(f"     角色: {m['role']}, 邮箱: {m['email']}")
        
        # 5. 更新 config.json
        print("\n" + "="*60)
        print("💡 更新配置")
        print("="*60)
        
        if annotators:
            assignees_list = [
                {"id": m['id'], "name": m['display_name']}
                for m in annotators
            ]
            
            # 更新 config.json
            config['assignees'] = assignees_list
            
            try:
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                
                print(f"\n✅ 已更新 {config_file} 中的 assignees 字段")
                print(f"   共 {len(assignees_list)} 个标注人员")
            except Exception as e:
                print(f"\n❌ 更新配置文件失败: {e}")
                print("\n手动添加以下内容到 config.json 的 assignees 字段：")
                print("\n\"assignees\": [")
                for i, m in enumerate(annotators):
                    comma = "," if i < len(annotators) - 1 else ""
                    print(f"  {{\"id\": {m['id']}, \"name\": \"{m['display_name']}\"}}{comma}")
                print("]")
        else:
            print("\n⚠️  未找到标注人员")
            print("   所有成员都是管理员")
        
        # 6. 显示所有成员的简化列表
        print("\n" + "="*60)
        print("📋 所有成员简化列表")
        print("="*60)
        
        all_members = admins + annotators
        for m in all_members:
            print(f"{m['id']}\t{m['display_name']}\t{m['role']}")
        
    except Exception as e:
        print(f"❌ 获取成员列表失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   响应内容: {e.response.text}")


if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    list_annotators(config_file)
