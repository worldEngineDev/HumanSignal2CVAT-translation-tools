#!/usr/bin/env python3
"""
检查标注进度 - 查看每个标注人员的任务完成情况
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
log_file = log_dir / f'check_progress_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

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
        logger.info(f"初始化CVAT客户端: {base_url}")
    
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
            
            logger.info(f"✅ 获取任务列表成功: {len(all_tasks)} 个任务")
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
            jobs = jobs_data.get('results', [])
            return jobs
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 获取jobs失败: task_id={task_id}, {e}")
            return []
    
    def get_user_info(self, user_id):
        """获取用户信息"""
        url = f'{self.base_url}/api/users/{user_id}'
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 获取用户信息失败: user_id={user_id}, {e}")
            return None
    
    def get_organization_members(self, organization_slug):
        """获取组织成员列表"""
        url = f'{self.base_url}/api/memberships'
        params = {'org': organization_slug, 'page_size': 100}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            members = data.get('results', [])
            return members
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 获取组织成员失败: {e}")
            return []
    
    def get_job_annotations_count(self, job_id):
        """获取job的标注数量和已标注帧数"""
        url = f'{self.base_url}/api/jobs/{job_id}/annotations'
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            shapes = data.get('shapes', [])
            tracks = data.get('tracks', [])
            
            # 统计有标注的帧（去重）
            annotated_frames = set()
            for shape in shapes:
                annotated_frames.add(shape.get('frame'))
            for track in tracks:
                # track的shapes里也有frame
                for shape in track.get('shapes', []):
                    annotated_frames.add(shape.get('frame'))
            
            return len(shapes), len(tracks), len(annotated_frames)
        except requests.exceptions.Timeout:
            logger.debug(f"检查job {job_id}超时")
            return 0, 0, 0
        except requests.exceptions.RequestException as e:
            logger.debug(f"检查job {job_id}失败: {e}")
            return 0, 0, 0


def format_duration(seconds):
    """格式化时长"""
    if seconds is None:
        return "N/A"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    
    if hours > 0:
        return f"{hours}小时{minutes}分钟"
    else:
        return f"{minutes}分钟"


def check_progress(config_file='config.json', task_ids=None, show_details=False):
    """检查标注进度主流程"""
    logger.info("="*60)
    logger.info("检查标注进度")
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
    
    # 2. 初始化客户端
    client = CVATClient(cvat_url, api_key)
    
    # 3. 获取任务列表
    logger.info(f"\n📋 获取任务列表...")
    
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
        # 获取所有任务
        tasks = client.get_all_tasks(organization_slug)
    
    # 排除旧平台任务
    EXCLUDED_TASKS = {1967925}
    tasks = [t for t in tasks if t['id'] not in EXCLUDED_TASKS]
    
    if not tasks:
        logger.warning("⚠️  未找到任何任务")
        return
    
    logger.info(f"✅ 找到 {len(tasks)} 个任务")
    
    # 4. 获取组织成员信息（用于显示用户名）
    logger.info(f"\n👥 获取组织成员信息...")
    members = client.get_organization_members(organization_slug) if organization_slug else []
    user_map = {}
    for member in members:
        user = member.get('user')
        if user:
            user_id = user.get('id')
            username = user.get('username')
            user_map[user_id] = username
    
    logger.info(f"✅ 找到 {len(user_map)} 个成员")
    
    # 5. 统计每个任务的进度
    logger.info(f"\n📊 分析任务进度...")
    
    all_stats = []
    user_stats = defaultdict(lambda: {
        'total_jobs': 0,
        'completed': 0,
        'in_progress': 0,
        'not_started': 0,
        'total_frames': 0,
        'annotated_frames': 0,
        'completed_jobs': 0,
        'total_shapes': 0,
        'speeds': []  # 存储每个job的速度，用于计算平均
    })
    
    for task in tasks:
        task_id = task['id']
        task_name = task['name']
        task_status = task.get('status')
        created_date = task.get('created_date', '')[:10]
        
        logger.info(f"\n处理任务: {task_name} (ID: {task_id})")
        
        # 获取任务的jobs
        jobs = client.get_task_jobs(task_id)
        
        if not jobs:
            logger.info(f"   → 没有jobs")
            continue
        
        logger.info(f"   → Jobs数: {len(jobs)}")
        logger.info(f"   → 检查标注状态（并发）...")
        
        # 并发检查每个job的标注数量
        def check_job(job):
            job_id = job.get('id')
            start_frame = job.get('start_frame', 0)
            stop_frame = job.get('stop_frame', 0)
            frame_count = stop_frame - start_frame + 1
            shapes, tracks, annotated_frames = client.get_job_annotations_count(job_id)
            return job_id, shapes, tracks, annotated_frames, frame_count
        
        job_annotations = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(check_job, job): job for job in jobs}
            completed = 0
            for future in as_completed(futures):
                job_id, shapes, tracks, annotated_frames, frame_count = future.result()
                job_annotations[job_id] = {
                    'shapes': shapes, 
                    'tracks': tracks, 
                    'annotated_frames': annotated_frames,
                    'frame_count': frame_count
                }
                completed += 1
                if completed % 10 == 0 or completed == len(jobs):
                    logger.info(f"      进度: {completed}/{len(jobs)} jobs")
        
        # 统计任务级别的信息
        task_stats = {
            'task_id': task_id,
            'task_name': task_name,
            'task_status': task_status,
            'created_date': created_date,
            'total_jobs': len(jobs),
            'job_stats': defaultdict(int),
            'assignee_stats': defaultdict(lambda: defaultdict(int)),
            'total_frames': 0,
            'completed_frames': 0
        }
        
        for job in jobs:
            job_id = job['id']
            state = job.get('state', 'new')
            assignee = job.get('assignee')
            start_frame = job.get('start_frame', 0)
            stop_frame = job.get('stop_frame', 0)
            frame_count = stop_frame - start_frame + 1
            
            # 获取标注数量
            ann_info = job_annotations.get(job_id, {'shapes': 0, 'tracks': 0, 'annotated_frames': 0, 'frame_count': frame_count})
            shapes_count = ann_info['shapes']
            tracks_count = ann_info['tracks']
            annotated_frames = ann_info['annotated_frames']
            
            # 统计job状态（基于已标注帧数判断）
            if annotated_frames == 0:
                actual_state = 'not_started'
            elif annotated_frames >= frame_count:
                actual_state = 'completed'
            else:
                actual_state = 'in_progress'
            
            task_stats['job_stats'][actual_state] += 1
            task_stats['total_frames'] += frame_count
            
            # 计入已标注帧数（精确统计）
            task_stats['completed_frames'] += annotated_frames
            
            # 统计每个标注人员的情况
            if assignee:
                assignee_id = assignee.get('id')
                assignee_username = assignee.get('username')
                assignee_name = user_map.get(assignee_id, assignee_username or f"User_{assignee_id}")
                
                task_stats['assignee_stats'][assignee_name]['total'] += 1
                task_stats['assignee_stats'][assignee_name][actual_state] += 1
                task_stats['assignee_stats'][assignee_name]['frames'] += frame_count
                task_stats['assignee_stats'][assignee_name]['annotated_frames'] = \
                    task_stats['assignee_stats'][assignee_name].get('annotated_frames', 0) + annotated_frames
                task_stats['assignee_stats'][assignee_name]['shapes'] = \
                    task_stats['assignee_stats'][assignee_name].get('shapes', 0) + shapes_count
                
                # 计算速度（帧/小时）
                assigned_date = job.get('assignee_updated_date') or job.get('created_date')
                updated_date = job.get('updated_date')
                if assigned_date and updated_date and annotated_frames > 0:
                    try:
                        from datetime import datetime as dt
                        assigned_dt = dt.fromisoformat(assigned_date.replace('Z', '+00:00'))
                        updated_dt = dt.fromisoformat(updated_date.replace('Z', '+00:00'))
                        hours = (updated_dt - assigned_dt).total_seconds() / 3600
                        if hours > 0:
                            speed = annotated_frames / hours
                            user_stats[assignee_name]['speeds'].append(speed)
                    except:
                        pass
                
                # 全局统计
                user_stats[assignee_name]['total_jobs'] += 1
                user_stats[assignee_name][actual_state] += 1
                user_stats[assignee_name]['total_frames'] += frame_count
                user_stats[assignee_name]['annotated_frames'] = \
                    user_stats[assignee_name].get('annotated_frames', 0) + annotated_frames
                user_stats[assignee_name]['total_shapes'] = \
                    user_stats[assignee_name].get('total_shapes', 0) + shapes_count
                
                # 完成的job数
                if actual_state == 'completed':
                    user_stats[assignee_name]['completed_jobs'] = \
                        user_stats[assignee_name].get('completed_jobs', 0) + 1
        
        all_stats.append(task_stats)
    
    # 6. 显示结果
    logger.info("\n" + "="*80)
    logger.info("📊 任务进度汇总")
    logger.info("="*80)
    
    for task_stat in all_stats:
        logger.info(f"\n📌 任务: {task_stat['task_name']} (ID: {task_stat['task_id']})")
        logger.info(f"   创建日期: {task_stat['created_date']}")
        logger.info(f"   任务状态: {task_stat['task_status']}")
        logger.info(f"   总Jobs数: {task_stat['total_jobs']}")
        logger.info(f"   总帧数: {task_stat['total_frames']}")
        logger.info(f"   已标注帧: {task_stat['completed_frames']} ({task_stat['completed_frames']*100//task_stat['total_frames'] if task_stat['total_frames'] > 0 else 0}%)")
        
        # Job状态分布
        logger.info(f"\n   Job状态分布:")
        for state, count in sorted(task_stat['job_stats'].items()):
            percentage = count * 100 // task_stat['total_jobs'] if task_stat['total_jobs'] > 0 else 0
            logger.info(f"     - {state}: {count} ({percentage}%)")
        
        # 标注人员统计
        if task_stat['assignee_stats']:
            logger.info(f"\n   标注人员进度:")
            for assignee, stats in sorted(task_stat['assignee_stats'].items()):
                total = stats['total']
                completed = stats.get('completed', 0)
                in_progress = stats.get('in_progress', 0)
                not_started = stats.get('not_started', 0)
                frames = stats.get('frames', 0)
                annotated_frames = stats.get('annotated_frames', 0)
                shapes = stats.get('shapes', 0)
                
                frame_rate = annotated_frames * 100 // frames if frames > 0 else 0
                
                logger.info(f"     👤 {assignee}:")
                logger.info(f"        Jobs: {completed}完成/{in_progress}进行中/{not_started}未开始 (共{total})")
                logger.info(f"        帧数: {annotated_frames}/{frames} ({frame_rate}%) | 标注数: {shapes}")
    
    # 7. 全局标注人员统计
    logger.info("\n" + "="*80)
    logger.info("👥 标注人员总体进度")
    logger.info("="*80)
    
    if user_stats:
        # 按完成率排序
        sorted_users = sorted(
            user_stats.items(),
            key=lambda x: x[1].get('annotated_frames', 0) / x[1]['total_frames'] if x[1]['total_frames'] > 0 else 0,
            reverse=True
        )
        
        for assignee, stats in sorted_users:
            total = stats['total_jobs']
            completed_jobs = stats.get('completed_jobs', 0)
            in_progress = stats.get('in_progress', 0)
            not_started = stats.get('not_started', 0)
            total_frames = stats['total_frames']
            annotated_frames = stats.get('annotated_frames', 0)
            total_shapes = stats.get('total_shapes', 0)
            speeds = stats.get('speeds', [])
            avg_speed = sum(speeds) / len(speeds) if speeds else None
            
            frame_completion_rate = annotated_frames * 100 // total_frames if total_frames > 0 else 0
            
            logger.info(f"\n👤 {assignee}:")
            logger.info(f"   Jobs: {completed_jobs}完成/{in_progress}进行中/{not_started}未开始 (共{total})")
            logger.info(f"   帧数: {annotated_frames}/{total_frames} ({frame_completion_rate}%)")
            logger.info(f"   标注数: {total_shapes}")
            logger.info(f"   平均速度: {avg_speed:.1f} 帧/小时" if avg_speed else "   平均速度: N/A")
            
            # 进度条（基于帧完成率）
            bar_length = 40
            filled = int(bar_length * frame_completion_rate / 100)
            bar = '█' * filled + '░' * (bar_length - filled)
            logger.info(f"   进度: [{bar}] {frame_completion_rate}%")
    else:
        sorted_users = []
        logger.info("   未找到已分配的任务")
    
    # 8. 保存详细报告
    report_file = log_dir / f'progress_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    
    report = {
        'generated_at': datetime.now().isoformat(),
        'summary': {
            'total_tasks': len(all_stats),
            'total_users': len(user_stats)
        },
        'tasks': all_stats,
        'users': dict(user_stats)
    }
    
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    
    logger.info(f"\n✅ 详细报告已保存: {report_file}")
    logger.info(f"📝 日志文件: {log_file}")
    
    # 9. 生成简单的每日报告
    daily_report_file = log_dir / f'daily_report_{datetime.now().strftime("%Y%m%d")}.txt'
    
    with open(daily_report_file, 'w', encoding='utf-8') as f:
        f.write(f"标注进度日报 - {datetime.now().strftime('%Y年%m月%d日')}\n")
        f.write("="*60 + "\n\n")
        
        f.write("📊 总体情况\n")
        f.write(f"  任务数: {len(all_stats)}\n")
        f.write(f"  标注人员: {len(user_stats)}\n\n")
        
        f.write("👥 标注人员进度\n")
        f.write("-"*60 + "\n")
        
        for assignee, stats in sorted_users:
            total = stats['total_jobs']
            completed_jobs = stats.get('completed_jobs', 0)
            in_progress = stats.get('in_progress', 0)
            not_started = stats.get('not_started', 0)
            total_frames = stats['total_frames']
            annotated_frames = stats.get('annotated_frames', 0)
            total_shapes = stats.get('total_shapes', 0)
            
            frame_rate = annotated_frames * 100 // total_frames if total_frames > 0 else 0
            
            f.write(f"\n{assignee}:\n")
            f.write(f"  Jobs: {completed_jobs}完成/{in_progress}进行中/{not_started}未开始 (共{total})\n")
            f.write(f"  帧数: {annotated_frames}/{total_frames} ({frame_rate}%)\n")
            f.write(f"  标注数: {total_shapes}\n")
        
        f.write("\n" + "="*60 + "\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    logger.info(f"📄 每日报告已保存: {daily_report_file}")
    
    logger.info("\n" + "="*80)


def main():
    """命令行入口"""
    import sys
    
    task_ids = None
    if len(sys.argv) > 1:
        # 支持指定任务ID
        try:
            task_ids = [int(tid) for tid in sys.argv[1:]]
            logger.info(f"检查指定任务: {task_ids}")
        except ValueError:
            logger.error("❌ 任务ID必须是数字")
            logger.info("用法: python check_progress.py [task_id1] [task_id2] ...")
            return
    
    check_progress(task_ids=task_ids)


if __name__ == "__main__":
    main()
