#!/usr/bin/env python3
"""
动态分配未开始的Jobs
扫描所有任务，找出 annotated_frames == 0 的 jobs，重新分配给指定人员
"""
import requests
import json
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# 配置日志
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f'reassign_jobs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 排除的任务（旧平台）
EXCLUDED_TASKS = {1967925}


class CVATClient:
    """CVAT客户端"""
    
    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {'Authorization': f'Token {api_key}'}
    
    def get_all_tasks(self, organization_slug=None):
        """获取所有任务"""
        url = f'{self.base_url}/api/tasks'
        params = {'page_size': 500}
        if organization_slug:
            params['org'] = organization_slug
        
        all_tasks = []
        page = 1
        
        while True:
            params['page'] = page
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            results = data.get('results', [])
            all_tasks.extend(results)
            
            if not data.get('next'):
                break
            page += 1
        
        return all_tasks
    
    def get_task_jobs(self, task_id):
        """获取任务的所有jobs"""
        url = f'{self.base_url}/api/jobs'
        params = {'task_id': task_id, 'page_size': 1000}
        
        response = requests.get(url, headers=self.headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('results', [])
    
    def get_job_annotations_count(self, job_id):
        """获取job的已标注帧数"""
        url = f'{self.base_url}/api/jobs/{job_id}/annotations'
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            annotated_frames = set()
            for shape in data.get('shapes', []):
                annotated_frames.add(shape.get('frame'))
            for track in data.get('tracks', []):
                for shape in track.get('shapes', []):
                    annotated_frames.add(shape.get('frame'))
            
            return len(annotated_frames)
        except:
            return -1  # 出错返回-1，表示无法确定
    
    def assign_job(self, job_id, assignee_id):
        """分配job给标注人员"""
        url = f'{self.base_url}/api/jobs/{job_id}'
        payload = {'assignee': assignee_id}
        headers = {**self.headers, 'Content-Type': 'application/json'}
        
        response = requests.patch(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return True
    
    def get_organization_members(self, organization_slug):
        """获取组织所有成员（包括管理员）"""
        url = f'{self.base_url}/api/memberships'
        params = {'org': organization_slug, 'page_size': 100}
        
        response = requests.get(url, headers=self.headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        members = []
        for member in data.get('results', []):
            user = member.get('user', {})
            role = member.get('role', 'worker')
            
            user_id = user.get('id')
            username = user.get('username')
            first_name = user.get('first_name', '')
            last_name = user.get('last_name', '')
            
            if first_name or last_name:
                display_name = f"{first_name} {last_name}".strip()
            else:
                display_name = username
            
            members.append({
                'id': user_id,
                'name': display_name,
                'username': username,
                'role': role
            })
        
        return members



def reassign_jobs(config_file='config.json', task_ids=None):
    """动态分配未开始的jobs"""
    logger.info("="*60)
    logger.info("动态分配未开始的Jobs")
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
    organization_slug = config.get('organization', {}).get('slug')
    
    client = CVATClient(cvat_url, api_key)
    
    # 2. 实时获取组织所有成员（包括管理员）
    logger.info("\n👥 获取组织成员...")
    all_members = client.get_organization_members(organization_slug)
    if not all_members:
        logger.error("❌ 未找到组织成员")
        return
    logger.info(f"✅ 找到 {len(all_members)} 个成员")
    
    # 3. 获取任务列表
    logger.info("\n📋 获取任务列表...")
    
    if task_ids:
        # 使用指定的任务ID
        tasks = []
        for task_id in task_ids:
            url = f'{cvat_url}/api/tasks/{task_id}'
            try:
                response = requests.get(url, headers=client.headers, timeout=30)
                response.raise_for_status()
                tasks.append(response.json())
            except Exception as e:
                logger.error(f"❌ 获取任务失败: task_id={task_id}, {e}")
    else:
        tasks = client.get_all_tasks(organization_slug)
    
    tasks = [t for t in tasks if t['id'] not in EXCLUDED_TASKS]
    logger.info(f"✅ 找到 {len(tasks)} 个任务")
    
    # 4. 扫描jobs，统计每个人的工作量（按帧数）
    logger.info("\n🔍 扫描Jobs状态...")
    unstarted_jobs = []
    user_started_frames = defaultdict(int)  # 每个人已开始的帧数（不能动的）
    
    for task in tasks:
        task_id = task['id']
        task_name = task['name']
        
        jobs = client.get_task_jobs(task_id)
        if not jobs:
            continue
        
        logger.info(f"   任务: {task_name} (ID: {task_id}) - {len(jobs)} jobs")
        
        # 并发检查每个job
        def check_job(job):
            job_id = job['id']
            annotated = client.get_job_annotations_count(job_id)
            return job, annotated
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(check_job, job) for job in jobs]
            for future in as_completed(futures):
                job, annotated = future.result()
                assignee = job.get('assignee')
                assignee_id = assignee.get('id') if assignee else None
                frame_count = job.get('stop_frame', 0) - job.get('start_frame', 0) + 1
                
                if annotated == 0:
                    # 未开始的job，可以重新分配
                    unstarted_jobs.append({
                        'job_id': job['id'],
                        'task_id': task_id,
                        'task_name': task_name,
                        'start_frame': job.get('start_frame', 0),
                        'stop_frame': job.get('stop_frame', 0),
                        'frame_count': frame_count,
                        'current_assignee': assignee.get('username') if assignee else None,
                        'current_assignee_id': assignee_id
                    })
                else:
                    # 已开始的job，统计帧数到对应人员
                    if assignee_id:
                        user_started_frames[assignee_id] += frame_count
    
    if not unstarted_jobs:
        logger.info("\n✅ 没有未开始的Jobs需要分配")
        return
    
    logger.info(f"\n📊 找到 {len(unstarted_jobs)} 个未开始的Jobs")
    
    # 5. 显示未开始的jobs
    total_unstarted_frames = sum(j['frame_count'] for j in unstarted_jobs)
    logger.info("\n未开始的Jobs列表:")
    for idx, job in enumerate(unstarted_jobs):
        current = job['current_assignee'] or '未分配'
        logger.info(f"   {idx+1}. Job {job['job_id']} ({job['frame_count']}帧) - 当前: {current}")
    logger.info(f"   共 {len(unstarted_jobs)} 个Jobs, {total_unstarted_frames} 帧")
    
    # 6. 显示所有成员，让用户选择参与分配的人
    print("\n" + "="*50)
    print("📋 组织成员列表（实时获取）:")
    print("="*50)
    for idx, m in enumerate(all_members):
        role_tag = f"[{m['role']}]" if m['role'] in ['owner', 'maintainer'] else ""
        print(f"   {idx+1}. {m['name']} (@{m['username']}) {role_tag}")
    
    # 让用户选择参与分配的人员
    print(f"\n请输入要参与分配的人员编号（用空格分隔，如: 1 2 3）")
    print(f"或输入 'all' 选择全部: ", end='')
    selection = input().strip()
    
    if selection.lower() == 'all':
        selected_assignees = all_members[:]
    else:
        try:
            indices = [int(x) - 1 for x in selection.split()]
            selected_assignees = [all_members[i] for i in indices if 0 <= i < len(all_members)]
            if not selected_assignees:
                logger.error("❌ 未选择任何人员")
                return
        except (ValueError, IndexError):
            logger.error("❌ 无效的输入")
            return
    
    logger.info(f"\n✅ 参与分配的人员 ({len(selected_assignees)} 人): {[a['name'] for a in selected_assignees]}")
    
    # 7. 按帧数平均分配
    # 统计选中人员当前已开始的帧数
    assignee_workload = {}
    for a in selected_assignees:
        started_frames = user_started_frames.get(a['id'], 0)
        assignee_workload[a['id']] = {
            'name': a['name'], 
            'started_frames': started_frames, 
            'assigned_frames': 0,
            'assigned_jobs': []
        }
    
    # 计算总帧数和目标平均值
    total_started_frames = sum(w['started_frames'] for w in assignee_workload.values())
    total_frames = total_started_frames + total_unstarted_frames
    target_frames_per_person = total_frames // len(selected_assignees)
    
    logger.info(f"\n📊 分配计算（按帧数）:")
    logger.info(f"   已开始的帧数（不可动）: {total_started_frames}")
    logger.info(f"   未开始的帧数（可分配）: {total_unstarted_frames}")
    logger.info(f"   总帧数: {total_frames}")
    logger.info(f"   目标每人: ~{target_frames_per_person} 帧")
    
    # 按帧数从大到小排序未开始的jobs（大的先分配，更容易平均）
    unstarted_jobs_sorted = sorted(unstarted_jobs, key=lambda j: j['frame_count'], reverse=True)
    
    # 贪心分配：每次把job分给当前帧数最少的人
    for job in unstarted_jobs_sorted:
        # 找当前总帧数最少的人
        min_person = min(selected_assignees, 
                        key=lambda a: assignee_workload[a['id']]['started_frames'] + assignee_workload[a['id']]['assigned_frames'])
        
        assignee_workload[min_person['id']]['assigned_frames'] += job['frame_count']
        assignee_workload[min_person['id']]['assigned_jobs'].append(job)
    
    # 显示分配预览
    logger.info(f"\n📋 分配预览:")
    for a in selected_assignees:
        w = assignee_workload[a['id']]
        total = w['started_frames'] + w['assigned_frames']
        jobs_count = len(w['assigned_jobs'])
        logger.info(f"   {w['name']}: 已有 {w['started_frames']}帧 + 分配 {w['assigned_frames']}帧 ({jobs_count}个jobs) = {total}帧")
    
    # 8. 确认分配
    print(f"\n确认按上述方案分配？(y/n): ", end='')
    confirm = input().strip().lower()
    if confirm != 'y':
        logger.info("❌ 取消分配")
        return
    
    # 9. 执行分配
    logger.info("\n🚀 开始分配...")
    success_count = 0
    fail_count = 0
    
    for a in selected_assignees:
        w = assignee_workload[a['id']]
        for job in w['assigned_jobs']:
            try:
                client.assign_job(job['job_id'], a['id'])
                logger.info(f"   ✓ Job {job['job_id']} ({job['frame_count']}帧) → {a['name']}")
                success_count += 1
            except Exception as e:
                logger.error(f"   ✗ Job {job['job_id']} 分配失败: {e}")
                fail_count += 1
    
    # 10. 完成
    logger.info("\n" + "="*60)
    logger.info(f"✅ 分配完成: 成功 {success_count}, 失败 {fail_count}")
    logger.info("="*60)
    logger.info(f"📝 日志文件: {log_file}")


def main():
    import sys
    
    task_ids = None
    if len(sys.argv) > 1:
        try:
            task_ids = [int(tid) for tid in sys.argv[1:]]
            logger.info(f"处理指定任务: {task_ids}")
        except ValueError:
            logger.error("❌ 任务ID必须是数字")
            return
    
    reassign_jobs(task_ids=task_ids)


if __name__ == "__main__":
    main()
