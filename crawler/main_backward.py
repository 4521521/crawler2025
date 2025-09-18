#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于main_back.py的定时增量爬虫
"""

import argparse
import logging
import sys
import os
import json
import yaml
import schedule
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup

# 导入原有模块
from db import UnifiedDB
from agent import PaperAgent
from parser import create_parser

# 确保日志目录存在
import os
os.makedirs("exports/logs", exist_ok=True)

# 配置日志

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("exports/logs/main_back_timed.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ConfigManager:
    """统一爬虫配置管理"""
    
    def __init__(self):
        self.config = self.load_config()
    
    def load_config(self):
        """加载配置"""
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def get_journal_list(self, journal):
        """获取期刊列表（支持动态文件回退到静态文件）"""
        journal_file = self.config["JOURNALS_PATH_" + journal.upper()]
        journal_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), journal_file)
        
        try:
            with open(journal_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            # 动态文件读取失败，回退到静态文件
            if 'dynamic' in journal_file:
                static_file = journal_file.replace('_dynamic', '')
                static_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), static_file)
                logger.warning("动态期刊文件读取失败: " + str(e) + "，回退到静态文件: " + static_file)
                try:
                    with open(static_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception as fallback_e:
                    logger.error("静态文件也读取失败: " + str(fallback_e))
                    raise
            else:
                raise

class CrawlerSystemTimed:
    """基于main_back.py的定时爬虫系统"""
    
    def __init__(self, journals, schedule_time="08:00", schedule_day="monday", initial_start_date=None, initial_end_date=None):
        self.journals = journals
        self.schedule_time = schedule_time
        self.schedule_day = schedule_day
        self.initial_start_date = initial_start_date
        self.initial_end_date = initial_end_date
        self.first_run = True
        self.config_manager = ConfigManager()
        self.parsers = {}
        self.databases = {}
        self.agents = {}
        self.all_ai_papers_with_reason = []
        self.running = True
        
        logger.info("="*60)
        logger.info("定时增量爬虫系统启动")
        logger.info("目标期刊: " + ', '.join(journals))
        logger.info("定时设置: 每周" + schedule_day + " " + schedule_time)
        if initial_start_date and initial_end_date:
            logger.info("第一次爬取范围: " + str(initial_start_date) + " 到 " + str(initial_end_date))
        logger.info("="*60)
    
    def initialize_journal(self, journal_name):
        """初始化期刊组件"""
        self.databases[journal_name] = UnifiedDB(journal_name)
        self.agents[journal_name] = PaperAgent(logger=logger)
        self.parsers[journal_name] = create_parser(journal_name, self.databases[journal_name], self.agents[journal_name])
        logger.info(f"{journal_name.upper()}期刊组件初始化完成")
    
    def run_incremental_crawl(self):
        """执行增量爬取 - 完全基于main_back.py逻辑"""
        execution_start = datetime.now()
        logger.info("="*60)
        logger.info(f"开始执行定时增量爬取")
        logger.info("执行时间: " + execution_start.strftime('%Y-%m-%d %H:%M:%S'))
        logger.info("目标期刊: " + ', '.join(self.journals))
        logger.info("="*60)
        
        # 重置收集器
        self.all_ai_papers_with_reason = []
        results = {}
        journal_stats = {
            'total_subjournals': 0,
            'success_subjournals': 0,
            'failed_subjournals': 0,
            'failed_subjournal_names': []
        }
        
        for journal in self.journals:
            try:
                logger.info(f"初始化{journal.upper()}期刊组件...")
                self.initialize_journal(journal)
                
                # 获取期刊列表
                journal_list = self.config_manager.get_journal_list(journal)
                if not journal_list:
                    logger.warning(f"{journal}期刊列表为空")
                    continue
                
                db = self.databases[journal]
                parser = self.parsers[journal]
                agent = self.agents[journal]
                
                # 爬取数据
                total_papers = 0
                total_saved = 0
                subjournal_success = 0
                subjournal_failed = 0
                failed_subjournal_names = []
                
                # 按子刊分别获取时间范围并爬取（智能时间检测）
                for journal_info in journal_list:
                    journal_name = journal_info['name']
                    journal_stats['total_subjournals'] += 1
                    
                    try:
                        # 智能时间检测：为每个子刊获取最新时间
                        if self.first_run and self.initial_start_date and self.initial_end_date:
                            # 第一次运行使用用户指定的时间范围
                            start_date = self.initial_start_date
                            end_date = self.initial_end_date
                            logger.info(journal.upper() + "-" + journal_name + ": 第一次爬取，使用指定范围 " + start_date.strftime('%Y-%m-%d') + " -> " + end_date.strftime('%Y-%m-%d'))
                        else:
                            # 后续运行使用智能时间检测
                            start_date = db.get_last_update_time(journal_name=journal_name)
                            end_date = datetime.now()
                            logger.info(f"{journal.upper()}-{journal_name}: 从{start_date.strftime('%Y-%m-%d')}开始爬取")
                        
                        logger.info(journal.upper() + "-" + journal_name + ": 开始增量爬取 " + start_date.strftime('%Y-%m-%d') + " -> " + end_date.strftime('%Y-%m-%d'))
                        
                        # 爬取该子刊数据
                        papers = parser.scrape_journal(
                            journal_name=journal_name,
                            base_url=journal_info.get('link', journal_info.get('url', '')),
                            start_date=start_date,
                            end_date=end_date
                        )
                        
                        # 如果没有抛出异常，视为成功
                        subjournal_success += 1
                        journal_stats['success_subjournals'] += 1
                        
                        # 初始化变量
                        card_infos = []
                        
                        if papers:
                            logger.info(f"{journal.upper()}-{journal_name}: 抓取到{len(papers)}篇论文，开始AI分析")
                            
                            # 完全复用main_back.py的AI分析逻辑
                            for paper in papers:
                                card_infos.append({
                                'title': paper.get('title', ''),
                                'abstract': paper.get('abstract', ''),
                                'date': paper.get('date'),
                                'doi': paper.get('doi', ''),
                                'link': paper.get('url', ''),
                                'url': paper.get('url', ''),   # 保持url字段用于数据库保存
                                'authors': paper.get('authors', ''),
                                'type': 'incremental'
                            })
                        
                        ai_papers = []
                        non_ai_papers = []
                        
                        if card_infos:
                            # 为每个item添加id
                            for i, item in enumerate(card_infos, start=1):
                                item['id'] = str(i)
                            logger.info(f"{journal.upper()}-{journal_name}: 开始三重验证AI分析 {len(card_infos)} 篇文章")

                            contents = [{"id":item['id'], "title": item['title'], "abstract": item['abstract']} for item in card_infos]
                            result1 = agent.batch_analyze_papers_in_batches_concurrent(contents, batch_size=10)
                            
                            # 两次AI分析之间添加延迟，避免API限流
                            import time
                            import random
                            delay = random.uniform(1, 3)  # 2-5秒随机延迟
                            # logger.info(f"第一轮AI分析完成，等待 {delay:.1f} 秒后进行第二轮分析...")
                            time.sleep(delay)
                            
                            result2 = agent.batch_analyze_papers_in_batches_concurrent(contents, batch_size=10)
                            
                            # 转成字典方便快速查找
                            r1_map = {res['id']: res for res in result1}
                            r2_map = {res['id']: res for res in result2}

                            for item in card_infos:
                                rid = item['id']
                                r1 = r1_map.get(rid)
                                r2 = r2_map.get(rid)

                                if not r1 or not r2:
                                    continue

                                if r1['is_ai_related'] and r2['is_ai_related']:
                                    item['reason'] = r1['explanation']
                                    ai_papers.append(item)
                                elif not r1['is_ai_related'] and not r2['is_ai_related']:
                                    item['reason'] = r1['explanation']
                                    non_ai_papers.append(item)
                                else:
                                    review = agent.analyze_paper(item['title'], item['abstract'])
                                    item['reason'] = review.get('explanation', 'reviewed')
                                    if review['is_ai_related']:
                                        ai_papers.append(item)
                                    else:
                                        non_ai_papers.append(item)

                            logger.info("AI相关论文数: " + str(len(ai_papers)) + "，非AI: " + str(len(non_ai_papers)))
                            
                            # 按发表时间排序（最早的优先保存）
                            ai_papers.sort(key=lambda x: x.get('date', datetime.now().date()))
                            
                            # 收集AI相关论文（包含reason）用于CSV导出
                            self.all_ai_papers_with_reason.extend(ai_papers)
                            
                            # 保存AI论文到数据库（数据库有重复检查）
                            saved_count = 0
                            for paper in ai_papers:
                                if db.save_paper(paper, journal_name):
                                    saved_count += 1
                            
                            # 保存非AI论文到JSON文件
                            if non_ai_papers:
                                self._save_non_ai_papers_to_json(journal, non_ai_papers, start_date, end_date)
                            
                            total_papers += len(papers)
                            total_saved += saved_count
                            
                            logger.info(f"{journal.upper()} {journal_name}: 抓取{len(papers)}篇，AI相关{len(ai_papers)}篇，新增{saved_count}篇")
                        else:
                            logger.info(f"{journal.upper()} {journal_name}: 未获取到新论文")
                    
                    except Exception as e:
                        logger.error(journal.upper() + "-" + journal_name + ": 子刊爬取失败 - " + str(e))
                        subjournal_failed += 1
                        journal_stats['failed_subjournals'] += 1
                        failed_subjournal_names.append(journal.upper() + "-" + journal_name)
                        journal_stats['failed_subjournal_names'].append(journal.upper() + "-" + journal_name)
                
                results[journal] = {
                    "total_papers": total_papers, 
                    "total_saved": total_saved,
                    "subjournal_success": subjournal_success,
                    "subjournal_failed": subjournal_failed,
                    "failed_subjournal_names": failed_subjournal_names
                }
                
            except Exception as e:
                logger.error(journal.upper() + "期刊增量爬取失败: " + str(e))
                results[journal] = {"error": str(e)}
        
        self.print_summary(results, "增量爬取", execution_start, journal_stats)
        
        # 导出最近AI相关论文的CSV
        if hasattr(self, 'all_ai_papers_with_reason') and self.all_ai_papers_with_reason:
            self._export_ai_papers()
        
        # 标记第一次运行完成
        if self.first_run:
            self.first_run = False
            logger.info("第一次运行完成，后续将使用智能时间检测")
        
        # 计算下次执行时间
        next_run = schedule.next_run()
        if next_run:
            logger.info("下次执行时间: " + next_run.strftime('%Y-%m-%d %H:%M:%S'))
        
        logger.info("任务完成，等待下次定时执行...")
        return results
    
    def _save_non_ai_papers_to_json(self, journal, non_ai_papers, start_date, end_date):
        """保存非AI论文到JSON文件"""
        try:
            os.makedirs("exports/json/backward", exist_ok=True)
            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')
            json_file = f"exports/json/backward/no_ai_{journal}_{start_str}_{end_str}.json"
            
            papers_to_save = []
            for paper in non_ai_papers:
                paper_data = {
                    'title': paper.get('title', ''),
                    'abstract': paper.get('abstract', ''),
                    'date': paper.get('date').strftime('%Y-%m-%d') if hasattr(paper.get('date'), 'strftime') else str(paper.get('date', '')),
                    'doi': paper.get('doi', ''),
                    'link': paper.get('url', ''),
                    'authors': paper.get('authors', ''),
                    'type': paper.get('type', 'incremental')
                }
                papers_to_save.append(paper_data)
            
            existing_papers = []
            if os.path.exists(json_file):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        existing_papers = json.load(f)
                except Exception as e:
                    logger.warning("读取现有" + json_file + "文件失败: " + str(e))
            
            existing_dois = {paper.get('doi') for paper in existing_papers if paper.get('doi')}
            for paper in papers_to_save:
                if paper.get('doi') and paper['doi'] not in existing_dois:
                    existing_papers.append(paper)
                    existing_dois.add(paper['doi'])
            
            existing_papers.sort(key=lambda x: x.get('date', ''), reverse=True)
            
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(existing_papers, f, ensure_ascii=False, indent=2)
            
            logger.info("保存" + str(len(papers_to_save)) + "篇非AI论文到 " + json_file)
            
        except Exception as e:
            logger.error("保存非AI论文到JSON失败: " + str(e))
    
    def _export_ai_papers(self):
        """导出AI相关论文"""
        try:
            os.makedirs("exports/reports", exist_ok=True)
            
            if self.all_ai_papers_with_reason:
                dates = []
                for paper in self.all_ai_papers_with_reason:
                    if 'date' in paper:
                        paper_date = paper['date']
                        if hasattr(paper_date, 'date'):
                            dates.append(paper_date.date())
                        else:
                            dates.append(paper_date)
                
                if dates:
                    start_date = min(dates).strftime('%Y-%m-%d')
                    end_date = max(dates).strftime('%Y-%m-%d')
                    csv_filename = f"ai_papers_{start_date}_{end_date}.csv"
                else:
                    current_date = datetime.now().strftime('%Y-%m-%d')
                    csv_filename = f"ai_papers_{current_date}.csv"
                
                logger.info(f"本次爬取共获得{len(self.all_ai_papers_with_reason)}篇AI相关论文")
                
        except Exception as e:
            logger.error("导出AI论文失败: " + str(e))
    
    def print_summary(self, results, mode, start_time, journal_stats=None):
        """打印总结"""
        duration = datetime.now() - start_time
        
        logger.info("="*60)
        logger.info(f"定时爬虫系统 - {mode}完成总结")
        logger.info(f"执行耗时: {duration.total_seconds():.1f}秒")
        
        # 显示时间范围信息
        if hasattr(self, 'initial_start_date') and hasattr(self, 'initial_end_date') and self.first_run:
            if self.initial_start_date and self.initial_end_date:
                logger.info("爬取时间范围: " + self.initial_start_date.strftime('%Y-%m-%d') + " 到 " + self.initial_end_date.strftime('%Y-%m-%d'))
        else:
            # 自动检测时间范围
            if hasattr(self, 'all_ai_papers_with_reason') and self.all_ai_papers_with_reason:
                dates = []
                for paper in self.all_ai_papers_with_reason:
                    if 'date' in paper:
                        paper_date = paper['date']
                        if hasattr(paper_date, 'date'):
                            dates.append(paper_date.date())
                        else:
                            dates.append(paper_date)
                if dates:
                    start_date = min(dates).strftime('%Y-%m-%d')
                    end_date = max(dates).strftime('%Y-%m-%d')
                    logger.info("实际获取论文时间范围: " + str(start_date) + " 到 " + str(end_date))
        
        logger.info("="*60)
        
        total_papers = 0
        total_saved = 0
        success_count = 0
        failed_journals = []
        
        for journal, result in results.items():
            if 'error' in result:
                failed_journals.append(journal)
                logger.info(journal.upper() + ": 爬取失败 - " + str(result['error']))
            else:
                papers = result.get('total_papers', 0)
                saved = result.get('total_saved', 0)
                logger.info(f"{journal.upper()}: 抓取 {papers} 篇文章，新增 {saved} 篇到数据库")
                total_papers += papers
                total_saved += saved
                success_count += 1
        
        logger.info("-"*60)
        logger.info(f"总计: 抓取 {total_papers} 篇文章，新增 {total_saved} 篇到数据库")
        
        # 使用子刊统计信息
        if journal_stats:
            success_subjournals = journal_stats.get('success_subjournals', 0)
            failed_subjournals = journal_stats.get('failed_subjournals', 0)
            logger.info(f"成功: {success_subjournals} 个子刊，失败: {failed_subjournals} 个子刊")
            
            failed_subjournal_names = journal_stats.get('failed_subjournal_names', [])
            if failed_subjournal_names:
                logger.info("失败子刊: " + ', '.join(failed_subjournal_names))
        else:
            # 回退到原来的期刊级别统计
            logger.info(f"成功: {success_count} 个期刊，失败: {len(failed_journals)} 个期刊")
            if failed_journals:
                logger.info("失败期刊: " + ', '.join(failed_journals))
        
        logger.info("="*60)
    
    def cleanup(self):
        """清理资源"""
        for journal, parser in self.parsers.items():
            if hasattr(parser, 'cleanup'):
                parser.cleanup()
        for journal, db in self.databases.items():
            if hasattr(db, 'close'):
                db.close()
    
    def start_daemon(self):
        """启动定时守护进程"""
        try:
            # 设置定时任务
            if self.schedule_day.lower() == 'daily':
                schedule.every().day.at(self.schedule_time).do(self.run_incremental_crawl)
                logger.info(f"设置定时任务: 每天{self.schedule_time}执行")
            else:
                getattr(schedule.every(), self.schedule_day.lower()).at(self.schedule_time).do(self.run_incremental_crawl)
                logger.info(f"设置定时任务: 每周{self.schedule_day} {self.schedule_time}执行")
            
            # 首次立即执行
            logger.info("定时守护进程启动，立即执行一次增量爬取...")
            self.run_incremental_crawl()
            
            # 显示下次运行时间
            next_run = schedule.next_run()
            if next_run:
                logger.info("下次运行时间: " + next_run.strftime('%Y-%m-%d %H:%M:%S'))
            
            # 进入守护循环
            logger.info("进入定时等待模式，守护进程将持续运行直到手动停止...")
            logger.info("提示: 可以使用 Ctrl+C 停止，或者 pkill -f main_backward.py 后台停止")
            
            while self.running:
                schedule.run_pending()
                time.sleep(60)  # 每分钟检查一次
                
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在关闭...")
            self.running = False
        except Exception as e:
            logger.error("守护进程运行异常: " + str(e))
            self.running = False
        finally:
            self.cleanup()
        
        logger.info("定时爬虫守护进程已停止")

def parse_journals(journals_str):
    """解析期刊参数"""
    if not journals_str:
        return []
    
    journals = [j.strip().lower() for j in journals_str.split(',')]
    valid_journals = ['nature', 'science', 'cell', 'plos']
    invalid = [j for j in journals if j not in valid_journals]
    
    if invalid:
        logger.error("不支持的期刊: " + ', '.join(invalid))
        logger.info("支持的期刊: " + ', '.join(valid_journals))
        return []
    
    return journals

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='定时增量爬虫（基于main_back.py）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 每周一8点执行指定期刊
  python main_backward.py -j nature,science,cell,plos
  
  # 每周一8点执行部分期刊
  python main_backward.py -j nature,science
  
  # 每周三10点执行
  python main_backward.py -j nature,science --day wednesday --time 10:00
  
  # 每天8点执行
  python main_backward.py -j nature --day daily --time 08:00
        """
    )
    
    parser.add_argument(
        '-j', '--journals',
        required=True,
        help='指定要爬取的期刊，支持: nature,science,cell,plos'
    )
    
    parser.add_argument(
        '--day',
        default='monday',
        help='执行日期，支持星期(monday-sunday)或daily表示每天（默认: monday）'
    )
    
    parser.add_argument(
        '--time',
        default='08:00',
        help='执行时间，格式HH:MM（默认: 08:00）'
    )
    
    parser.add_argument(
        '--start-date',
        help='第一次执行的开始日期，格式YYYY-MM-DD（默认: 7天前）'
    )
    
    parser.add_argument(
        '--end-date',
        help='第一次执行的结束日期，格式YYYY-MM-DD（默认: 今天）'
    )
    
    args = parser.parse_args()
    
    # 解析期刊参数
    journals = parse_journals(args.journals)
    if not journals:
        return 1
    
    # 验证时间格式
    try:
        datetime.strptime(args.time, '%H:%M')
    except ValueError:
        logger.error(f"时间格式错误: {args.time}，应该是 HH:MM 格式")
        return 1
    
    # 验证日期参数
    valid_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday', 'daily']
    if args.day.lower() not in valid_days:
        logger.error("日期参数错误: " + args.day + "，支持: " + ', '.join(valid_days))
        return 1
    
    # 解析用户指定的时间范围
    initial_start_date = None
    initial_end_date = None
    
    if args.start_date or args.end_date:
        try:
            if args.start_date:
                initial_start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
            else:
                initial_start_date = datetime.now() - timedelta(days=7)  # 默认7天前
            
            if args.end_date:
                initial_end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
            else:
                initial_end_date = datetime.now()  # 默认今天
            
            logger.info("用户指定第一次爬取时间范围: " + initial_start_date.strftime('%Y-%m-%d') + " 到 " + initial_end_date.strftime('%Y-%m-%d'))
            
        except ValueError as e:
            logger.error(f"日期格式错误: {e}，应该是 YYYY-MM-DD 格式")
            return 1
    
    # 创建并启动守护进程
    daemon = CrawlerSystemTimed(
        journals=journals,
        schedule_time=args.time,
        schedule_day=args.day,
        initial_start_date=initial_start_date,
        initial_end_date=initial_end_date
    )
    
    daemon.start_daemon()
    return 0

if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
