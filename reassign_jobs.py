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
    
    # 4. 扫描jobs，统计每个人的工作量
    logger.info("\n🔍 扫描Jobs状态...")
    unstarted_jobs = []
    user_started_jobs = defaultdict(int)  # 每个人已开始的jobs数量（不能动的）
    
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
                
                if annotated == 0:
                    # 未开始的job，可以重新分配
                    unstarted_jobs.append({
                        'job_id': job['id'],
                        'task_id': task_id,
                        'task_name': task_name,
                        'start_frame': job.get('start_frame', 0),
                        'stop_frame': job.get('stop_frame', 0),
                        'current_assignee': assignee.get('username') if assignee else None,
                        'current_assignee_id': assignee_id
                    })
                else:
                    # 已开始的job，统计到对应人员
                    if assignee_id:
                        user_started_jobs[assignee_id] += 1
    
    if not unstarted_jobs:
        logger.info("\n✅ 没有未开始的Jobs需要分配")
        return
    
    logger.info(f"\n📊 找到 {len(unstarted_jobs)} 个未开始的Jobs")
    
    # 5. 显示未开始的jobs
    logger.info("\n未开始的Jobs列表:")
    for idx, job in enumerate(unstarted_jobs):
        frame_count = job['stop_frame'] - job['start_frame'] + 1
        current = job['current_assignee'] or '未分配'
        logger.info(f"   {idx+1}. Job {job['job_id']} ({frame_count}帧) - 当前: {current}")
    
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
    
    # 7. 计算平均分配方案
    # 统计选中人员当前已开始的jobs数量（annotated > 0 的，不能动）
    assignee_workload = {}
    for a in selected_assignees:
        started = user_started_jobs.get(a['id'], 0)
        assignee_workload[a['id']] = {'name': a['name'], 'started': started, 'will_assign': 0}
    
    # 计算总jobs数和目标平均值
    total_started = sum(w['started'] for w in assignee_workload.values())
    total_jobs = total_started + len(unstarted_jobs)
    target_per_person = total_jobs // len(selected_assignees)
    remainder = total_jobs % len(selected_assignees)
    
    logger.info(f"\n📊 分配计算:")
    logger.info(f"   已开始的Jobs（不可动）: {total_started}")
    logger.info(f"   未开始的Jobs（可分配）: {len(unstarted_jobs)}")
    logger.info(f"   总Jobs: {total_jobs}")
    logger.info(f"   目标每人: {target_per_person} ~ {target_per_person + 1}")
    
    # 计算每个人的目标数量
    # 先按当前已开始数量排序（多的在前，他们的目标会先被分配）
    sorted_by_started = sorted(selected_assignees, key=lambda a: user_started_jobs.get(a['id'], 0), reverse=True)
    
    targets = {}
    remaining_target = total_jobs
    remaining_people = len(selected_assignees)
    
    for a in sorted_by_started:
        started = user_started_jobs.get(a['id'], 0)
        # 这个人的目标 = 剩余总数 / 剩余人数（向上取整给前面的人）
        avg = remaining_target // remaining_people
        extra = 1 if remaining_target % remaining_people > 0 else 0
        
        # 如果已开始的已经超过目标，就只保留已开始的
        target = max(started, avg + extra)
        targets[a['id']] = target
        
        remaining_target -= target
        remaining_people -= 1
    
    # 计算每个人需要分配多少
    for a in selected_assignees:
        started = user_started_jobs.get(a['id'], 0)
        target = targets[a['id']]
        need = target - started
        assignee_workload[a['id']]['target'] = target
        assignee_workload[a['id']]['need'] = need
    
    # 显示分配预览（按需要分配数量排序，多的在前）
    sorted_assignees = sorted(selected_assignees, key=lambda a: assignee_workload[a['id']]['need'], reverse=True)
    
    logger.info(f"\n📋 分配预览:")
    for a in sorted_assignees:
        w = assignee_workload[a['id']]
        logger.info(f"   {w['name']}: 已开始 {w['started']} + 将分配 {w['need']} = {w['target']}")
    
    # 8. 确认分配
    print(f"\n确认按上述方案分配？(y/n): ", end='')
    confirm = input().strip().lower()
    if confirm != 'y':
        logger.info("❌ 取消分配")
        return
    
    # 9. 执行分配（按需分配给每个人）
    logger.info("\n🚀 开始分配...")
    success_count = 0
    fail_count = 0
    job_index = 0
    
    for a in sorted_assignees:
        w = assignee_workload[a['id']]
        need = w['need']
        
        for _ in range(need):
            if job_index >= len(unstarted_jobs):
                break
            job = unstarted_jobs[job_index]
            try:
                client.assign_job(job['job_id'], a['id'])
                logger.info(f"   ✓ Job {job['job_id']} → {a['name']}")
                success_count += 1
            except Exception as e:
                logger.error(f"   ✗ Job {job['job_id']} 分配失败: {e}")
                fail_count += 1
            job_index += 1
    
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
