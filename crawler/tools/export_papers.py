#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
论文数据导出工具
模仿 paperagent (2) 的导出逻辑，支持多种格式导出
"""

import argparse
import logging
import sys
import os
from datetime import datetime

# 添加父目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import UnifiedDB

def main():
    """主函数"""
    # 确保日志目录存在
    os.makedirs("exports/logs", exist_ok=True)
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("exports/logs/export_papers.log"),
            logging.StreamHandler()
        ]
    )
    
    # 解析命令行参数 - 支持直接参数格式
    parser = argparse.ArgumentParser(description='统一学术期刊数据库导出工具')
    
    # 支持两种用法：
    # 1. 子命令格式: python export_papers.py export --journal nature --format csv
    # 2. 直接参数格式: python export_papers.py --journal nature --format csv
    
    # 首先尝试检测是否使用了子命令格式
    if len(sys.argv) > 1 and sys.argv[1] in ['export', 'quick']:
        # 子命令格式
        subparsers = parser.add_subparsers(dest='command', help='命令')
        
        # 导出命令
        export_parser = subparsers.add_parser('export', help='导出论文数据')
        export_parser.add_argument('--journal', '-j', type=str, choices=['nature', 'science', 'cell', 'plos'], 
                                   required=True, help='期刊类型')
        export_parser.add_argument('--start-date', '-s', type=str, help='开始日期 (YYYY-MM-DD)')
        export_parser.add_argument('--end-date', '-e', type=str, help='结束日期 (YYYY-MM-DD)')
        export_parser.add_argument('--format', '-f', choices=['json', 'csv', 'markdown', 'xlsx'], default='csv', 
                                   help='输出格式 (默认: csv)')
        export_parser.add_argument('--output', '-o', type=str, help='输出文件路径')
        
        # 快速导出命令
        quick_parser = subparsers.add_parser('quick', help='快速导出最近论文')
        quick_parser.add_argument('--journal', '-j', type=str, choices=['nature', 'science', 'cell', 'plos'], 
                                  required=True, help='期刊类型')
        quick_parser.add_argument('--days', '-d', type=int, default=7, help='最近天数 (默认: 7天)')
        quick_parser.add_argument('--format', '-f', choices=['csv', 'xlsx'], default='xlsx', 
                                  help='输出格式 (默认: xlsx)')
        
        args = parser.parse_args()
        
        if not args.command:
            parser.print_help()
            return
            
    else:
        # 直接参数格式 - 简化的主要用法
        parser.add_argument('--journal', '-j', type=str, choices=['nature', 'science', 'cell', 'plos'], 
                           required=True, help='期刊类型')
        parser.add_argument('--start-date', '-s', type=str, help='开始日期 (YYYY-MM-DD)')
        parser.add_argument('--end-date', '-e', type=str, help='结束日期 (YYYY-MM-DD)')
        parser.add_argument('--format', '-f', choices=['json', 'csv', 'markdown', 'xlsx'], default='csv', 
                           help='输出格式 (默认: csv)')
        parser.add_argument('--output', '-o', type=str, help='输出文件路径')
        parser.add_argument('--days', '-d', type=int, help='最近天数（如果不指定日期范围则使用此参数）')
        parser.add_argument('--quick', action='store_true', help='快速导出模式')
        
        args = parser.parse_args()
        
        # 默认为导出模式
        if not hasattr(args, 'command'):
            if args.quick or (args.days and not args.start_date and not args.end_date):
                args.command = 'quick'
                if not args.days:
                    args.days = 7
            else:
                args.command = 'export'
    
    # 处理导出命令
    if args.command == 'export':
        db = UnifiedDB(args.journal)
        
        try:
            # 显示数据库基本信息
            total_count = db.get_paper_count()
            print(f"数据库中共有 {args.journal.upper()} 论文: {total_count} 篇")
            
            # 如果没有指定日期范围，默认导出所有数据
            if not args.start_date and not args.end_date:
                print("未指定日期范围，将导出所有数据")
                print("提示：使用 --start-date 和 --end-date 参数可指定特定日期范围")
            
            success, result = db.export_papers_after_date(
                start_date=args.start_date,
                end_date=args.end_date,
                output_format=args.format,
                output_file=args.output
            )
            
            if success:
                print(f"导出成功: {result}")
                
                # 显示导出的文件信息
                if os.path.exists(result):
                    file_size = os.path.getsize(result) / 1024  # KB
                    print(f"文件大小: {file_size:.1f} KB")
            else:
                print(f"导出失败: {result}")
                
        except Exception as e:
            print(f"导出过程中发生错误: {e}")
        finally:
            db.close()
    
    # 处理快速导出命令
    elif args.command == 'quick':
        from datetime import timedelta
        
        db = UnifiedDB(args.journal)
        
        try:
            # 计算时间范围
            end_date = datetime.now()
            start_date = end_date - timedelta(days=args.days)
            
            # 生成文件名和目录
            date_range = f"{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}"
            
            # 根据格式选择目录
            if args.format == 'csv':
                output_dir = "exports/csv"
            elif args.format == 'xlsx':
                output_dir = "exports/excel"
            else:
                output_dir = "exports/reports"
            
            # 确保目录存在
            os.makedirs(output_dir, exist_ok=True)
            
            output_file = f"{output_dir}/recent_papers_{args.journal}_{date_range}.{args.format}"
            
            print(f"导出时间范围: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}")
            print(f"输出文件: {output_file}")
            
            success, result = db.export_papers_after_date(
                start_date=start_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d'),
                output_format=args.format,
                output_file=output_file
            )
            
            if success:
                print(f"快速导出成功: {result}")
                
                # 如果是Excel格式，额外生成output.csv兼容文件
                if args.format == 'xlsx':
                    csv_file = f"exports/csv/output_{args.journal}_{date_range}.csv"
                    success_csv, result_csv = db.export_papers_after_date(
                        start_date=start_date.strftime('%Y-%m-%d'),
                        end_date=end_date.strftime('%Y-%m-%d'),
                        output_format='csv',
                        output_file=csv_file
                    )
                    if success_csv:
                        print(f"同时生成CSV文件: {result_csv}")
            else:
                print(f"快速导出失败: {result}")
                
        except Exception as e:
            print(f"快速导出过程中发生错误: {e}")
        finally:
            db.close()

if __name__ == "__main__":
    main()