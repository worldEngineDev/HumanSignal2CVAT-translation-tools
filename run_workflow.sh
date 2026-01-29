#!/bin/bash
# CVAT 工作流程脚本

set -e

# 使用虚拟环境的 Python
PYTHON=".venv/bin/python"

# 检查虚拟环境
if [ ! -f "$PYTHON" ]; then
    echo "❌ 虚拟环境不存在: .venv"
    echo "💡 请先创建虚拟环境: python3 -m venv .venv"
    echo "💡 然后安装依赖: .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 列出所有任务
list_tasks() {
    $PYTHON -c "
import json
import requests

with open('config.json') as f:
    config = json.load(f)

url = config['cvat']['url'].rstrip('/') + '/api/tasks'
headers = {'Authorization': 'Token ' + config['cvat']['api_key']}
params = {'page_size': 100, 'org': config.get('organization', {}).get('slug', '')}

try:
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    tasks = resp.json().get('results', [])
    
    # 排除旧平台任务
    tasks = [t for t in tasks if t['id'] != 1967925]
    
    print('\\n📋 任务列表:')
    print('-' * 60)
    for t in sorted(tasks, key=lambda x: x['id'], reverse=True):
        status = t.get('status', '')
        size = t.get('size', 0)
        print(f\"  {t['id']}  {t['name'][:40]:<40}  [{size}张]\")
    print('-' * 60)
except Exception as e:
    print(f'获取任务列表失败: {e}')
"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# 显示菜单
show_menu() {
    echo ""
    echo "=========================================="
    echo "  CVAT 工作流程"
    echo "=========================================="
    echo ""
    echo "【数据管理】"
    echo "  1. 从旧平台迁移数据（HumanSignal → CVAT）"
    echo "  2. 核对云存储和标注状态"
    echo "  3. 从云存储导入新数据"
    echo ""
    echo "【进度监控】"
    echo "  4. 检查标注人员完成情况"
    echo "  5. 检查每日绩效（速度统计）"
    echo "  6. 查看最新报告"
    echo ""
    echo "【人员管理】"
    echo "  7. 刷新标注人员列表"
    echo "  8. 动态分配未开始的Jobs"
    echo ""
    echo "  0. 退出"
    echo ""
    echo -n "请选择操作 [0-8]: "
}

# 1. 从旧平台迁移
migrate_from_old() {
    print_info "从旧平台（HumanSignal）迁移数据到 CVAT..."
    echo ""
    
    # 检查数据文件
    data_file=$(cat config.json | grep -o '"humansignal_json"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
    
    if [ -z "$data_file" ]; then
        print_error "config.json 中未配置 humansignal_json 路径"
        return 1
    fi
    
    if [ ! -f "$data_file" ]; then
        print_error "数据文件不存在: $data_file"
        echo -n "请输入 HumanSignal 导出的 JSON 文件路径: "
        read input_file
        if [ -f "$input_file" ]; then
            cp "$input_file" "$data_file"
            print_success "数据文件已复制"
        else
            print_error "文件不存在: $input_file"
            return 1
        fi
    fi
    
    print_info "数据文件: $data_file"
    echo -n "确认开始迁移？(y/n): "
    read confirm
    if [ "$confirm" != "y" ]; then
        print_warning "取消迁移"
        return 0
    fi
    
    $PYTHON cvat_auto_import.py
    if [ $? -eq 0 ]; then
        print_success "迁移完成"
    else
        print_error "迁移失败，请查看日志"
    fi
}

# 2. 核对云存储和标注状态
check_status() {
    print_info "核对云存储和 CVAT 标注状态..."
    echo ""
    echo "选择检查范围:"
    echo "1. 检查所有任务"
    echo "2. 检查指定任务"
    echo -n "请选择 [1-2]: "
    read choice
    
    if [ "$choice" = "2" ]; then
        list_tasks
        echo -n "请输入任务ID（多个ID用空格分隔）: "
        read task_ids
        $PYTHON check_annotation_status.py $task_ids
    else
        $PYTHON check_annotation_status.py
    fi
    
    if [ $? -eq 0 ]; then
        print_success "状态核对完成"
        
        # 显示摘要
        latest_report=$(ls -t logs/annotation_status_*.json 2>/dev/null | head -1)
        if [ -n "$latest_report" ]; then
            echo ""
            print_info "最新状态报告: $latest_report"
            echo ""
            $PYTHON -c "import json; data=json.load(open('$latest_report')); summary=data.get('summary',{}); print('📊 统计:'); [print(f'   {k}: {v}') for k,v in summary.items()]"
        fi
    else
        print_error "状态核对失败"
    fi
}

# 3. 检查标注人员完成情况
check_progress() {
    print_info "检查标注人员完成情况..."
    echo ""
    echo "选择检查范围:"
    echo "1. 检查所有任务"
    echo "2. 检查指定任务"
    echo -n "请选择 [1-2]: "
    read choice
    
    if [ "$choice" = "2" ]; then
        list_tasks
        echo -n "请输入任务ID（多个ID用空格分隔）: "
        read task_ids
        $PYTHON check_progress.py $task_ids
    else
        $PYTHON check_progress.py
    fi
    
    if [ $? -eq 0 ]; then
        print_success "进度检查完成"
        
        # 显示最新的每日报告
        latest_daily=$(ls -t logs/daily_report_*.txt 2>/dev/null | head -1)
        if [ -n "$latest_daily" ]; then
            echo ""
            print_info "最新每日报告: $latest_daily"
            echo ""
            cat "$latest_daily"
        fi
    else
        print_error "进度检查失败"
    fi
}

# 4. 从云存储导入新数据
import_new_data() {
    print_info "从云存储导入新数据..."
    echo ""
    
    # 检查是否有新数据文件
    latest_new_images=$(ls -t logs/new_images_*.txt 2>/dev/null | head -1)
    if [ -z "$latest_new_images" ]; then
        print_warning "未找到新数据文件列表"
        print_info "请先运行 '核对云存储和标注状态' 生成新数据列表"
        return 1
    fi
    
    print_info "使用新数据文件: $latest_new_images"
    
    # 显示新数据数量
    new_count=$(wc -l < "$latest_new_images")
    print_info "新数据数量: $new_count 个文件"
    
    if [ "$new_count" -eq 0 ]; then
        print_success "没有新数据需要导入"
        return 0
    fi
    
    echo -n "确认导入并自动分配给标注人员？(y/n): "
    read confirm
    if [ "$confirm" != "y" ]; then
        print_warning "取消导入"
        return 0
    fi
    
    $PYTHON import_new_data.py "$latest_new_images"
    if [ $? -eq 0 ]; then
        print_success "新数据导入完成"
    else
        print_error "导入失败，请查看日志"
    fi
}

# 5. 列出标注人员
list_annotators() {
    print_info "获取组织成员并更新配置..."
    $PYTHON list_annotators.py
    
    if [ $? -eq 0 ]; then
        print_success "标注人员列表已更新到 config.json"
    else
        print_error "获取标注人员列表失败"
    fi
}

# 7. 检查每日绩效
check_daily_performance() {
    print_info "检查标注人员每日绩效..."
    echo ""
    
    $PYTHON check_daily_performance.py
    
    if [ $? -eq 0 ]; then
        print_success "绩效检查完成"
        
        # 显示CSV位置
        latest_csv=$(ls -t reports/daily_performance_*.csv 2>/dev/null | head -1)
        if [ -n "$latest_csv" ]; then
            print_info "CSV报告: $latest_csv"
        fi
    else
        print_error "绩效检查失败，请查看日志"
    fi
}

# 8. 动态分配未开始的Jobs
reassign_jobs() {
    print_info "动态分配未开始的Jobs..."
    echo ""
    echo "选择处理范围:"
    echo "1. 处理所有任务"
    echo "2. 处理指定任务"
    echo -n "请选择 [1-2]: "
    read choice
    
    if [ "$choice" = "2" ]; then
        list_tasks
        echo -n "请输入任务ID（多个ID用空格分隔）: "
        read task_ids
        $PYTHON reassign_jobs.py $task_ids
    else
        $PYTHON reassign_jobs.py
    fi
    
    if [ $? -eq 0 ]; then
        print_success "分配完成"
    else
        print_error "分配失败，请查看日志"
    fi
}

# 6. 查看最新报告
view_reports() {
    echo ""
    echo "=========================================="
    echo "  查看报告"
    echo "=========================================="
    echo ""
    echo "1. 标注状态报告"
    echo "2. 人员进度报告"
    echo "3. 查看日志文件"
    echo "0. 返回"
    echo ""
    echo -n "请选择 [0-3]: "
    read choice
    
    case $choice in
        1)
            latest_report=$(ls -t logs/annotation_status_*.json 2>/dev/null | head -1)
            if [ -z "$latest_report" ]; then
                print_warning "未找到状态报告"
                return 1
            fi
            print_info "最新状态报告: $latest_report"
            echo ""
            $PYTHON -m json.tool "$latest_report"
            ;;
        2)
            latest_daily=$(ls -t logs/daily_report_*.txt 2>/dev/null | head -1)
            if [ -z "$latest_daily" ]; then
                print_warning "未找到进度报告"
                return 1
            fi
            print_info "最新进度报告: $latest_daily"
            echo ""
            cat "$latest_daily"
            ;;
        3)
            echo ""
            echo "最近的日志文件:"
            echo ""
            ls -lt logs/*.log 2>/dev/null | head -10 | nl
            echo ""
            echo -n "请输入要查看的日志编号或按回车返回: "
            read log_num
            if [ -n "$log_num" ]; then
                log_file=$(ls -t logs/*.log 2>/dev/null | sed -n "${log_num}p")
                if [ -n "$log_file" ]; then
                    print_info "查看日志: $log_file"
                    echo ""
                    tail -100 "$log_file"
                fi
            fi
            ;;
        0)
            return 0
            ;;
        *)
            print_error "无效的选择"
            ;;
    esac
}

# 主循环
main() {
    # 检查配置文件
    if [ ! -f "config.json" ]; then
        print_error "配置文件不存在: config.json"
        print_info "请先创建配置文件: cp config.example.json config.json"
        exit 1
    fi
    
    while true; do
        show_menu
        read choice
        
        case $choice in
            1)
                migrate_from_old
                ;;
            2)
                check_status
                ;;
            3)
                import_new_data
                ;;
            4)
                check_progress
                ;;
            5)
                check_daily_performance
                ;;
            6)
                view_reports
                ;;
            7)
                list_annotators
                ;;
            8)
                reassign_jobs
                ;;
            0)
                print_info "退出"
                exit 0
                ;;
            *)
                print_error "无效的选择"
                ;;
        esac
        
        echo ""
        echo -n "按回车继续..."
        read
    done
}

# 运行主程序
main
