#!/usr/bin/env python3
"""
检查标注人员每日工作绩效
- 记录每日快照
- 计算今日产出
- 计算平均速度
- 输出CSV报告
"""
import requests
import json
import logging
import csv
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# 配置日志
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

# 绩效报告目录
report_dir = Path('reports')
report_dir.mkdir(exist_ok=True)
snapshot_dir = report_dir / 'snapshots'
snapshot_dir.mkdir(exist_ok=True)

log_file = log_dir / f'check_performance_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

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
        
        try:
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
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 获取任务列表失败: {e}")
            return []
    
    def get_task_jobs(self, task_id):
        """获取任务的所有jobs"""
        url = f'{self.base_url}/api/jobs'
        params = {'task_id': task_id, 'page_size': 1000}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            jobs_data = response.json()
            return jobs_data.get('results', [])
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 获取jobs失败: task_id={task_id}, {e}")
            return []
    
    def get_job_annotations(self, job_id):
        """获取job的标注详情"""
        url = f'{self.base_url}/api/jobs/{job_id}/annotations'
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            shapes = data.get('shapes', [])
            tracks = data.get('tracks', [])
            
            # 统计有标注的帧
            annotated_frames = set()
            for shape in shapes:
                annotated_frames.add(shape.get('frame'))
            for track in tracks:
                for shape in track.get('shapes', []):
                    annotated_frames.add(shape.get('frame'))
            
            return len(shapes), len(tracks), len(annotated_frames)
        except requests.exceptions.RequestException as e:
            logger.debug(f"获取标注失败: job_id={job_id}, {e}")
            return 0, 0, 0
    
    def get_organization_members(self, organization_slug):
        """获取组织成员列表"""
        url = f'{self.base_url}/api/memberships'
        params = {'org': organization_slug, 'page_size': 100}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get('results', [])
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 获取组织成员失败: {e}")
            return []


def load_snapshot(date_str):
    """加载指定日期的快照"""
    snapshot_file = snapshot_dir / f'daily_{date_str}.json'
    if snapshot_file.exists():
        with open(snapshot_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_snapshot(date_str, data):
    """保存快照"""
    snapshot_file = snapshot_dir / f'daily_{date_str}.json'
    with open(snapshot_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"✅ 快照已保存: {snapshot_file}")


def check_daily_performance(config_file='config.json', task_ids=None):
    """检查每日绩效主流程"""
    logger.info("="*60)
    logger.info("检查标注人员每日绩效")
    logger.info("="*60)
    
    today = datetime.now().strftime('%Y%m%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    
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
    
    # 2. 初始化客户端
    client = CVATClient(cvat_url, api_key)
    logger.info(f"初始化CVAT客户端: {cvat_url}")
    
    # 3. 获取任务列表
    logger.info(f"\n📋 获取任务列表...")
    
    if task_ids:
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
    
    # 排除旧平台任务
    EXCLUDED_TASKS = {1967925}
    tasks = [t for t in tasks if t['id'] not in EXCLUDED_TASKS]
    
    if not tasks:
        logger.warning("⚠️  未找到任何任务")
        return
    
    logger.info(f"✅ 找到 {len(tasks)} 个任务")
    
    # 4. 获取组织成员
    members = client.get_organization_members(organization_slug) if organization_slug else []
    user_map = {}
    for member in members:
        user = member.get('user')
        if user:
            user_map[user.get('id')] = user.get('username')
    
    # 5. 收集每个用户的数据
    logger.info(f"\n📊 收集标注数据...")
    
    user_data = defaultdict(lambda: {
        'total_frames': 0,
        'annotated_frames': 0,
        'total_shapes': 0,
        'total_jobs': 0,
        'completed_jobs': 0,
        'in_progress_jobs': 0,
        'jobs_detail': []
    })
    
    for task in tasks:
        task_id = task['id']
        task_name = task['name']
        
        logger.info(f"\n处理任务: {task_name} (ID: {task_id})")
        
        jobs = client.get_task_jobs(task_id)
        if not jobs:
            continue
        
        logger.info(f"   → Jobs数: {len(jobs)}")
        
        # 并发获取标注数据
        def check_job(job):
            job_id = job.get('id')
            shapes, tracks, annotated_frames = client.get_job_annotations(job_id)
            return job_id, shapes, tracks, annotated_frames
        
        job_annotations = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(check_job, job): job for job in jobs}
            completed = 0
            for future in as_completed(futures):
                job_id, shapes, tracks, annotated_frames = future.result()
                job_annotations[job_id] = {
                    'shapes': shapes,
                    'tracks': tracks,
                    'annotated_frames': annotated_frames
                }
                completed += 1
                if completed % 10 == 0 or completed == len(jobs):
                    print(f"\r   检查进度: {completed}/{len(jobs)} jobs", end='', flush=True)
        print()
        
        # 统计每个用户
        for job in jobs:
            job_id = job['id']
            assignee = job.get('assignee')
            if not assignee:
                continue
            
            assignee_id = assignee.get('id')
            assignee_name = user_map.get(assignee_id, assignee.get('username', f'User_{assignee_id}'))
            
            start_frame = job.get('start_frame', 0)
            stop_frame = job.get('stop_frame', 0)
            frame_count = stop_frame - start_frame + 1
            
            ann = job_annotations.get(job_id, {'shapes': 0, 'tracks': 0, 'annotated_frames': 0})
            annotated_frames = ann['annotated_frames']
            shapes = ann['shapes']
            
            # 计算速度（帧/小时）
            assigned_date = job.get('assignee_updated_date') or job.get('created_date')
            updated_date = job.get('updated_date')
            speed = None
            
            if assigned_date and updated_date and annotated_frames > 0:
                try:
                    assigned_dt = datetime.fromisoformat(assigned_date.replace('Z', '+00:00'))
                    updated_dt = datetime.fromisoformat(updated_date.replace('Z', '+00:00'))
                    hours = (updated_dt - assigned_dt).total_seconds() / 3600
                    if hours > 0:
                        speed = annotated_frames / hours
                except:
                    pass
            
            # 判断状态
            if annotated_frames == 0:
                status = 'not_started'
            elif annotated_frames >= frame_count:
                status = 'completed'
                user_data[assignee_name]['completed_jobs'] += 1
            else:
                status = 'in_progress'
                user_data[assignee_name]['in_progress_jobs'] += 1
            
            user_data[assignee_name]['total_frames'] += frame_count
            user_data[assignee_name]['annotated_frames'] += annotated_frames
            user_data[assignee_name]['total_shapes'] += shapes
            user_data[assignee_name]['total_jobs'] += 1
            user_data[assignee_name]['jobs_detail'].append({
                'task_id': task_id,
                'job_id': job_id,
                'frame_count': frame_count,
                'annotated_frames': annotated_frames,
                'shapes': shapes,
                'status': status,
                'speed': speed,
                'assigned_date': assigned_date,
                'updated_date': updated_date
            })
    
    # 6. 加载昨天的快照计算今日增量
    yesterday_snapshot = load_snapshot(yesterday)
    
    # 7. 计算今日数据和增量
    today_data = {
        'date': today,
        'generated_at': datetime.now().isoformat(),
        'users': {}
    }
    
    performance_records = []
    
    for user, data in user_data.items():
        # 计算平均速度
        speeds = [j['speed'] for j in data['jobs_detail'] if j['speed'] is not None]
        avg_speed = sum(speeds) / len(speeds) if speeds else None
        
        # 今日增量
        today_frames = data['annotated_frames']
        today_shapes = data['total_shapes']
        
        if yesterday_snapshot and user in yesterday_snapshot.get('users', {}):
            yesterday_data = yesterday_snapshot['users'][user]
            delta_frames = today_frames - yesterday_data.get('annotated_frames', 0)
            delta_shapes = today_shapes - yesterday_data.get('total_shapes', 0)
        else:
            delta_frames = None  # 无昨日数据，无法计算增量
            delta_shapes = None
        
        today_data['users'][user] = {
            'total_frames': data['total_frames'],
            'annotated_frames': data['annotated_frames'],
            'total_shapes': data['total_shapes'],
            'total_jobs': data['total_jobs'],
            'completed_jobs': data['completed_jobs'],
            'in_progress_jobs': data['in_progress_jobs'],
            'avg_speed': avg_speed
        }
        
        performance_records.append({
            'date': today,
            'user': user,
            'today_frames': delta_frames if delta_frames is not None else 'N/A',
            'total_annotated_frames': data['annotated_frames'],
            'total_frames': data['total_frames'],
            'today_shapes': delta_shapes if delta_shapes is not None else 'N/A',
            'total_shapes': data['total_shapes'],
            'completed_jobs': data['completed_jobs'],
            'in_progress_jobs': data['in_progress_jobs'],
            'total_jobs': data['total_jobs'],
            'avg_speed': f"{avg_speed:.1f}" if avg_speed else 'N/A'
        })
    
    # 8. 保存今日快照
    save_snapshot(today, today_data)
    
    # 9. 输出CSV
    csv_file = report_dir / f'daily_performance_{today}.csv'
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['date', 'user', 'today_frames', 'total_annotated_frames', 'total_frames', 
                      'today_shapes', 'total_shapes', 'completed_jobs', 'in_progress_jobs', 
                      'total_jobs', 'avg_speed']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(performance_records)
    
    logger.info(f"✅ CSV报告已保存: {csv_file}")
    
    # 10. 追加到汇总CSV
    summary_file = report_dir / 'performance_summary.csv'
    file_exists = summary_file.exists()
    
    with open(summary_file, 'a', newline='', encoding='utf-8') as f:
        fieldnames = ['date', 'user', 'today_frames', 'total_annotated_frames', 'total_frames',
                      'today_shapes', 'total_shapes', 'completed_jobs', 'in_progress_jobs',
                      'total_jobs', 'avg_speed']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(performance_records)
    
    logger.info(f"✅ 汇总CSV已更新: {summary_file}")
    
    # 11. 显示结果
    logger.info("\n" + "="*80)
    logger.info("📊 今日绩效报告")
    logger.info("="*80)
    
    for record in sorted(performance_records, key=lambda x: x['total_annotated_frames'], reverse=True):
        logger.info(f"\n👤 {record['user']}:")
        if record['today_frames'] != 'N/A':
            logger.info(f"   今日标注: {record['today_frames']} 帧")
        logger.info(f"   累计标注: {record['total_annotated_frames']}/{record['total_frames']} 帧")
        logger.info(f"   标注数量: {record['total_shapes']}")
        logger.info(f"   Jobs: {record['completed_jobs']}完成/{record['in_progress_jobs']}进行中/{record['total_jobs']}总计")
        logger.info(f"   平均速度: {record['avg_speed']} 帧/小时")
    
    logger.info("\n" + "="*80)
    logger.info(f"📝 日志文件: {log_file}")


def main():
    """命令行入口"""
    import sys
    
    task_ids = None
    if len(sys.argv) > 1:
        try:
            task_ids = [int(tid) for tid in sys.argv[1:]]
            logger.info(f"检查指定任务: {task_ids}")
        except ValueError:
            logger.error("❌ 任务ID必须是数字")
            return
    
    check_daily_performance(task_ids=task_ids)


if __name__ == "__main__":
    main()
