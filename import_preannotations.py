#!/usr/bin/env python3
"""
导入预标注到CVAT
从云存储读取 *_bbox.json (COCO格式)，转换并导入到对应的 job
只对没有标注的 job 导入，不覆盖人工标注
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import logging
import boto3
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

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
log_file = log_dir / f'import_preannotations_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

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

# 预标注记录目录
report_dir = Path('reports')
report_dir.mkdir(exist_ok=True)
preannotation_record_file = report_dir / 'preannotation_records.json'

def load_preannotation_records():
    """加载预标注记录"""
    if preannotation_record_file.exists():
        with open(preannotation_record_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_preannotation_records(records):
    """保存预标注记录"""
    with open(preannotation_record_file, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

# 标签映射：COCO -> CVAT
LABEL_MAP = {
    'left_hand': 'Left hand',
    'right_hand': 'Right hand',
    'partial_left_hand': 'Partial left hand',
    'partial_right_hand': 'Partial right hand',
}


class CVATClient:
    """CVAT客户端"""
    
    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {'Authorization': f'Token {api_key}'}
        self.session = get_retry_session()
    
    def get_task(self, task_id):
        """获取任务信息"""
        url = f'{self.base_url}/api/tasks/{task_id}'
        response = self.session.get(url, headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def get_task_jobs(self, task_id):
        """获取任务的所有jobs"""
        url = f'{self.base_url}/api/jobs'
        params = {'task_id': task_id, 'page_size': 1000}
        response = self.session.get(url, headers=self.headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('results', [])
    
    def get_job_frames(self, job_id):
        """获取job的帧信息（图片路径）"""
        url = f'{self.base_url}/api/jobs/{job_id}/data/meta'
        response = self.session.get(url, headers=self.headers, timeout=60)
        response.raise_for_status()
        return response.json()
    
    def get_job_annotations_count(self, job_id):
        """获取job的已标注帧数"""
        url = f'{self.base_url}/api/jobs/{job_id}/annotations'
        try:
            response = self.session.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            annotated_frames = set()
            for shape in data.get('shapes', []):
                annotated_frames.add(shape.get('frame'))
            return len(annotated_frames)
        except:
            return -1
    
    def get_task_labels(self, task_id):
        """获取任务的标签列表"""
        url = f'{self.base_url}/api/labels'
        params = {'task_id': task_id}
        response = self.session.get(url, headers=self.headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        labels = {}
        for label in data.get('results', []):
            labels[label['name']] = label['id']
        return labels
    
    def upload_job_annotations(self, job_id, annotations):
        """上传标注到job"""
        url = f'{self.base_url}/api/jobs/{job_id}/annotations?action=create'
        headers = {**self.headers, 'Content-Type': 'application/json'}
        
        response = self.session.patch(url, headers=headers, json=annotations, timeout=120)
        response.raise_for_status()
        return True


class S3Client:
    """S3/R2客户端"""
    
    def __init__(self, config):
        endpoint_url = f"https://{config['account_id']}.r2.cloudflarestorage.com"
        self.s3 = boto3.client('s3',
            endpoint_url=endpoint_url,
            aws_access_key_id=config['aws_access_key_id'],
            aws_secret_access_key=config['aws_secret_access_key'],
            region_name=config['region']
        )
        self.bucket = config['bucket_name']
    
    def get_json(self, key):
        """下载并解析JSON文件"""
        try:
            resp = self.s3.get_object(Bucket=self.bucket, Key=key)
            return json.loads(resp['Body'].read().decode('utf-8'))
        except Exception as e:
            logger.debug(f"获取JSON失败: {key}, {e}")
            return None
    
    def find_bbox_json(self, prefix):
        """在指定前缀下查找 *_bbox.json 文件"""
        try:
            resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix, MaxKeys=100)
            for obj in resp.get('Contents', []):
                if obj['Key'].endswith('_bbox.json'):
                    return obj['Key']
        except:
            pass
        return None



def extract_chunk_id(filename):
    """
    从文件路径提取 chunk ID
    格式: 23dc/session_20260121_200123_268461/0001/down/labels/.../frame_00000.jpg
    返回: session_20260121_200123_268461_0001
    """
    parts = filename.split('/')
    for i, part in enumerate(parts):
        if part.startswith('session_'):
            if i + 1 < len(parts):
                chunk_num = parts[i + 1]
                return f"{part}_{chunk_num}"
    return None


def get_session_prefix(filename):
    """
    从文件路径获取 session 的 labels 目录前缀
    格式: 23dc/session_20260121_200123_268461/0001/down/labels/.../frame_00000.jpg
    返回: 23dc/session_20260121_200123_268461/0001/down/labels/
    """
    parts = filename.split('/')
    for i, part in enumerate(parts):
        if part == 'labels' and i > 0:
            return '/'.join(parts[:i+1]) + '/'
    return None


def convert_coco_to_cvat(coco_data, frame_mapping, label_ids, start_frame):
    """
    将COCO格式转换为CVAT格式
    
    coco_data: COCO JSON数据
    frame_mapping: {coco_image_id: cvat_frame_number}
    label_ids: {label_name: label_id}
    start_frame: job的起始帧号
    """
    shapes = []
    
    # 构建 category_id -> label_name 映射
    category_map = {}
    for cat in coco_data.get('categories', []):
        category_map[cat['id']] = cat['name']
    
    # 构建 image_id -> file_name 映射
    image_map = {}
    for img in coco_data.get('images', []):
        image_map[img['id']] = img['file_name']
    
    for ann in coco_data.get('annotations', []):
        image_id = ann['image_id']
        category_id = ann['category_id']
        bbox = ann['bbox']  # [x, y, width, height]
        
        # 获取标签名称
        coco_label = category_map.get(category_id)
        if not coco_label:
            continue
        
        # 映射到CVAT标签
        cvat_label = LABEL_MAP.get(coco_label, coco_label)
        label_id = label_ids.get(cvat_label)
        if not label_id:
            logger.warning(f"标签未找到: {cvat_label}")
            continue
        
        # 获取帧号
        if image_id not in frame_mapping:
            continue
        
        frame = frame_mapping[image_id]
        
        # CVAT rectangle 格式: [x1, y1, x2, y2]
        x, y, w, h = bbox
        points = [x, y, x + w, y + h]
        
        shapes.append({
            'type': 'rectangle',
            'frame': frame,
            'label_id': label_id,
            'points': points,
            'occluded': False,
            'z_order': 0,
            'attributes': []
        })
    
    return {'shapes': shapes, 'tracks': [], 'tags': []}


def import_preannotations(config_file='config.json', task_id=None, job_id=None):
    """导入预标注主流程
    
    Args:
        task_id: 任务ID
        job_id: 可选，指定单个job导入
    """
    logger.info("="*60)
    logger.info("导入预标注到CVAT")
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
    s3_config = config['s3']
    
    cvat = CVATClient(cvat_url, api_key)
    s3 = S3Client(s3_config)
    
    # 加载已有的预标注记录
    preannotation_records = load_preannotation_records()
    
    # 2. 获取任务信息
    if not task_id:
        logger.error("❌ 请指定任务ID")
        return
    
    logger.info(f"\n📋 获取任务信息: {task_id}")
    try:
        task = cvat.get_task(task_id)
        logger.info(f"   任务名称: {task['name']}")
    except Exception as e:
        logger.error(f"❌ 获取任务失败: {e}")
        return
    
    # 3. 获取任务标签
    label_ids = cvat.get_task_labels(task_id)
    logger.info(f"   标签: {list(label_ids.keys())}")
    
    # 4. 获取所有jobs
    jobs = cvat.get_task_jobs(task_id)
    logger.info(f"   Jobs数: {len(jobs)}")
    
    # 如果指定了job_id，只处理该job
    if job_id:
        jobs = [j for j in jobs if j['id'] == job_id]
        if not jobs:
            logger.error(f"❌ 未找到Job: {job_id}")
            return
        logger.info(f"   指定处理Job: {job_id}")
    
    # 5. 处理每个job
    success_count = 0
    skip_count = 0
    fail_count = 0
    
    for job in jobs:
        job_id = job['id']
        start_frame = job.get('start_frame', 0)
        stop_frame = job.get('stop_frame', 0)
        
        logger.info(f"\n处理 Job {job_id} (帧 {start_frame}-{stop_frame})...")
        
        # 检查是否已有标注
        annotated_count = cvat.get_job_annotations_count(job_id)
        if annotated_count > 0:
            logger.info(f"   ⏭️  跳过：已有 {annotated_count} 帧标注")
            skip_count += 1
            continue
        
        # 获取job的帧信息
        try:
            meta = cvat.get_job_frames(job_id)
            frames = meta.get('frames', [])
            if not frames:
                logger.warning(f"   ⚠️  无帧信息")
                fail_count += 1
                continue
        except Exception as e:
            logger.error(f"   ❌ 获取帧信息失败: {e}")
            fail_count += 1
            continue
        
        # 从第一帧路径获取session前缀
        first_frame_path = frames[0].get('name', '')
        session_prefix = get_session_prefix(first_frame_path)
        
        if not session_prefix:
            logger.warning(f"   ⚠️  无法解析session路径: {first_frame_path}")
            fail_count += 1
            continue
        
        logger.info(f"   Session: {session_prefix}")
        
        # 查找bbox.json
        bbox_json_key = s3.find_bbox_json(session_prefix)
        if not bbox_json_key:
            logger.warning(f"   ⚠️  未找到预标注文件")
            fail_count += 1
            continue
        
        logger.info(f"   预标注文件: {bbox_json_key}")
        
        # 下载COCO数据
        coco_data = s3.get_json(bbox_json_key)
        if not coco_data:
            logger.error(f"   ❌ 下载预标注失败")
            fail_count += 1
            continue
        
        # 构建帧映射: COCO image_id -> CVAT frame
        # COCO的image按file_name排序，CVAT的frame按顺序
        frame_mapping = {}
        coco_images = {img['file_name']: img['id'] for img in coco_data.get('images', [])}
        
        for idx, frame_info in enumerate(frames):
            frame_name = frame_info.get('name', '')
            cvat_frame = start_frame + idx
            
            # 在COCO中查找对应的image
            if frame_name in coco_images:
                coco_image_id = coco_images[frame_name]
                frame_mapping[coco_image_id] = cvat_frame
        
        logger.info(f"   帧映射: {len(frame_mapping)}/{len(frames)}")
        
        if not frame_mapping:
            logger.warning(f"   ⚠️  无法建立帧映射")
            fail_count += 1
            continue
        
        # 转换格式
        cvat_annotations = convert_coco_to_cvat(coco_data, frame_mapping, label_ids, start_frame)
        shapes_count = len(cvat_annotations['shapes'])
        
        if shapes_count == 0:
            logger.info(f"   ℹ️  预标注为空")
            skip_count += 1
            continue
        
        logger.info(f"   转换完成: {shapes_count} 个标注")
        
        # 上传到CVAT
        try:
            cvat.upload_job_annotations(job_id, cvat_annotations)
            logger.info(f"   ✅ 导入成功")
            success_count += 1
            
            # 记录预标注信息
            preannotation_records[str(job_id)] = {
                'task_id': task_id,
                'shapes_count': shapes_count,
                'frames_count': len(frame_mapping),
                'imported_at': datetime.now().isoformat(),
                'bbox_json': bbox_json_key
            }
        except Exception as e:
            logger.error(f"   ❌ 导入失败: {e}")
            fail_count += 1
    
    # 6. 保存预标注记录
    if preannotation_records:
        save_preannotation_records(preannotation_records)
        logger.info(f"\n📋 预标注记录已保存: {preannotation_record_file}")
    
    # 7. 完成
    logger.info("\n" + "="*60)
    logger.info(f"✅ 导入完成")
    logger.info(f"   成功: {success_count}")
    logger.info(f"   跳过: {skip_count}")
    logger.info(f"   失败: {fail_count}")
    logger.info("="*60)
    logger.info(f"📝 日志文件: {log_file}")


def main():
    import sys
    
    task_id = None
    job_id = None
    
    # 解析参数
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--job' and i + 1 < len(args):
            job_id = int(args[i + 1])
            i += 2
        else:
            task_id = int(args[i])
            i += 1
    
    if not task_id:
        print("❌ 请指定任务ID")
        print("用法: python import_preannotations.py <task_id> [--job <job_id>]")
        print("示例: python import_preannotations.py 1972398")
        print("示例: python import_preannotations.py 1972398 --job 3541585")
        return
    
    import_preannotations(task_id=task_id, job_id=job_id)


if __name__ == "__main__":
    main()
