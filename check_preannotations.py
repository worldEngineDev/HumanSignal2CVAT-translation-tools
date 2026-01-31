#!/usr/bin/env python3
"""
查看云存储中的预标注统计
扫描所有 *_bbox.json 文件，统计每个 chunk 的预标注数量
"""
import json
import csv
import logging
import boto3
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# 配置日志
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

report_dir = Path('reports')
report_dir.mkdir(exist_ok=True)

log_file = log_dir / f'check_preannotations_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


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
    
    def list_bbox_jsons(self):
        """列出所有 *_bbox.json 文件"""
        bbox_files = []
        paginator = self.s3.get_paginator('list_objects_v2')
        
        for page in paginator.paginate(Bucket=self.bucket):
            for obj in page.get('Contents', []):
                if obj['Key'].endswith('_bbox.json'):
                    bbox_files.append(obj['Key'])
        
        return bbox_files
    
    def get_json(self, key):
        """下载并解析JSON文件"""
        try:
            resp = self.s3.get_object(Bucket=self.bucket, Key=key)
            return json.loads(resp['Body'].read().decode('utf-8'))
        except Exception as e:
            logger.error(f"获取JSON失败: {key}, {e}")
            return None


def extract_chunk_id(bbox_path):
    """
    从 bbox.json 路径提取 chunk ID
    格式: 23dc/session_20260121_173554_311375/0000/down/labels/23dc_down_sbs_0000_bbox.json
    返回: session_20260121_173554_311375_0000
    """
    parts = bbox_path.split('/')
    for i, part in enumerate(parts):
        if part.startswith('session_'):
            if i + 1 < len(parts):
                chunk_num = parts[i + 1]
                return f"{part}_{chunk_num}"
    return bbox_path


def check_preannotations(config_file='config.json'):
    """扫描预标注统计"""
    logger.info("="*60)
    logger.info("查看云存储预标注统计")
    logger.info("="*60)
    
    # 1. 加载配置
    logger.info("\n📖 加载配置文件...")
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ 配置文件不存在: {config_file}")
        return
    
    s3_config = config['s3']
    s3 = S3Client(s3_config)
    
    # 2. 列出所有 bbox.json
    logger.info("\n🔍 扫描预标注文件...")
    print("正在扫描云存储...", end='', flush=True)
    
    bbox_files = []
    file_count = 0
    paginator = s3.s3.get_paginator('list_objects_v2')
    
    for page in paginator.paginate(Bucket=s3.bucket):
        for obj in page.get('Contents', []):
            file_count += 1
            if file_count % 1000 == 0:
                print(f"\r正在扫描... {file_count} 个文件", end='', flush=True)
            if obj['Key'].endswith('_bbox.json'):
                bbox_files.append(obj['Key'])
    
    print(f"\r正在扫描... {file_count} 个文件 ✓")
    logger.info(f"✅ 扫描完成: {file_count} 个文件, 找到 {len(bbox_files)} 个预标注文件")
    
    if not bbox_files:
        logger.info("没有预标注文件")
        return
    
    # 3. 统计每个文件
    summary_data = []
    details_data = {}
    
    for idx, bbox_path in enumerate(bbox_files):
        chunk_id = extract_chunk_id(bbox_path)
        print(f"\r读取预标注: {idx+1}/{len(bbox_files)} - {chunk_id[:40]}", end='', flush=True)
        
        coco_data = s3.get_json(bbox_path)
        if not coco_data:
            continue
        
        images = coco_data.get('images', [])
        annotations = coco_data.get('annotations', [])
        
        # 统计每帧的标注数
        frame_annotations = defaultdict(int)
        for ann in annotations:
            image_id = ann['image_id']
            frame_annotations[image_id] += 1
        
        # 获取帧文件名映射
        image_id_to_name = {img['id']: img['file_name'] for img in images}
        
        # 汇总
        total_frames = len(images)
        annotated_frames = len(frame_annotations)
        total_annotations = len(annotations)
        
        summary_data.append({
            'chunk_id': chunk_id,
            'bbox_file': bbox_path,
            'total_frames': total_frames,
            'annotated_frames': annotated_frames,
            'total_annotations': total_annotations
        })
        
        # 详情
        details_data[chunk_id] = {
            'bbox_file': bbox_path,
            'total_frames': total_frames,
            'annotated_frames': annotated_frames,
            'total_annotations': total_annotations,
            'frames': [
                {
                    'image_id': img_id,
                    'file_name': image_id_to_name.get(img_id, ''),
                    'annotation_count': count
                }
                for img_id, count in sorted(frame_annotations.items())
            ]
        }
    
    print(f"\r读取预标注: {len(bbox_files)}/{len(bbox_files)} ✓" + " " * 30)
    
    # 4. 输出汇总CSV
    summary_file = report_dir / 'preannotation_summary.csv'
    with open(summary_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['Chunk ID', '预标注文件', '总帧数', '有标注帧数', '标注总数']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary_data:
            writer.writerow({
                'Chunk ID': row['chunk_id'],
                '预标注文件': row['bbox_file'],
                '总帧数': row['total_frames'],
                '有标注帧数': row['annotated_frames'],
                '标注总数': row['total_annotations']
            })
    
    logger.info(f"\n✅ 汇总CSV已保存: {summary_file}")
    
    # 5. 输出详情JSON
    details_file = report_dir / 'preannotation_details.json'
    with open(details_file, 'w', encoding='utf-8') as f:
        json.dump(details_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"✅ 详情JSON已保存: {details_file}")
    
    # 6. 显示汇总
    logger.info("\n" + "="*60)
    logger.info("📊 预标注汇总")
    logger.info("="*60)
    
    total_chunks = len(summary_data)
    total_frames = sum(r['total_frames'] for r in summary_data)
    total_annotated = sum(r['annotated_frames'] for r in summary_data)
    total_annotations = sum(r['total_annotations'] for r in summary_data)
    
    logger.info(f"\n总计:")
    logger.info(f"   Chunks: {total_chunks}")
    logger.info(f"   总帧数: {total_frames}")
    logger.info(f"   有标注帧: {total_annotated}")
    logger.info(f"   标注总数: {total_annotations}")
    
    logger.info("\n" + "="*60)
    logger.info(f"📝 日志文件: {log_file}")


def main():
    check_preannotations()


if __name__ == "__main__":
    main()
