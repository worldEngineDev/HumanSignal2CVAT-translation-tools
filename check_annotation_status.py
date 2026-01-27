#!/usr/bin/env python3
"""
核对云存储和CVAT平台的标注状态
找出哪些数据已标注、哪些未标注
"""
import requests
import json
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

# 配置日志
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f'check_status_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

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
    
    def get_task_data(self, task_id):
        """获取任务的所有图片"""
        url = f'{self.base_url}/api/tasks/{task_id}/data/meta'
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            frames = data.get('frames', [])
            images = [frame.get('name') for frame in frames if frame.get('name')]
            
            logger.info(f"   任务 {task_id}: {len(images)} 张图片")
            return images
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 获取任务数据失败: task_id={task_id}, {e}")
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
    
    def get_job_has_annotations(self, job_id):
        """检查job是否有标注（只检查数量，不获取全部数据）"""
        url = f'{self.base_url}/api/jobs/{job_id}/annotations'
        
        try:
            # 只获取第一页，检查是否有数据
            response = requests.get(url, headers=self.headers, params={'page_size': 1}, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # 检查是否有shapes或tracks
            has_shapes = len(data.get('shapes', [])) > 0
            has_tracks = len(data.get('tracks', [])) > 0
            
            return has_shapes or has_tracks
        except requests.exceptions.Timeout:
            logger.debug(f"检查job {job_id}超时")
            return False
        except requests.exceptions.RequestException as e:
            logger.debug(f"检查job {job_id}失败: {e}")
            return False


def list_s3_files(bucket_name, prefix, aws_access_key_id=None, aws_secret_access_key=None, region_name='us-east-1', account_id=None):
    """列举S3/R2存储桶中的文件
    
    Args:
        bucket_name: S3 bucket名称
        prefix: 文件路径前缀
        aws_access_key_id: AWS Access Key ID
        aws_secret_access_key: AWS Secret Access Key
        region_name: AWS Region
        account_id: Cloudflare R2 Account ID（如果使用R2）
        
    Returns:
        文件路径列表，如果失败返回None
    """
    if not HAS_BOTO3:
        logger.error("❌ boto3未安装，无法访问S3")
        logger.info("💡 安装: pip install boto3")
        return None
    
    try:
        # 判断是否是Cloudflare R2
        if account_id:
            # Cloudflare R2 endpoint
            endpoint_url = f'https://{account_id}.r2.cloudflarestorage.com'
            logger.info(f"   使用Cloudflare R2: {endpoint_url}")
            s3_client = boto3.client(
                's3',
                endpoint_url=endpoint_url,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name='auto'
            )
        else:
            # 标准AWS S3
            if aws_access_key_id and aws_secret_access_key:
                s3_client = boto3.client(
                    's3',
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    region_name=region_name
                )
            else:
                # 使用默认凭证
                s3_client = boto3.client('s3', region_name=region_name)
        
        logger.info(f"   正在列举文件: {bucket_name}/{prefix}")
        
        # 先列举根目录看看有什么
        logger.info(f"   先检查根目录...")
        try:
            root_response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix='', MaxKeys=10)
            if 'Contents' in root_response:
                logger.info(f"   根目录示例文件:")
                for obj in root_response['Contents'][:5]:
                    logger.info(f"     - {obj['Key']}")
        except Exception as e:
            logger.warning(f"   无法列举根目录: {e}")
        
        # 列举对象
        files = []
        paginator = s3_client.get_paginator('list_objects_v2')
        
        for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    # 只要文件，不要目录
                    if not key.endswith('/'):
                        files.append(key)
        
        logger.info(f"✅ 找到 {len(files)} 个文件")
        return files
        
    except NoCredentialsError:
        logger.error("❌ AWS凭证未找到")
        logger.info("💡 在config.json中配置s3部分")
        return None
    except ClientError as e:
        logger.error(f"❌ S3访问失败: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ 列举文件失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def extract_basename(file_path):
    """提取文件基础名（去掉路径和hash前缀）"""
    basename = file_path.split('/')[-1]
    if '__' in basename:
        basename = basename.split('__', 1)[1]
    return basename


def check_annotation_status(config_file='config.json', task_ids=None):
    """核对标注状态主流程
    
    Args:
        config_file: 配置文件路径
        task_ids: 可选的任务ID列表，如果指定则只检查这些任务
    """
    logger.info("="*60)
    logger.info("核对CVAT平台的标注状态")
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
    
    # S3配置
    s3_config = config.get('s3', {})
    bucket_name = s3_config.get('bucket_name')
    prefix = s3_config.get('prefix', 'test_1000/images/')
    aws_access_key_id = s3_config.get('aws_access_key_id')
    aws_secret_access_key = s3_config.get('aws_secret_access_key')
    region_name = s3_config.get('region', 'us-east-1')
    account_id = s3_config.get('account_id')  # Cloudflare R2 Account ID
    
    # 2. 初始化CVAT客户端
    cvat_client = CVATClient(cvat_url, api_key)
    
    # 3. 从S3/R2获取云存储文件列表
    cloud_basenames = None
    
    if bucket_name:
        logger.info(f"\n📁 从云存储获取文件列表...")
        logger.info(f"   Bucket: {bucket_name}")
        logger.info(f"   Prefix: {prefix}")
        
        s3_files = list_s3_files(
            bucket_name=bucket_name,
            prefix=prefix,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
            account_id=account_id
        )
        
        if s3_files:
            # 按 session 分组文件，检查是否有 json 文件（标志 session 完整）
            logger.info(f"   检查 session 完整性（是否有 json 文件）...")
            
            session_files = defaultdict(lambda: {'images': [], 'has_json': False})
            
            for file_path in s3_files:
                # 提取 session ID
                # 路径格式: b1e0/session_20260108_034622_359267/0000/down/labels/xxx/frame_00089.jpg
                parts = file_path.split('/')
                session_id = None
                for part in parts:
                    if part.startswith('session_'):
                        session_id = part
                        break
                
                if not session_id:
                    continue
                
                # 检查是否是 json 文件
                if file_path.endswith('.json'):
                    session_files[session_id]['has_json'] = True
                elif file_path.endswith('.jpg') or file_path.endswith('.png'):
                    session_files[session_id]['images'].append(file_path)
            
            # 只保留有 json 文件的完整 session
            complete_sessions = {sid: data for sid, data in session_files.items() if data['has_json']}
            incomplete_sessions = {sid: data for sid, data in session_files.items() if not data['has_json']}
            
            logger.info(f"   完整 session: {len(complete_sessions)} 个")
            logger.info(f"   不完整 session（无json）: {len(incomplete_sessions)} 个")
            
            if incomplete_sessions:
                logger.info(f"   不完整的 session 将被跳过:")
                for sid in sorted(incomplete_sessions.keys())[:5]:
                    img_count = len(incomplete_sessions[sid]['images'])
                    logger.info(f"      - {sid}: {img_count} 张图片（无json文件）")
                if len(incomplete_sessions) > 5:
                    logger.info(f"      ... 还有 {len(incomplete_sessions) - 5} 个")
            
            # 构建 cloud_basenames 和 cloud_path_map（只包含完整 session 的图片）
            cloud_basenames = set()
            cloud_path_map = {}  # basename -> 完整路径的映射
            
            for session_id, data in complete_sessions.items():
                for file_path in data['images']:
                    basename = file_path.split('/')[-1]
                    # 去掉hash前缀
                    if '__' in basename:
                        basename = basename.split('__', 1)[1]
                    cloud_basenames.add(basename)
                    # 记录第一次出现的完整路径
                    if basename not in cloud_path_map:
                        cloud_path_map[basename] = file_path
            
            logger.info(f"✅ 云存储文件（完整session）: {len(cloud_basenames)} 个")
        else:
            logger.warning("⚠️  无法从S3获取文件列表")
            cloud_path_map = {}
    else:
        logger.warning("⚠️  未配置S3，将只统计CVAT中的数据")
        logger.info("💡 在config.json中添加s3配置：")
        cloud_path_map = {}
    
    # 4. 获取CVAT中的所有任务和图片
    logger.info(f"\n📋 获取CVAT任务列表...")
    
    if task_ids:
        # 使用指定的任务ID
        tasks = []
        for task_id in task_ids:
            url = f'{cvat_url}/api/tasks/{task_id}'
            try:
                response = requests.get(url, headers={'Authorization': f'Token {api_key}'}, timeout=30)
                response.raise_for_status()
                tasks.append(response.json())
            except Exception as e:
                logger.error(f"❌ 获取任务失败: task_id={task_id}, {e}")
    else:
        # 获取所有任务
        tasks = cvat_client.get_all_tasks(organization_slug)
    
    if not tasks:
        logger.warning("⚠️  未找到任何任务")
        cvat_images = set()
        cvat_annotated_images = set()
    else:
        logger.info(f"✅ 找到 {len(tasks)} 个任务")
        
        cvat_images = set()
        cvat_annotated_images = set()
        
        logger.info(f"\n📊 分析任务数据...")
        for idx, task in enumerate(tasks, 1):
            task_id = task['id']
            task_name = task['name']
            
            logger.info(f"\n[{idx}/{len(tasks)}] 处理任务: {task_name} (ID: {task_id})")
            
            # 获取任务图片列表
            images = cvat_client.get_task_data(task_id)
            image_basenames = []
            for img_path in images:
                basename = extract_basename(img_path)
                cvat_images.add(basename)
                image_basenames.append(basename)
            
            logger.info(f"   → 图片数: {len(images)}")
            
            # 获取任务的jobs
            logger.info(f"   → 获取jobs...")
            jobs = cvat_client.get_task_jobs(task_id)
            logger.info(f"   → Jobs数: {len(jobs)}")
            
            # 检查每个job是否有标注（并发执行）
            logger.info(f"   → 检查标注状态（并发检查）...")
            annotated_job_count = 0
            
            # 准备检查任务
            def check_job(job_info):
                job_idx, job = job_info
                job_id = job.get('id')
                start_frame = job.get('start_frame', 0)
                stop_frame = job.get('stop_frame', 0)
                frame_count = stop_frame - start_frame + 1
                
                has_annotations = cvat_client.get_job_has_annotations(job_id)
                
                return {
                    'job_idx': job_idx,
                    'job_id': job_id,
                    'start_frame': start_frame,
                    'stop_frame': stop_frame,
                    'frame_count': frame_count,
                    'has_annotations': has_annotations
                }
            
            # 并发检查（最多10个并发）
            results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(check_job, (idx, job)): idx for idx, job in enumerate(jobs, 1)}
                
                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)
                    
                    # 显示进度
                    if len(results) % 10 == 0 or len(results) == len(jobs):
                        logger.info(f"      进度: {len(results)}/{len(jobs)} jobs")
            
            # 按job顺序排序结果
            results.sort(key=lambda x: x['job_idx'])
            
            # 处理结果
            for result in results:
                if result['has_annotations']:
                    annotated_job_count += 1
                    # 将这个job的所有帧标记为已标注
                    for frame_idx in range(result['start_frame'], result['stop_frame'] + 1):
                        if frame_idx < len(image_basenames):
                            cvat_annotated_images.add(image_basenames[frame_idx])
            
            logger.info(f"   ✓ 已标注jobs: {annotated_job_count}/{len(jobs)}")
        
        logger.info(f"\n✅ CVAT统计:")
        logger.info(f"   已加载图片: {len(cvat_images)} 个")
        logger.info(f"   已标注图片: {len(cvat_annotated_images)} 个")
    
    # 5. 对比分析
    logger.info(f"\n🔍 分析结果...")
    
    loaded_not_annotated = cvat_images - cvat_annotated_images
    
    if cloud_basenames is not None:
        # 有云存储数据，进行对比
        new_images = cloud_basenames - cvat_images
        
        logger.info(f"\n📊 对比结果:")
        logger.info(f"   云存储总文件: {len(cloud_basenames)}")
        logger.info(f"   已加载到CVAT: {len(cvat_images)}")
        logger.info(f"   CVAT已标注: {len(cvat_annotated_images)}")
        logger.info(f"   已加载未标注: {len(loaded_not_annotated)}")
        logger.info(f"   未加载（新数据）: {len(new_images)}")
        
        result = {
            'summary': {
                'cloud_total': len(cloud_basenames),
                'cvat_loaded': len(cvat_images),
                'cvat_annotated': len(cvat_annotated_images),
                'cvat_not_annotated': len(loaded_not_annotated),
                'new_images': len(new_images),
            },
            'new_images': sorted(list(new_images)),
            'annotated_images': sorted(list(cvat_annotated_images)),
            'not_annotated_images': sorted(list(loaded_not_annotated)),
        }
        
        # 生成新数据文件列表
        if new_images:
            new_images_file = log_dir / f'new_images_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
            with open(new_images_file, 'w', encoding='utf-8') as f:
                for img in sorted(new_images):
                    # 使用完整的云存储路径
                    full_path = cloud_path_map.get(img, f"{prefix}{img}")
                    f.write(f"{full_path}\n")
            
            logger.info(f"\n✅ 新数据列表已保存: {new_images_file}")
            logger.info(f"💡 下一步: 使用 import_new_data.py 导入新数据")
    else:
        # 只有CVAT数据
        logger.info(f"\n📊 CVAT标注状态:")
        logger.info(f"   总图片数: {len(cvat_images)}")
        logger.info(f"   已标注: {len(cvat_annotated_images)}")
        logger.info(f"   未标注: {len(loaded_not_annotated)}")
        
        result = {
            'summary': {
                'cvat_total': len(cvat_images),
                'cvat_annotated': len(cvat_annotated_images),
                'cvat_not_annotated': len(loaded_not_annotated),
            },
            'annotated_images': sorted(list(cvat_annotated_images)),
            'not_annotated_images': sorted(list(loaded_not_annotated)),
        }
    
    # 6. 保存结果
    result_file = log_dir / f'annotation_status_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\n✅ 结果已保存: {result_file}")
    
    logger.info(f"\n📝 日志文件: {log_file}")
    logger.info("="*60)


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
            logger.info("用法: python check_annotation_status.py [task_id1] [task_id2] ...")
            return
    
    check_annotation_status(task_ids=task_ids)


if __name__ == "__main__":
    main()
