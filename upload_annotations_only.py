#!/usr/bin/env python3
"""
单独上传标注到已存在的CVAT任务
"""
import requests
import json
import zipfile
import io
import logging
from pathlib import Path
from datetime import datetime

# 配置日志
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f'upload_annotations_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def upload_annotations(cvat_url, api_key, task_id, annotation_data):
    """上传标注到指定任务"""
    url = f'{cvat_url}/api/tasks/{task_id}/annotations'
    params = {'format': 'COCO 1.0'}
    
    # 创建内存中的zip文件
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        json_str = json.dumps(annotation_data, ensure_ascii=False, indent=2)
        zipf.writestr('annotations/instances_default.json', json_str)
    
    zip_buffer.seek(0)
    
    headers = {'Authorization': f'Token {api_key}'}
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
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ 上传标注失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"   响应内容: {e.response.text}")
        return False


def main():
    """主函数"""
    logger.info("="*60)
    logger.info("单独上传标注到CVAT任务")
    logger.info("="*60)
    
    # 1. 加载配置
    logger.info("📖 加载配置...")
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    cvat_url = config['cvat']['url'].rstrip('/')
    api_key = config['cvat']['api_key']
    input_json = config['files']['humansignal_json']
    
    # 2. 输入任务ID
    task_id = input("请输入任务ID: ").strip()
    if not task_id:
        logger.error("❌ 任务ID不能为空")
        return
    
    logger.info(f"目标任务: {task_id}")
    
    # 3. 读取标注数据
    logger.info(f"📖 读取标注数据: {input_json}")
    with open(input_json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    logger.info(f"   总图片数: {len(data['images'])}")
    logger.info(f"   总标注数: {len(data['annotations'])}")
    logger.info(f"   类别数: {len(data['categories'])}")
    
    # 4. 转换图片路径
    logger.info("🔄 转换图片路径...")
    converted_images = []
    
    for img in data['images']:
        original_path = img['file_name']
        
        # 转换路径
        basename = original_path.split('/')[-1]
        if '__' in basename:
            basename = basename.split('__', 1)[1]
        
        # 添加 prefix 前缀
        new_path = f"test_1000/images/{basename}"
        
        # 创建新的image对象
        new_img = img.copy()
        new_img['file_name'] = new_path
        converted_images.append(new_img)
    
    logger.info(f"   已转换 {len(converted_images)} 个图片路径")
    
    # 5. 确保 categories 格式正确（CVAT 需要 category_id 从 1 开始）
    logger.info("🏷️  处理类别信息...")
    # 按 category ID 排序，确保顺序一致
    categories_sorted = sorted(data['categories'], key=lambda x: x['id'])
    converted_categories = []
    category_id_mapping = {}  # 旧ID -> 新ID
    
    for idx, cat in enumerate(categories_sorted):
        new_id = idx + 1  # 从 1 开始
        category_id_mapping[cat['id']] = new_id
        converted_cat = {
            'id': new_id,
            'name': cat['name'],
            'supercategory': cat.get('supercategory', '')
        }
        converted_categories.append(converted_cat)
    
    logger.info(f"   类别列表: {[cat['name'] for cat in converted_categories]}")
    logger.info(f"   类别ID映射: {category_id_mapping}")
    
    # 转换标注中的 category_id
    converted_annotations = []
    for ann in data['annotations']:
        new_ann = ann.copy()
        old_cat_id = ann['category_id']
        new_ann['category_id'] = category_id_mapping.get(old_cat_id, old_cat_id + 1)
        converted_annotations.append(new_ann)
    
    # 6. 构建最终数据
    converted_data = {
        'images': converted_images,
        'annotations': converted_annotations,
        'categories': converted_categories
    }
    
    logger.info(f"\n📊 准备上传:")
    logger.info(f"   图片: {len(converted_images)}")
    logger.info(f"   标注: {len(converted_annotations)}")
    logger.info(f"   类别: {len(converted_categories)}")
    
    # 7. 确认上传
    confirm = input("\n确认上传？(yes/no): ").strip().lower()
    if confirm != 'yes':
        logger.info("❌ 取消上传")
        return
    
    # 8. 上传标注
    logger.info("\n📤 开始上传标注...")
    success = upload_annotations(cvat_url, api_key, task_id, converted_data)
    
    if success:
        logger.info("\n" + "="*60)
        logger.info("✅ 上传完成！")
        logger.info("="*60)
        logger.info(f"🔗 查看任务: {cvat_url}/tasks/{task_id}")
        logger.info(f"📝 日志文件: {log_file}")
    else:
        logger.error("\n❌ 上传失败，请查看日志")


if __name__ == "__main__":
    main()
