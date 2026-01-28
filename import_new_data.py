#!/usr/bin/env python3
"""
导入云存储中的新数据到CVAT
按session分组创建jobs，并自动分配给标注人员
"""
import requests
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# 配置日志
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f'import_new_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class CVATClient:
    """CVAT REST API客户端"""
    
    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {'Authorization': f'Token {api_key}'}
        logger.info(f"初始化CVAT客户端: {base_url}")
    
    def create_task(self, name, labels, organization_slug=None):
        """创建任务并定义标签"""
        url = f'{self.base_url}/api/tasks'
        if organization_slug:
            url = f'{url}?org={organization_slug}'
        
        payload = {
            'name': name,
            'labels': labels
        }
        
        headers = {**self.headers, 'Content-Type': 'application/json'}
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            task = response.json()
            logger.info(f"✅ 任务创建成功: ID={task['id']}, Name={name}")
            return task
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 创建任务失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"   响应内容: {e.response.text}")
            raise
    
    def attach_data_with_jobs(self, task_id, cloud_storage_id, server_files, job_file_mapping=None):
        """从云存储加载数据，可选择是否指定job分组"""
        url = f'{self.base_url}/api/tasks/{task_id}/data'
        
        payload = {
            'cloud_storage_id': cloud_storage_id,
            'server_files': server_files,
            'use_cache': True,
            'image_quality': 70,
            'storage_method': 'cache',
        }
        
        if job_file_mapping:
            payload['job_file_mapping'] = job_file_mapping
            logger.info(f"   使用 job_file_mapping: {len(job_file_mapping)} 个 jobs")
        else:
            payload['sorting_method'] = 'natural'
            logger.info(f"   不使用 job_file_mapping，使用自然排序")
        
        headers = {**self.headers, 'Content-Type': 'application/json'}
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            logger.info(f"✅ 数据加载请求已提交: task_id={task_id}")
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 加载数据失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"   响应内容: {e.response.text}")
            raise
    
    def check_task_status(self, task_id):
        """检查任务状态"""
        url = f'{self.base_url}/api/tasks/{task_id}'
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            task = response.json()
            return task.get('status'), task.get('size', 0)
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 检查任务状态失败: {e}")
            return None, 0
    
    def wait_for_data_loading(self, task_id, expected_size, timeout=3600, check_interval=30):
        """等待数据加载完成"""
        logger.info(f"⏳ 等待数据加载完成: task_id={task_id}, 预期图片数={expected_size}")
        
        start_time = time.time()
        last_size = 0
        
        while time.time() - start_time < timeout:
            try:
                status, current_size = self.check_task_status(task_id)
                elapsed = int(time.time() - start_time)
                
                if current_size != last_size:
                    progress_pct = (current_size * 100 // expected_size) if expected_size > 0 else 0
                    logger.info(f"   [{elapsed//60}分{elapsed%60}秒] 进度: {current_size}/{expected_size} ({progress_pct}%)")
                    last_size = current_size
                
                if current_size >= expected_size * 0.95:
                    logger.info(f"✅ 数据加载完成: {current_size} 张图片")
                    return True
                
                if status == 'failed':
                    logger.error(f"❌ 任务失败: task_id={task_id}")
                    return False
                    
            except Exception as e:
                logger.warning(f"   检查进度时出错: {e}")
            
            time.sleep(check_interval)
        
        logger.warning(f"⚠️  数据加载超时")
        return False
    
    def get_task_jobs(self, task_id):
        """获取任务的所有jobs"""
        url = f'{self.base_url}/api/jobs'
        params = {'task_id': task_id, 'page_size': 1000}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            jobs_data = response.json()
            jobs = jobs_data.get('results', [])
            jobs.sort(key=lambda x: x.get('start_frame', 0))
            return jobs
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 获取jobs失败: {e}")
            return []
    
    def assign_job(self, job_id, assignee_id):
        """分配job给标注人员"""
        url = f'{self.base_url}/api/jobs/{job_id}'
        
        # 注意：CVAT API 使用 assignee 字段，不是 assignee_id
        payload = {'assignee': assignee_id}
        headers = {**self.headers, 'Content-Type': 'application/json'}
        
        try:
            # PATCH更新
            response = requests.patch(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            logger.info(f"   ✓ Job {job_id} 已分配给用户 {assignee_id}")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"   ✗ 分配job失败: job_id={job_id}, {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"   响应内容: {e.response.text}")
            return False
    
    def get_organization_members(self, organization_slug):
        """获取组织成员列表"""
        url = f'{self.base_url}/api/memberships'
        params = {'org': organization_slug, 'page_size': 100}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            members = data.get('results', [])
            
            logger.info(f"✅ 获取组织成员: {len(members)} 人")
            return members
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 获取组织成员失败: {e}")
            return []


def extract_session_id(filename):
    """
    提取 chunk ID
    支持两种路径格式：
    1. 旧格式: 461ff0b4__3748_session_20251210_221855_834176_0002_000000.jpg
       Chunk ID: 3748_session_20251210_221855_834176_0002
    2. 新格式: 23dc/session_20260121_200123_268461/0001/down/labels/23dc_down_sbs_0001_undetected_frames/frame_00000.jpg
       Chunk ID: session_20260121_200123_268461_0001
    """
    # 先尝试从路径中提取 session_xxx/xxxx 格式
    parts = filename.split('/')
    for i, part in enumerate(parts):
        if part.startswith('session_'):
            # 找到 session 部分，取 session + 下一个部分（chunk编号）
            if i + 1 < len(parts):
                chunk_num = parts[i + 1]
                return f"{part}_{chunk_num}"  # session_20260121_200123_268461_0001
            else:
                return part  # 只有 session，没有 chunk
    
    # 如果路径中没找到，尝试从文件名提取（旧格式）
    basename = filename.split('/')[-1]
    if '__' in basename:
        basename = basename.split('__', 1)[1]
    
    parts = basename.split('_')
    if len(parts) >= 6 and 'session' in basename:
        return '_'.join(parts[:6])  # 3748_session_20251210_221855_834176_0002
    
    return None


def group_files_by_session(file_list):
    """按session分组文件"""
    sessions = defaultdict(list)
    
    for file_path in file_list:
        session_id = extract_session_id(file_path)
        if session_id:
            sessions[session_id].append(file_path)
        else:
            # 没有session ID的文件放到 'unknown' 组
            sessions['unknown'].append(file_path)
    
    logger.info(f"✅ 文件分组完成: {len(sessions)} 个session")
    return sessions


def import_new_data(config_file='config.json', new_images_file=None):
    """导入新数据主流程"""
    logger.info("="*60)
    logger.info("导入云存储中的新数据到CVAT")
    logger.info("="*60)
    
    # 1. 加载配置
    logger.info("\n📖 加载配置文件...")
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ 配置文件不存在: {config_file}")
        return
    
    cvat_url = config['cvat']['url']
    api_key = config['cvat']['api_key']
    cloud_storage_id = config['cloud_storage']['id']
    organization_slug = config.get('organization', {}).get('slug')
    
    # 标签配置
    labels = config.get('labels', [
        {'name': 'Left hand', 'color': '#ff00ff'},
        {'name': 'Partial left hand', 'color': '#ff00ff'},
        {'name': 'Partial right hand', 'color': '#ff00ff'},
        {'name': 'Right hand', 'color': '#ff00ff'}
    ])
    
    # 任务分配配置
    assignees = config.get('assignees', [])
    use_job_mapping = config.get('use_job_file_mapping', True)
    
    # 2. 读取新数据文件列表
    if not new_images_file:
        # 查找最新的 new_images 文件
        new_images_files = sorted(log_dir.glob('new_images_*.txt'), reverse=True)
        if not new_images_files:
            logger.error("❌ 未找到新数据文件列表")
            logger.info("💡 请先运行 check_annotation_status.py 生成新数据列表")
            return
        new_images_file = new_images_files[0]
    
    logger.info(f"\n📖 读取新数据文件列表: {new_images_file}")
    
    with open(new_images_file, 'r', encoding='utf-8') as f:
        new_files = [line.strip() for line in f if line.strip()]
    
    if not new_files:
        logger.info("✅ 没有新数据需要导入")
        return
    
    logger.info(f"✅ 找到 {len(new_files)} 个新文件")
    
    # 3. 按session分组
    logger.info(f"\n📊 按session分组...")
    sessions = group_files_by_session(new_files)
    
    # 4. 准备job_file_mapping
    job_file_mapping = []
    session_names = []
    all_files = []
    
    for session_id in sorted(sessions.keys()):
        session_files = sessions[session_id]
        job_file_mapping.append(session_files)
        session_names.append(session_id)
        all_files.extend(session_files)
        logger.info(f"   Session {session_id}: {len(session_files)} 张图片")
    
    logger.info(f"✅ 分组完成: {len(job_file_mapping)} 个jobs, {len(all_files)} 张图片")
    
    # 5. 创建CVAT客户端
    client = CVATClient(cvat_url, api_key)
    
    # 6. 创建任务
    task_name = f"New Data Import - {datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger.info(f"\n🏗️  创建任务: {task_name}")
    
    try:
        task = client.create_task(task_name, labels, organization_slug)
        task_id = task['id']
    except Exception as e:
        logger.error(f"❌ 创建任务失败: {e}")
        return
    
    # 7. 加载图片
    logger.info(f"\n📁 加载图片...")
    logger.info(f"   总图片数: {len(all_files)}")
    logger.info(f"   Jobs数量: {len(job_file_mapping)}")
    
    try:
        if use_job_mapping:
            client.attach_data_with_jobs(task_id, cloud_storage_id, all_files, job_file_mapping)
        else:
            client.attach_data_with_jobs(task_id, cloud_storage_id, all_files, None)
    except Exception as e:
        logger.error(f"❌ 加载数据失败: {e}")
        return
    
    # 8. 等待数据加载完成
    logger.info(f"\n⏳ 等待数据加载完成...")
    if not client.wait_for_data_loading(task_id, len(all_files), timeout=3600, check_interval=30):
        logger.error(f"❌ 数据加载超时或失败")
        return
    
    # 9. 获取jobs并分配
    logger.info(f"\n👥 分配任务...")
    jobs = client.get_task_jobs(task_id)
    
    if not jobs:
        logger.warning("⚠️  未找到jobs")
    else:
        logger.info(f"   找到 {len(jobs)} 个jobs")
        
        # 如果配置了assignees，自动分配
        if assignees:
            logger.info(f"   开始自动分配给 {len(assignees)} 个标注人员...")
            
            for idx, job in enumerate(jobs):
                job_id = job['id']
                session_id = session_names[idx] if idx < len(session_names) else 'unknown'
                
                # 轮询分配
                assignee = assignees[idx % len(assignees)]
                assignee_id = assignee.get('id')
                assignee_name = assignee.get('name', assignee_id)
                
                if assignee_id:
                    client.assign_job(job_id, assignee_id)
                    logger.info(f"   Job {job_id} ({session_id}) → {assignee_name}")
        else:
            logger.info("   ℹ️  未配置assignees，跳过自动分配")
            logger.info("   💡 可在config.json中配置assignees进行自动分配")
    
    # 10. 保存job-session映射
    mapping_file = log_dir / f'job_session_mapping_{task_id}.json'
    mapping = []
    
    for idx, job in enumerate(jobs):
        if idx < len(session_names):
            mapping.append({
                'job_id': job['id'],
                'session_id': session_names[idx],
                'start_frame': job.get('start_frame'),
                'stop_frame': job.get('stop_frame'),
                'frame_count': job.get('stop_frame', 0) - job.get('start_frame', 0) + 1
            })
    
    with open(mapping_file, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\n📋 Job-Session映射已保存: {mapping_file}")
    
    # 11. 完成
    logger.info("\n" + "="*60)
    logger.info("✅ 导入完成！")
    logger.info("="*60)
    logger.info(f"任务ID: {task_id}")
    logger.info(f"任务名称: {task_name}")
    logger.info(f"Jobs数量: {len(jobs)}")
    logger.info(f"总图片数: {len(all_files)}")
    logger.info(f"\n🔗 CVAT链接: {cvat_url}/tasks/{task_id}")
    logger.info(f"📝 日志文件: {log_file}")


def main():
    """命令行入口"""
    import sys
    
    new_images_file = None
    if len(sys.argv) > 1:
        new_images_file = sys.argv[1]
    
    import_new_data(new_images_file=new_images_file)


if __name__ == "__main__":
    main()
