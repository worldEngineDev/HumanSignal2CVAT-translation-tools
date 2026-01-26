#!/usr/bin/env python3
"""
生成 job 和 session 的映射文件
"""
import requests
import json
from pathlib import Path
from collections import defaultdict

def extract_session_id(filename):
    """提取session ID"""
    basename = filename.split('/')[-1]
    if '__' in basename:
        basename = basename.split('__', 1)[1]
    
    parts = basename.split('_')
    if len(parts) >= 4 and 'session' in basename:
        return '_'.join(parts[:4])
    return None


def generate_mapping(cvat_url, api_key, task_id, data_file):
    """生成映射"""
    print(f"\n{'='*60}")
    print(f"生成任务 {task_id} 的 Job-Session 映射")
    print(f"{'='*60}\n")
    
    headers = {'Authorization': f'Token {api_key}'}
    
    # 1. 读取原始数据，按session分组
    print(f"📖 读取数据: {data_file}")
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 按session分组
    sessions = defaultdict(lambda: {'images': [], 'image_ids': set()})
    for img in data['images']:
        session_id = extract_session_id(img['file_name'])
        if session_id:
            sessions[session_id]['images'].append(img)
            sessions[session_id]['image_ids'].add(img['id'])
    
    print(f"   找到 {len(sessions)} 个 sessions")
    
    # 2. 获取任务的所有 jobs
    print(f"\n📋 获取任务的 jobs...")
    url = f'{cvat_url}/api/jobs'
    params = {'task_id': task_id, 'page_size': 1000}
    
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    
    jobs_data = response.json()
    jobs = jobs_data.get('results', [])
    
    print(f"   找到 {len(jobs)} 个 jobs")
    
    # 3. 按 start_frame 排序
    jobs.sort(key=lambda x: x.get('start_frame', 0))
    
    # 4. 创建映射
    print(f"\n🗂️  创建映射...")
    session_names = sorted(sessions.keys())
    
    mapping = []
    for idx, job in enumerate(jobs):
        if idx < len(session_names):
            session_id = session_names[idx]
            mapping.append({
                'job_id': job['id'],
                'session_id': session_id,
                'start_frame': job.get('start_frame'),
                'stop_frame': job.get('stop_frame'),
                'frame_count': job.get('stop_frame', 0) - job.get('start_frame', 0) + 1,
                'image_count': len(sessions[session_id]['images'])
            })
    
    # 5. 保存映射
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    mapping_file = log_dir / f'job_session_mapping_{task_id}.json'
    
    with open(mapping_file, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)
    
    print(f"✅ 映射已保存: {mapping_file}")
    print(f"\n前10个映射:")
    for item in mapping[:10]:
        print(f"   Job {item['job_id']}: {item['session_id']} ({item['image_count']} 张图片)")
    
    print(f"\n总计: {len(mapping)} 个 job-session 映射")
    
    return mapping_file


if __name__ == "__main__":
    # 加载配置
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    cvat_url = config['cvat']['url'].rstrip('/')
    api_key = config['cvat']['api_key']
    data_file = config['files']['humansignal_json']
    
    task_id = input("请输入任务ID (默认 1966256): ").strip() or "1966256"
    
    generate_mapping(cvat_url, api_key, task_id, data_file)
