#!/usr/bin/env python3
"""
检查标注人员每日工作绩效
- 基于 job 级别的快照差值统计
- 增量归属到当前 assignee（解决重新分配问题）
- 支持查询指定日期
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

# 排除的任务
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
        
        try:
            while True:
                params['page'] = page
                response = requests.get(url, headers=self.headers, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                all_tasks.extend(data.get('results', []))
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
            return response.json().get('results', [])
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 获取jobs失败: task_id={task_id}, {e}")
            return []
    
    def get_job_annotated_frames(self, job_id):
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
            
            return len(annotated_frames), len(data.get('shapes', []))
        except:
            return 0, 0
    
    def get_organization_members(self, organization_slug):
        """获取组织成员列表"""
        url = f'{self.base_url}/api/memberships'
        params = {'org': organization_slug, 'page_size': 100}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json().get('results', [])
        except:
            return []


def load_snapshot(date_str):
    """加载指定日期的快照"""
    snapshot_file = snapshot_dir / f'daily_{date_str}.json'
    if snapshot_file.exists():
        with open(snapshot_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_snapshot(date_str, data):
    """保存快照（同一天覆盖）"""
    snapshot_file = snapshot_dir / f'daily_{date_str}.json'
    with open(snapshot_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"✅ 快照已保存: {snapshot_file}")



def check_daily_performance(config_file='config.json', target_date=None):
    """
    检查每日绩效主流程
    target_date: 查询的日期，格式 YYYYMMDD，默认今天
    """
    logger.info("="*60)
    logger.info("检查标注人员每日绩效")
    logger.info("="*60)
    
    # 确定日期
    today = datetime.now().strftime('%Y%m%d')
    if target_date:
        query_date = target_date
    else:
        query_date = today
    
    query_date_display = f"{query_date[:4]}-{query_date[4:6]}-{query_date[6:8]}"
    logger.info(f"📅 查询日期: {query_date_display}")
    
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
    logger.info(f"初始化CVAT客户端: {cvat_url}")
    
    # 2. 获取任务列表
    logger.info(f"\n📋 获取任务列表...")
    tasks = client.get_all_tasks(organization_slug)
    tasks = [t for t in tasks if t['id'] not in EXCLUDED_TASKS]
    
    if not tasks:
        logger.warning("⚠️  未找到任何任务")
        return
    
    logger.info(f"✅ 找到 {len(tasks)} 个任务")
    
    # 3. 获取组织成员
    members = client.get_organization_members(organization_slug) if organization_slug else []
    user_map = {}
    for member in members:
        user = member.get('user')
        if user:
            user_map[user.get('id')] = user.get('username')
    
    # 4. 收集当前所有 job 的数据
    logger.info(f"\n📊 收集标注数据...")
    
    # job_data: {job_id: {assignee, annotated_frames, shapes, frame_count, ...}}
    job_data = {}
    
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
            annotated_frames, shapes = client.get_job_annotated_frames(job_id)
            return job, annotated_frames, shapes
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(check_job, job) for job in jobs]
            completed = 0
            
            for future in as_completed(futures):
                job, annotated_frames, shapes = future.result()
                job_id = job['id']
                assignee = job.get('assignee')
                
                start_frame = job.get('start_frame', 0)
                stop_frame = job.get('stop_frame', 0)
                frame_count = stop_frame - start_frame + 1
                
                assignee_id = assignee.get('id') if assignee else None
                assignee_name = user_map.get(assignee_id, assignee.get('username')) if assignee else None
                
                job_data[job_id] = {
                    'task_id': task_id,
                    'assignee_id': assignee_id,
                    'assignee_name': assignee_name,
                    'frame_count': frame_count,
                    'annotated_frames': annotated_frames,
                    'shapes': shapes,
                    'updated_date': job.get('updated_date'),
                    'assigned_date': job.get('assignee_updated_date') or job.get('created_date')
                }
                
                completed += 1
                if completed % 10 == 0 or completed == len(jobs):
                    print(f"\r   检查进度: {completed}/{len(jobs)} jobs", end='', flush=True)
            
            print()
    
    # 5. 加载昨天的快照
    yesterday = (datetime.strptime(query_date, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
    yesterday_snapshot = load_snapshot(yesterday)
    yesterday_jobs = yesterday_snapshot.get('jobs', {}) if yesterday_snapshot else {}
    
    # 6. 计算每个用户的数据
    user_stats = defaultdict(lambda: {
        'today_frames': 0,      # 今日增量帧数
        'today_shapes': 0,      # 今日增量标注数
        'total_frames': 0,      # 累计标注帧数
        'total_shapes': 0,      # 累计标注数
        'job_frames': 0,        # 分配的总帧数
        'jobs': 0,
        'speeds': []
    })
    
    for job_id, data in job_data.items():
        assignee_name = data['assignee_name']
        if not assignee_name:
            continue
        
        # 累计数据
        user_stats[assignee_name]['total_frames'] += data['annotated_frames']
        user_stats[assignee_name]['total_shapes'] += data['shapes']
        user_stats[assignee_name]['job_frames'] += data['frame_count']
        user_stats[assignee_name]['jobs'] += 1
        
        # 计算增量（与昨天快照对比）
        job_id_str = str(job_id)
        if job_id_str in yesterday_jobs:
            yesterday_frames = yesterday_jobs[job_id_str].get('annotated_frames', 0)
            yesterday_shapes = yesterday_jobs[job_id_str].get('shapes', 0)
            delta_frames = data['annotated_frames'] - yesterday_frames
            delta_shapes = data['shapes'] - yesterday_shapes
            
            # 增量归属到当前 assignee（即使 job 被重新分配了）
            if delta_frames > 0:
                user_stats[assignee_name]['today_frames'] += delta_frames
            if delta_shapes > 0:
                user_stats[assignee_name]['today_shapes'] += delta_shapes
        else:
            # 新 job，全部算今日增量
            user_stats[assignee_name]['today_frames'] += data['annotated_frames']
            user_stats[assignee_name]['today_shapes'] += data['shapes']
        
        # 计算速度
        if data['annotated_frames'] > 0 and data['assigned_date'] and data['updated_date']:
            try:
                assigned_dt = datetime.fromisoformat(data['assigned_date'].replace('Z', '+00:00'))
                updated_dt = datetime.fromisoformat(data['updated_date'].replace('Z', '+00:00'))
                hours = (updated_dt - assigned_dt).total_seconds() / 3600
                if hours > 0.1:
                    speed = data['annotated_frames'] / hours
                    user_stats[assignee_name]['speeds'].append(speed)
            except:
                pass
    
    # 7. 保存今日快照（只在查询今天时保存）
    if query_date == today:
        snapshot_data = {
            'date': today,
            'generated_at': datetime.now().isoformat(),
            'jobs': {str(k): {'annotated_frames': v['annotated_frames'], 'shapes': v['shapes']} 
                     for k, v in job_data.items()}
        }
        save_snapshot(today, snapshot_data)
    
    # 8. 生成报告
    performance_records = []
    
    for user, stats in user_stats.items():
        avg_speed = sum(stats['speeds']) / len(stats['speeds']) if stats['speeds'] else None
        
        performance_records.append({
            'date': query_date,
            'user': user,
            'today_frames': stats['today_frames'],
            'today_shapes': stats['today_shapes'],
            'total_frames': stats['total_frames'],
            'total_shapes': stats['total_shapes'],
            'job_frames': stats['job_frames'],
            'jobs': stats['jobs'],
            'avg_speed': f"{avg_speed:.1f}" if avg_speed else 'N/A'
        })
    
    # 按今日帧数排序
    performance_records.sort(key=lambda x: x['today_frames'], reverse=True)
    
    # 9. 输出CSV
    csv_file = report_dir / f'daily_performance_{query_date}.csv'
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['日期', '用户', '当日帧数', '当日标注数', 
                      '累计帧数', '累计标注数', '分配帧数', 'Jobs数', '平均速度']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in performance_records:
            writer.writerow({
                '日期': record['date'],
                '用户': record['user'],
                '当日帧数': record['today_frames'],
                '当日标注数': record['today_shapes'],
                '累计帧数': record['total_frames'],
                '累计标注数': record['total_shapes'],
                '分配帧数': record['job_frames'],
                'Jobs数': record['jobs'],
                '平均速度': record['avg_speed']
            })
    
    logger.info(f"\n✅ CSV报告已保存: {csv_file}")
    
    # 10. 追加到汇总CSV
    summary_file = report_dir / 'performance_summary.csv'
    file_exists = summary_file.exists()
    
    with open(summary_file, 'a', newline='', encoding='utf-8') as f:
        fieldnames = ['日期', '用户', '当日帧数', '当日标注数',
                      '累计帧数', '累计标注数', '分配帧数', 'Jobs数', '平均速度']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for record in performance_records:
            writer.writerow({
                '日期': record['date'],
                '用户': record['user'],
                '当日帧数': record['today_frames'],
                '当日标注数': record['today_shapes'],
                '累计帧数': record['total_frames'],
                '累计标注数': record['total_shapes'],
                '分配帧数': record['job_frames'],
                'Jobs数': record['jobs'],
                '平均速度': record['avg_speed']
            })
    
    logger.info(f"✅ 汇总CSV已更新: {summary_file}")
    
    # 11. 显示结果
    logger.info("\n" + "="*80)
    logger.info(f"📊 {query_date_display} 绩效报告")
    logger.info("="*80)
    
    total_today = sum(r['today_frames'] for r in performance_records)
    has_yesterday = yesterday_snapshot is not None
    
    if not has_yesterday:
        logger.info(f"\n⚠️  无 {yesterday} 快照，今日增量为全部累计值")
    
    logger.info(f"\n📈 当日总产出: {total_today} 帧")
    
    for record in performance_records:
        logger.info(f"\n👤 {record['user']}:")
        logger.info(f"   今日标注: {record['today_frames']} 帧 ({record['today_shapes']} 个标注)")
        logger.info(f"   累计标注: {record['total_frames']}/{record['job_frames']} 帧")
        logger.info(f"   Jobs数: {record['jobs']}")
        logger.info(f"   平均速度: {record['avg_speed']} 帧/小时")
    
    logger.info("\n" + "="*80)
    logger.info(f"📝 日志文件: {log_file}")


def main():
    import sys
    
    target_date = None
    create_snapshot = False
    
    # 解析参数
    args = sys.argv[1:]
    for arg in args:
        if arg == '--snapshot':
            create_snapshot = True
        elif len(arg) == 8 and arg.isdigit():
            target_date = arg
        else:
            print("用法: python check_daily_performance.py [YYYYMMDD] [--snapshot]")
            print("示例:")
            print("  python check_daily_performance.py              # 查询今天")
            print("  python check_daily_performance.py 20260129     # 查询指定日期")
            print("  python check_daily_performance.py 20260128 --snapshot  # 补录指定日期快照")
            return
    
    if create_snapshot:
        if not target_date:
            print("❌ 补录快照需要指定日期")
            print("示例: python check_daily_performance.py 20260128 --snapshot")
            return
        create_snapshot_for_date(target_date)
    else:
        check_daily_performance(target_date=target_date)


def create_snapshot_for_date(target_date):
    """补录指定日期的快照（基于 job 的 updated_date 智能判断）"""
    logger.info("="*60)
    logger.info(f"补录快照: {target_date}")
    logger.info("="*60)
    
    # 目标日期的结束时间点（当天23:59:59）
    target_date_end = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}T23:59:59"
    logger.info(f"📅 只包含 {target_date_end} 之前更新的数据")
    
    # 加载配置
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error("❌ 配置文件不存在")
        return
    
    cvat_url = config['cvat']['url']
    api_key = config['cvat']['api_key']
    organization_slug = config.get('organization', {}).get('slug')
    
    client = CVATClient(cvat_url, api_key)
    
    # 获取任务
    logger.info("\n📋 获取任务列表...")
    tasks = client.get_all_tasks(organization_slug)
    tasks = [t for t in tasks if t['id'] not in EXCLUDED_TASKS]
    logger.info(f"✅ 找到 {len(tasks)} 个任务")
    
    # 收集 job 数据
    logger.info("\n📊 收集标注数据...")
    job_data = {}
    included_count = 0
    excluded_count = 0
    
    for task in tasks:
        task_id = task['id']
        jobs = client.get_task_jobs(task_id)
        
        for job in jobs:
            job_id = job['id']
            updated_date = job.get('updated_date', '')
            
            # 判断 job 的 updated_date 是否在目标日期之前
            if updated_date and updated_date <= target_date_end:
                # 这个 job 在目标日期之前有更新，获取当前数据
                annotated_frames, shapes = client.get_job_annotated_frames(job_id)
                job_data[str(job_id)] = {
                    'annotated_frames': annotated_frames,
                    'shapes': shapes
                }
                included_count += 1
            else:
                # 这个 job 在目标日期之后才有更新，存为0
                job_data[str(job_id)] = {
                    'annotated_frames': 0,
                    'shapes': 0
                }
                excluded_count += 1
        
        print(f"\r   已处理: {included_count + excluded_count} jobs (包含: {included_count}, 排除: {excluded_count})", end='', flush=True)
    
    print()
    
    # 保存快照
    snapshot_data = {
        'date': target_date,
        'generated_at': datetime.now().isoformat(),
        'note': f'补录快照，基于 updated_date <= {target_date_end}',
        'jobs': job_data
    }
    save_snapshot(target_date, snapshot_data)
    
    logger.info(f"\n✅ 快照补录完成: {target_date}")
    logger.info(f"   包含数据的 jobs: {included_count}")
    logger.info(f"   排除的 jobs（之后更新）: {excluded_count}")


if __name__ == "__main__":
    main()
