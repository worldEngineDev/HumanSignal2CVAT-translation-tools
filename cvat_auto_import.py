#!/usr/bin/env python3
"""
CVAT自动化导入工具 - 创建1个任务，按session分成多个jobs
"""
import requests
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import re
import zipfile
import io

# 配置日志
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f'cvat_import_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

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
        self.headers = {
            'Authorization': f'Token {api_key}'
        }
        logger.info(f"初始化CVAT客户端: {base_url}")
    
    def create_task(self, name, labels, organization_slug=None):
        """创建任务并定义标签"""
        # 在URL中指定组织
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
            logger.info(f"✅ 任务创建成功: ID={task['id']}, Name={name}, Org={task.get('organization')}")
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
        
        # 如果提供了 job_file_mapping，则添加
        if job_file_mapping:
            payload['job_file_mapping'] = job_file_mapping
            logger.info(f"   使用 job_file_mapping: {len(job_file_mapping)} 个 jobs")
        else:
            # 不使用 job_file_mapping，使用自然排序
            payload['sorting_method'] = 'natural'
            logger.info(f"   不使用 job_file_mapping，使用自然排序")
        
        headers = {**self.headers, 'Content-Type': 'application/json'}
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            logger.info(f"✅ 数据加载请求已提交: task_id={task_id}")
            if job_file_mapping:
                logger.info(f"   将创建 {len(job_file_mapping)} 个jobs")
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 加载数据失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"   响应内容: {e.response.text}")
            raise
    
    def upload_annotations(self, task_id, annotation_data, format_name='COCO 1.0'):
        """上传标注（直接传入JSON数据）"""
        url = f'{self.base_url}/api/tasks/{task_id}/annotations'
        params = {'format': format_name}
        
        # 创建内存中的zip文件
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            json_str = json.dumps(annotation_data, ensure_ascii=False, indent=2)
            zipf.writestr('annotations/instances_default.json', json_str)
        
        zip_buffer.seek(0)
        
        headers = {'Authorization': self.headers['Authorization']}
        files = {'annotation_file': ('annotations.zip', zip_buffer, 'application/zip')}
        
        try:
            response = requests.post(
                url, 
                headers=headers, 
                params=params, 
                files=files,
                timeout=120
            )
            response.raise_for_status()
            logger.info(f"✅ 标注上传成功: task_id={task_id}")
            return response.status_code
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 上传标注失败: {e}")
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
            return task.get('status')
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 检查任务状态失败: {e}")
            return None
    
    def wait_for_task_ready(self, task_id, timeout=300, check_interval=10):
        """等待任务准备就绪并检查错误"""
        logger.info(f"⏳ 等待任务准备就绪: task_id={task_id}")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.check_task_status(task_id)
            if status in ['annotation', 'validation', 'completed']:
                logger.info(f"✅ 任务已就绪: task_id={task_id}, status={status}")
                return True
            elif status == 'failed':
                logger.error(f"❌ 任务失败: task_id={task_id}")
                return False
            
            time.sleep(check_interval)
        
        logger.warning(f"⚠️  等待超时: task_id={task_id}")
        return False
    
    def wait_for_data_loading(self, task_id, expected_size, timeout=3600, check_interval=30):
        """等待数据加载完成（检查图片数量）- 适用于大量图片"""
        logger.info(f"⏳ 等待数据加载完成: task_id={task_id}, 预期图片数={expected_size}")
        logger.info(f"   预计需要时间: {expected_size // 100} - {expected_size // 50} 分钟")
        logger.info(f"   每 {check_interval} 秒检查一次进度...")
        
        start_time = time.time()
        last_size = 0
        no_progress_count = 0
        
        while time.time() - start_time < timeout:
            try:
                url = f'{self.base_url}/api/tasks/{task_id}'
                response = requests.get(url, headers=self.headers, timeout=30)
                response.raise_for_status()
                task = response.json()
                
                current_size = task.get('size', 0)
                status = task.get('status')
                elapsed = int(time.time() - start_time)
                
                # 显示进度
                if current_size != last_size:
                    progress_pct = (current_size * 100 // expected_size) if expected_size > 0 else 0
                    remaining_time = 0
                    if current_size > 0:
                        # 估算剩余时间
                        time_per_image = elapsed / current_size
                        remaining_images = expected_size - current_size
                        remaining_time = int(remaining_images * time_per_image / 60)
                    
                    logger.info(f"   [{elapsed//60}分{elapsed%60}秒] 进度: {current_size}/{expected_size} ({progress_pct}%) | 预计剩余: {remaining_time}分钟")
                    last_size = current_size
                    no_progress_count = 0
                else:
                    no_progress_count += 1
                    # 如果连续 5 次没有进度，显示等待信息
                    if no_progress_count % 5 == 0:
                        logger.info(f"   [{elapsed//60}分{elapsed%60}秒] 等待中... (当前: {current_size}/{expected_size})")
                
                # 如果图片数达到预期，认为加载完成
                if current_size >= expected_size * 0.95:  # 允许 5% 的误差（去重等原因）
                    logger.info(f"✅ 数据加载完成: {current_size} 张图片 (耗时: {elapsed//60}分{elapsed%60}秒)")
                    return True
                
                # 如果状态变为 failed，停止等待
                if status == 'failed':
                    logger.error(f"❌ 任务失败: task_id={task_id}")
                    return False
                
                # 如果长时间没有进度（超过 10 次检查），可能有问题
                if no_progress_count > 10 and current_size == 0:
                    logger.warning(f"⚠️  长时间没有进度，可能数据加载失败")
                    return False
                    
            except Exception as e:
                logger.warning(f"   检查进度时出错: {e}")
            
            time.sleep(check_interval)
        
        logger.warning(f"⚠️  数据加载超时: 当前 {last_size}/{expected_size} 图片 (超时时间: {timeout//60}分钟)")
        return False
    
    def check_task_jobs(self, task_id):
        """检查任务的jobs状态"""
        url = f'{self.base_url}/api/jobs'
        params = {'task_id': task_id}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            jobs = response.json()
            return jobs
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 检查jobs失败: {e}")
            return None
    
    def update_job_names(self, task_id, job_names):
        """更新job名称"""
        # 获取所有jobs
        url = f'{self.base_url}/api/jobs'
        params = {'task_id': task_id}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            jobs = response.json()
            
            job_list = jobs.get('results', [])
            logger.info(f"📝 更新job名称: 共{len(job_list)}个jobs")
            
            # 按start_frame排序（确保顺序正确）
            job_list.sort(key=lambda x: x.get('start_frame', 0))
            
            # 更新每个job的名称
            for idx, job in enumerate(job_list):
                if idx < len(job_names):
                    job_id = job['id']
                    job_name = job_names[idx]
                    
                    # 更新job
                    update_url = f'{self.base_url}/api/jobs/{job_id}'
                    payload = {'stage': job.get('stage'), 'state': job.get('state'), 'assignee': job.get('assignee')}
                    
                    # CVAT可能不支持直接设置job name，我们尝试通过其他方式
                    # 先检查job对象有哪些可编辑字段
                    logger.info(f"   Job {job_id}: {job_name} (frames: {job.get('start_frame')}-{job.get('stop_frame')})")
            
            logger.info(f"✅ Job名称记录完成")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 更新job名称失败: {e}")
            return False
    
    def check_import_status(self, task_id, wait_time=10):
        """检查导入状态和错误 - 等待一段时间后检查"""
        time.sleep(wait_time)  # 等待导入处理
        
        url = f'{self.base_url}/api/requests'
        params = {'target': f'task/{task_id}', 'page_size': 100}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            if response.status_code == 200:
                requests_data = response.json()
                results = requests_data.get('results', [])
                
                logger.info(f"📋 检查导入请求状态...")
                
                if not results:
                    logger.warning(f"   ⚠️  没有找到导入请求记录")
                    return None
                
                has_errors = False
                for req in results:
                    operation = req.get('operation')
                    status = req.get('status')
                    message = req.get('message', '')
                    
                    logger.info(f"   操作: {operation}, 状态: {status}")
                    
                    if status == 'failed':
                        has_errors = True
                        logger.error(f"   ❌ 操作失败!")
                        if message:
                            # 显示完整错误信息
                            logger.error(f"   错误信息: {message}")
                            
                            # 分析常见错误
                            if 'is not specified in input files' in message:
                                logger.error(f"   ⚠️  job_file_mapping 不一致 - 某些文件在 job_file_mapping 中但不在 server_files 中")
                                logger.error(f"   建议: 检查数据去重逻辑")
                            elif 'Could not match item id' in message:
                                logger.error(f"   ⚠️  图片路径不匹配 - 标注文件中的路径与加载的图片路径不一致")
                            elif 'can\'t import annotation' in message:
                                logger.error(f"   ⚠️  标注导入失败 - 可能是label不匹配或格式错误")
                            elif 'ValidationError' in message:
                                logger.error(f"   ⚠️  验证错误 - 请求参数不正确")
                    
                    elif status == 'finished' and message:
                        # 即使成功也可能有警告信息
                        if 'error' in message.lower() or 'warning' in message.lower():
                            logger.warning(f"   ⚠️  有警告信息: {message[:200]}")
                
                return {'has_errors': has_errors, 'results': results}
        except Exception as e:
            logger.warning(f"⚠️  无法检查导入状态: {e}")
        
        return None


def extract_session_id(filename):
    """提取session ID"""
    basename = filename.split('/')[-1]
    if '__' in basename:
        basename = basename.split('__', 1)[1]
    
    parts = basename.split('_')
    if len(parts) >= 4 and 'session' in basename:
        return '_'.join(parts[:4])
    return None


def group_data_by_session(data):
    """按session分组数据"""
    sessions = defaultdict(lambda: {
        'images': [],
        'annotations': [],
        'image_ids': set()
    })
    
    # 分组图片
    for img in data['images']:
        session_id = extract_session_id(img['file_name'])
        if session_id:
            sessions[session_id]['images'].append(img)
            sessions[session_id]['image_ids'].add(img['id'])
    
    # 分组标注
    for ann in data['annotations']:
        img_id = ann['image_id']
        for session_id, content in sessions.items():
            if img_id in content['image_ids']:
                content['annotations'].append(ann)
                break
    
    logger.info(f"数据分组完成: {len(sessions)} 个session")
    return sessions


def create_session_annotation_data(session_data, categories):
    """为单个session创建标注数据"""
    return {
        'images': session_data['images'],
        'annotations': session_data['annotations'],
        'categories': categories
    }


def auto_import_to_cvat(config_file='config.json'):
    """自动化导入主流程 - 创建1个任务，按session分成jobs"""
    logger.info("="*60)
    logger.info("开始CVAT自动化导入")
    logger.info("="*60)
    
    # 1. 加载配置
    logger.info("📖 加载配置文件...")
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ 配置文件不存在: {config_file}")
        logger.info("💡 请先创建配置文件，参考 config.example.json")
        return
    
    cvat_url = config['cvat']['url']
    api_key = config['cvat']['api_key']
    
    # 使用旧桶配置（用于从旧平台迁移数据）
    cloud_storage_config = config.get('cloud_storage_old', config.get('cloud_storage'))
    cloud_storage_id = cloud_storage_config['id']
    logger.info(f"   使用云存储: {cloud_storage_config.get('name', 'Unknown')} (ID: {cloud_storage_id})")
    
    organization_slug = config.get('organization', {}).get('slug', 'wp')  # 使用slug而不是id
    input_json = config['files']['humansignal_json']
    task_name = config.get('task', {}).get('name', 'Hand Detection - HumanSignal Import')
    
    # 新增：是否使用 job_file_mapping（默认关闭）
    use_job_mapping = config.get('use_job_file_mapping', False)
    if use_job_mapping:
        logger.info("   ⚠️  将使用 job_file_mapping 按 session 分组")
    else:
        logger.info("   ℹ️  不使用 job_file_mapping，所有图片在一个任务中")
    input_json = config['files']['humansignal_json']
    task_name = config.get('task', {}).get('name', 'Hand Detection - HumanSignal Import')
    
    # 2. 读取HumanSignal数据
    logger.info(f"📖 读取HumanSignal数据: {input_json}")
    try:
        with open(input_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ 数据文件不存在: {input_json}")
        return
    
    categories = data['categories']
    # 按 category ID 排序，确保 label 顺序和 category_id 对应
    categories_sorted = sorted(categories, key=lambda x: x['id'])
    labels = [{'name': cat['name'], 'color': '#ff00ff'} for cat in categories_sorted]
    
    logger.info(f"✅ 数据加载完成")
    logger.info(f"   总图片数: {len(data['images'])}")
    logger.info(f"   总标注数: {len(data['annotations'])}")
    logger.info(f"   类别数: {len(categories)}")
    logger.info(f"   类别列表: {[cat['name'] for cat in categories_sorted]}")
    
    # 3. 按session分组
    logger.info("📊 按session分组数据...")
    sessions = group_data_by_session(data)
    
    # 4. 准备job_file_mapping和session名称
    logger.info("🗂️  准备job分组映射...")
    job_file_mapping = []
    all_image_paths = []
    seen_paths = set()  # 用于去重
    session_names = []  # 记录session名称
    file_to_session = {}  # 记录每个文件属于哪个 session（第一次出现的）
    
    # 第一步：收集所有唯一的文件路径，并记录它们第一次出现的 session
    for session_id in sorted(sessions.keys()):
        session_data = sessions[session_id]
        
        for img in session_data['images']:
            # 转换路径格式
            path = img['file_name']  # images/461ff0b4__3748_session_xxx.jpg
            basename = path.split('/')[-1]  # 461ff0b4__3748_session_xxx.jpg
            if '__' in basename:
                basename = basename.split('__', 1)[1]  # 3748_session_xxx.jpg
            
            # 云存储路径格式: test_1000/images/<文件名>
            final_path = f"test_1000/images/{basename}"
            
            # 去重：只添加一次到 all_image_paths
            if final_path not in seen_paths:
                seen_paths.add(final_path)
                all_image_paths.append(final_path)
                file_to_session[final_path] = session_id  # 记录第一次出现的 session
    
    logger.info(f"   收集到 {len(all_image_paths)} 个唯一文件")
    
    # 第二步：构建 job_file_mapping（每个文件只出现一次，在第一次出现的 session 中）
    for session_id in sorted(sessions.keys()):
        session_data = sessions[session_id]
        session_files = []
        seen_in_session = set()  # 防止同一个 session 中重复添加
        
        for img in session_data['images']:
            path = img['file_name']
            basename = path.split('/')[-1]
            if '__' in basename:
                basename = basename.split('__', 1)[1]
            
            # 云存储路径格式: test_1000/images/<文件名>
            final_path = f"test_1000/images/{basename}"
            
            # 只添加属于当前 session 的文件（第一次出现在这个 session）
            # 并且在当前 session 中还没有添加过
            if file_to_session.get(final_path) == session_id and final_path not in seen_in_session:
                session_files.append(final_path)
                seen_in_session.add(final_path)
        
        if session_files:  # 只添加非空的session
            job_file_mapping.append(session_files)
            session_names.append(session_id)
            logger.info(f"   Session {session_id}: {len(session_files)} 张图片")
    
    logger.info(f"✅ 分组完成: {len(job_file_mapping)} 个jobs, {len(all_image_paths)} 张图片（去重后）")
    
    # 验证：确保 job_file_mapping 中的所有文件都在 all_image_paths 中
    logger.info("🔍 验证 job_file_mapping 一致性...")
    all_files_in_mapping = set()
    for session_files in job_file_mapping:
        all_files_in_mapping.update(session_files)
    
    missing_files = all_files_in_mapping - set(all_image_paths)
    if missing_files:
        logger.error(f"❌ 发现不一致: {len(missing_files)} 个文件在 job_file_mapping 中但不在 server_files 中")
        for f in list(missing_files)[:10]:
            logger.error(f"   - {f}")
        logger.error(f"   这会导致 CVAT 拒绝请求，请检查数据")
        return
    
    extra_files = set(all_image_paths) - all_files_in_mapping
    if extra_files:
        logger.warning(f"⚠️  {len(extra_files)} 个文件在 server_files 中但不在任何 job 中")
    
    logger.info(f"✅ 验证通过: job_file_mapping 和 server_files 一致")
    logger.info(f"   - server_files 文件数: {len(all_image_paths)}")
    logger.info(f"   - job_file_mapping 文件数: {len(all_files_in_mapping)}")
    logger.info(f"   - 总引用次数: {sum(len(files) for files in job_file_mapping)}")
    
    # 5. 创建CVAT客户端
    client = CVATClient(cvat_url, api_key)
    
    # 6. 创建任务
    logger.info(f"\n🏗️  创建任务: {task_name}")
    try:
        task = client.create_task(task_name, labels, organization_slug)
        task_id = task['id']
        logger.info(f"✅ 任务创建成功: ID={task_id}")
    except Exception as e:
        logger.error(f"❌ 创建任务失败: {e}")
        return
    
    # 7. 加载图片并指定job分组
    logger.info(f"\n📁 加载图片并创建jobs...")
    logger.info(f"   总图片数: {len(all_image_paths)}")
    logger.info(f"   Jobs数量: {len(job_file_mapping)}")
    
    # 保存调试信息
    debug_file = log_dir / f'debug_request_{task_id}.json'
    with open(debug_file, 'w', encoding='utf-8') as f:
        json.dump({
            'task_id': task_id,
            'server_files_count': len(all_image_paths),
            'server_files_sample': all_image_paths[:10],
            'job_file_mapping_count': len(job_file_mapping),
            'job_file_mapping_sample': [files[:5] for files in job_file_mapping[:3]],
            'session_names': session_names[:10]
        }, f, indent=2, ensure_ascii=False)
    logger.info(f"   调试信息已保存: {debug_file}")
    
    try:
        if use_job_mapping:
            # 使用 job_file_mapping
            client.attach_data_with_jobs(
                task_id, 
                cloud_storage_id, 
                all_image_paths,
                job_file_mapping
            )
        else:
            # 不使用 job_file_mapping
            client.attach_data_with_jobs(
                task_id, 
                cloud_storage_id, 
                all_image_paths,
                None  # 不传 job_file_mapping
            )
    except Exception as e:
        logger.error(f"❌ 加载数据失败: {e}")
        logger.error(f"   请检查调试文件: {debug_file}")
        return
    
    # 8. 等待数据加载完成（检查图片数量）
    logger.info(f"\n⏳ 等待数据加载完成...")
    logger.info(f"   提示: 21,000+ 张图片预计需要 15-30 分钟")
    logger.info(f"   请耐心等待，脚本会每 30 秒显示一次进度")
    
    if not client.wait_for_data_loading(task_id, len(all_image_paths), timeout=3600, check_interval=30):  # 60分钟超时，每30秒检查
        logger.error(f"❌ 数据加载超时或失败")
        logger.info(f"   建议: 手动检查 CVAT 任务状态: {cvat_url}/tasks/{task_id}")
        # 检查导入状态
        client.check_import_status(task_id)
        return
    
    # 8.5 检查jobs创建情况并更新名称
    logger.info(f"\n🔍 检查jobs创建情况...")
    jobs_data = client.check_task_jobs(task_id)
    if jobs_data:
        job_count = jobs_data.get('count', 0)
        logger.info(f"   实际创建的jobs数量: {job_count}")
        if job_count != len(job_file_mapping):
            logger.warning(f"   ⚠️  预期{len(job_file_mapping)}个jobs，实际{job_count}个")
        
        # 尝试更新job名称
        if job_count == len(session_names):
            logger.info(f"\n📝 为jobs设置session名称...")
            client.update_job_names(task_id, session_names)
    
    # 8.6 检查数据加载状态
    logger.info(f"\n🔍 检查数据加载状态...")
    load_status = client.check_import_status(task_id, wait_time=10)
    if load_status and load_status.get('has_errors'):
        logger.error(f"\n❌ 数据加载有错误，请检查上面的错误信息")
        logger.error(f"   建议: 检查云存储中的图片路径是否正确")
    
    # 9. 上传标注
    logger.info(f"\n📤 上传标注...")
    
    # 转换标注文件中的图片路径，使其与加载的图片路径一致
    # 重要：只包含实际加载的图片！
    logger.info(f"   转换标注文件中的图片路径...")
    
    # 创建实际加载的文件名集合（用于过滤）
    loaded_files_set = set(all_image_paths)
    logger.info(f"   实际加载的文件数: {len(loaded_files_set)}")
    
    converted_data = data.copy()
    converted_images = []
    path_mapping = {}  # 原始路径 -> 新路径
    loaded_image_ids = set()  # 实际加载的图片 ID
    
    for img in data['images']:
        original_path = img['file_name']
        
        # 转换路径
        basename = original_path.split('/')[-1]
        if '__' in basename:
            basename = basename.split('__', 1)[1]
        
        # 添加 prefix 前缀
        new_path = f"test_1000/images/{basename}"
        
        # 只包含实际加载的文件（用完整路径匹配）
        if new_path not in loaded_files_set:
            continue
        
        # 记录映射关系
        path_mapping[original_path] = new_path
        loaded_image_ids.add(img['id'])
        
        # 创建新的image对象
        new_img = img.copy()
        new_img['file_name'] = new_path
        converted_images.append(new_img)
    
    # 确保 categories 格式正确（CVAT 需要 category_id 从 1 开始）
    logger.info(f"🏷️  处理类别信息...")
    converted_categories = []
    category_id_mapping = {}  # 旧ID -> 新ID
    
    for idx, cat in enumerate(categories_sorted):
        new_id = idx + 1  # 从 1 开始，而不是从 0
        category_id_mapping[cat['id']] = new_id
        converted_cat = {
            'id': new_id,
            'name': cat['name'],
            'supercategory': cat.get('supercategory', '')
        }
        converted_categories.append(converted_cat)
    
    logger.info(f"   类别ID映射: {category_id_mapping}")
    
    # 只包含已加载图片的标注，并转换 category_id
    converted_annotations = []
    for ann in data['annotations']:
        if ann['image_id'] in loaded_image_ids:
            new_ann = ann.copy()
            old_cat_id = ann['category_id']
            new_ann['category_id'] = category_id_mapping.get(old_cat_id, old_cat_id + 1)
            converted_annotations.append(new_ann)
    
    converted_data['images'] = converted_images
    converted_data['annotations'] = converted_annotations
    converted_data['categories'] = converted_categories
    
    logger.info(f"   已转换 {len(converted_images)} 个图片路径")
    logger.info(f"   包含 {len(converted_annotations)} 个标注")
    logger.info(f"   类别数: {len(converted_categories)}")
    logger.info(f"   类别ID映射: {category_id_mapping}")
    if converted_images:
        logger.info(f"   示例路径: {converted_images[0]['file_name']}")
    else:
        logger.error(f"   ❌ 没有匹配到任何图片！请检查路径转换逻辑")
    
    # 调试：打印第一个标注和类别信息
    if converted_annotations:
        logger.info(f"   示例标注: image_id={converted_annotations[0]['image_id']}, category_id={converted_annotations[0]['category_id']}")
    if converted_categories:
        logger.info(f"   类别列表: {[cat['name'] for cat in converted_categories]}")
    
    try:
        client.upload_annotations(task_id, converted_data)
        logger.info(f"✅ 标注上传请求已提交")
        
        # 等待标注处理完成 - 39,000+ 个标注需要时间
        logger.info(f"\n⏳ 等待标注导入完成...")
        logger.info(f"   提示: 39,000+ 个标注预计需要 5-10 分钟")
        logger.info(f"   正在处理中，请耐心等待...")
        
        # 等待更长时间
        for i in range(20):  # 最多等待 10 分钟（每次 30 秒）
            time.sleep(30)
            annotation_status = client.check_import_status(task_id, wait_time=0)
            
            if annotation_status:
                results = annotation_status.get('results', [])
                for req in results:
                    if 'import:annotations' in req.get('operation', ''):
                        status = req.get('status')
                        progress = req.get('progress', 0)
                        
                        if status == 'finished':
                            logger.info(f"✅ 标注导入完成")
                            break
                        elif status == 'failed':
                            logger.error(f"❌ 标注导入失败")
                            if req.get('message'):
                                logger.error(f"   错误: {req.get('message')[:500]}")
                            return
                        else:
                            logger.info(f"   进度: {progress}% - 状态: {status}")
                else:
                    continue
                break
        
        # 最终检查
        logger.info(f"\n🔍 最终检查标注导入状态...")
        annotation_status = client.check_import_status(task_id, wait_time=5)
        
        if annotation_status and annotation_status.get('has_errors'):
            logger.error(f"\n❌ 标注导入有错误！")
            logger.error(f"   常见原因:")
            logger.error(f"   1. 标注文件中的图片路径与实际加载的图片路径不匹配")
            logger.error(f"   2. 标注的category_id与任务的label不匹配")
            logger.error(f"   3. 标注格式不正确")
            return
        else:
            logger.info(f"✅ 标注导入检查完成")
        
    except Exception as e:
        logger.error(f"❌ 上传标注失败: {e}")
        return
    
    # 10. 完成 - 保存job和session的映射关系
    logger.info("\n" + "="*60)
    logger.info("✅ 导入完成！")
    logger.info("="*60)
    logger.info(f"任务ID: {task_id}")
    logger.info(f"任务名称: {task_name}")
    logger.info(f"Jobs数量: {len(job_file_mapping)}")
    logger.info(f"总图片数: {len(all_image_paths)}")
    logger.info(f"总标注数: {len(data['annotations'])}")
    logger.info(f"\n🔗 CVAT链接: {cvat_url}/tasks/{task_id}")
    logger.info(f"\n📝 日志文件: {log_file}")
    
    # 保存job和session的映射关系
    mapping_file = log_dir / f'job_session_mapping_{task_id}.json'
    
    # 获取实际的job列表
    jobs_response = client.check_task_jobs(task_id)
    if jobs_response:
        job_list = jobs_response.get('results', [])
        job_list.sort(key=lambda x: x.get('start_frame', 0))
        
        mapping = []
        for idx, job in enumerate(job_list):
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
        logger.info(f"\n前5个映射:")
        for item in mapping[:5]:
            logger.info(f"   Job {item['job_id']}: {item['session_id']} ({item['frame_count']} 帧)")


def main():
    """命令行入口"""
    auto_import_to_cvat()


if __name__ == "__main__":
    main()
