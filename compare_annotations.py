#!/usr/bin/env python3
"""
对比预标注和人工标注状态
找出哪些job有预标注但还没人工标注
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import logging
import csv
from pathlib import Path
from datetime import datetime

# 配置带重试的 session
def get_retry_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# 配置日志
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f'compare_annotations_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

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

# 报告目录
report_dir = Path('reports')
report_dir.mkdir(exist_ok=True)


class CVATClient:
    def __init__(self, base_url, api_key, org=None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.org = org
        self.headers = {'Authorization': f'Token {api_key}'}
        self.session = get_retry_session()
    
    def get_tasks(self):
        """获取所有任务"""
        url = f'{self.base_url}/api/tasks'
        params = {'page_size': 500}
        if self.org:
            params['org'] = self.org
        
        tasks = []
        page = 1
        while True:
            params['page'] = page
            response = self.session.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            results = data.get('results', [])
            tasks.extend(results)
            if not data.get('next'):
                break
            page += 1
        return tasks
    
    def get_task_jobs(self, task_id):
        """获取任务的所有jobs"""
        url = f'{self.base_url}/api/jobs'
        params = {'task_id': task_id, 'page_size': 1000}
        response = self.session.get(url, headers=self.headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('results', [])
    
    def get_job_frames(self, job_id):
        """获取job的帧信息"""
        url = f'{self.base_url}/api/jobs/{job_id}/data/meta'
        response = self.session.get(url, headers=self.headers, timeout=60)
        response.raise_for_status()
        return response.json()
    
    def get_job_annotations(self, job_id):
        """获取job的标注详情"""
        url = f'{self.base_url}/api/jobs/{job_id}/annotations'
        response = self.session.get(url, headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()


def extract_chunk_id(filename):
    """从文件路径提取chunk ID"""
    parts = filename.split('/')
    for i, part in enumerate(parts):
        if part.startswith('session_'):
            if i + 1 < len(parts):
                chunk_num = parts[i + 1]
                return f"{part}_{chunk_num}"
    return None


def load_preannotation_details():
    """加载预标注详情"""
    details_file = report_dir / 'preannotation_details.json'
    if not details_file.exists():
        return None
    with open(details_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def compare_annotations(config_file='config.json'):
    """对比预标注和人工标注"""
    logger.info("="*60)
    logger.info("对比预标注和人工标注状态")
    logger.info("="*60)
    
    # 1. 加载配置
    logger.info("\n📖 加载配置...")
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ 配置文件不存在: {config_file}")
        return
    
    cvat_url = config['cvat']['url']
    api_key = config['cvat']['api_key']
    org = config['cvat'].get('org')
    
    cvat = CVATClient(cvat_url, api_key, org)
    
    # 2. 加载预标注详情
    logger.info("📖 加载预标注数据...")
    preannotation_data = load_preannotation_details()
    if not preannotation_data:
        logger.error("❌ 预标注数据不存在，请先运行选项10生成")
        return
    
    logger.info(f"   预标注chunks: {len(preannotation_data)}")
    
    # 3. 获取所有任务
    logger.info("\n📋 获取CVAT任务...")
    try:
        tasks = cvat.get_tasks()
        tasks = [t for t in tasks if t['id'] not in EXCLUDED_TASKS]
        logger.info(f"   任务数: {len(tasks)}")
    except Exception as e:
        logger.error(f"❌ 获取任务失败: {e}")
        return
    
    # 4. 遍历所有jobs，对比状态
    results = []
    
    for task in tasks:
        task_id = task['id']
        task_name = task['name']
        logger.info(f"\n处理任务: {task_name} (ID: {task_id})")
        
        try:
            jobs = cvat.get_task_jobs(task_id)
        except Exception as e:
            logger.error(f"   ❌ 获取jobs失败: {e}")
            continue
        
        for job in jobs:
            job_id = job['id']
            assignee = job.get('assignee', {})
            assignee_name = assignee.get('username', '未分配') if assignee else '未分配'
            start_frame = job.get('start_frame', 0)
            stop_frame = job.get('stop_frame', 0)
            frame_count = stop_frame - start_frame + 1
            
            # 获取人工标注数
            human_annotated = 0
            try:
                ann_data = cvat.get_job_annotations(job_id)
                human_frames = set()
                for shape in ann_data.get('shapes', []):
                    human_frames.add(shape.get('frame'))
                human_annotated = len(human_frames)
            except:
                pass
            
            # 获取job的帧路径，确定chunk_id
            chunk_id = None
            try:
                meta = cvat.get_job_frames(job_id)
                frames = meta.get('frames', [])
                if frames:
                    first_frame = frames[0].get('name', '')
                    chunk_id = extract_chunk_id(first_frame)
            except Exception as e:
                logger.debug(f"   获取帧信息失败: {e}")
            
            # 查找预标注数据
            pre_frames = 0
            pre_annotations = 0
            if chunk_id and chunk_id in preannotation_data:
                pre_info = preannotation_data[chunk_id]
                pre_frames = pre_info.get('annotated_frames', 0)
                pre_annotations = pre_info.get('total_annotations', 0)
            
            results.append({
                'task_id': task_id,
                'task_name': task_name,
                'job_id': job_id,
                'assignee': assignee_name,
                'total_frames': frame_count,
                'human_annotated': human_annotated,
                'pre_frames': pre_frames,
                'pre_annotations': pre_annotations,
                'chunk_id': chunk_id or ''
            })
            
            # 日志输出关键信息
            if pre_frames > 0 and human_annotated == 0:
                logger.info(f"   Job {job_id}: 有{pre_frames}帧预标注，无人工标注 ⚠️")
    
    # 5. 输出CSV报告
    csv_file = report_dir / f'annotation_comparison_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['任务ID', '任务名称', 'Job ID', '负责人', '总帧数', 
                        '人工标注帧', '预标注帧', '预标注数', 'Chunk ID', '状态'])
        
        for r in results:
            # 判断状态
            if r['human_annotated'] > 0:
                status = '已标注'
            elif r['pre_frames'] > 0:
                status = '待标注(有预标注)'
            else:
                status = '待标注(无预标注)'
            
            writer.writerow([
                r['task_id'], r['task_name'], r['job_id'], r['assignee'],
                r['total_frames'], r['human_annotated'], r['pre_frames'],
                r['pre_annotations'], r['chunk_id'], status
            ])
    
    logger.info(f"\n✅ CSV报告: {csv_file}")
    
    # 6. 统计汇总
    total_jobs = len(results)
    human_done = sum(1 for r in results if r['human_annotated'] > 0)
    with_pre = sum(1 for r in results if r['pre_frames'] > 0 and r['human_annotated'] == 0)
    no_pre = sum(1 for r in results if r['pre_frames'] == 0 and r['human_annotated'] == 0)
    
    logger.info("\n" + "="*60)
    logger.info("📊 汇总统计")
    logger.info("="*60)
    logger.info(f"   总Jobs数: {total_jobs}")
    logger.info(f"   已有人工标注: {human_done}")
    logger.info(f"   有预标注待人工: {with_pre}")
    logger.info(f"   无预标注待人工: {no_pre}")
    logger.info("="*60)
    
    # 7. 输出JSON详情
    json_file = report_dir / 'annotation_comparison.json'
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"📋 JSON详情: {json_file}")
    
    logger.info(f"📝 日志文件: {log_file}")


def main():
    compare_annotations()


if __name__ == "__main__":
    main()
