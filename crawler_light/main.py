#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一学术期刊爬虫系统 - 全量爬取
包含Nature、Science、Cell、PLOS四个期刊的完整爬虫逻辑
"""

import argparse
import logging
import sys
import os
import json
import yaml
from datetime import datetime, timedelta
from typing import List, Dict, Any
import requests
import time
import random
from bs4 import BeautifulSoup
import pandas as pd

# 确保Excel导出依赖可用
try:
    import openpyxl
except ImportError:
    print("警告: openpyxl未安装，Excel导出可能失败")

# 导入模块
# from db import UnifiedDB  # 轻量版不使用数据库
from agent import PaperAgent
from parser import create_parser

# 确保日志目录存在
os.makedirs("exports/logs", exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("exports/logs/crawler.log"),
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


class CrawlerSystem:
    """统一爬虫系统"""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.parsers = {}
        # self.databases = {}  # 轻量版不使用数据库
        self.agents = {}
    
    def initialize_journal(self, journal_name):
        """初始化期刊组件"""
        # 轻量版不使用数据库
        # 先创建PaperAgent
        self.agents[journal_name] = PaperAgent(logger=logger)
        # 然后使用PaperAgent创建parser
        self.parsers[journal_name] = create_parser(journal_name, self.agents[journal_name])
        logger.info(f"{journal_name.upper()}期刊组件初始化完成")
    
    def append_articles_to_file(self, articles, journal_type, category, start_date_str, end_date_str, export_format='xlsx'):
        """追加文章到文件（同一期刊的所有子刊数据保存在一个文件中）"""
        try:
            
            # 生成文件名（基于期刊类型和日期范围）
            filename = f"{journal_type}_papers_{category}_{start_date_str}_{end_date_str}.{export_format}"
            
            # 根据格式选择子目录
            if export_format == 'xlsx':
                subdir = 'excel'
            elif export_format == 'csv':
                subdir = 'csv'
            elif export_format == 'json':
                subdir = 'json'
            else:
                subdir = 'other'
            
            filepath = os.path.join("exports", subdir, filename)
            
            # 确保目录存在
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            # 检查文件是否已存在，如果存在则追加，否则创建新文件
            if os.path.exists(filepath):
                # 文件已存在，读取现有数据并追加
                if export_format == 'xlsx':
                    existing_df = pd.read_excel(filepath)
                    new_df = pd.DataFrame(articles)
                    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                    combined_df.to_excel(filepath, index=False, engine='openpyxl')
                elif export_format == 'csv':
                    existing_df = pd.read_csv(filepath, encoding='utf-8-sig')
                    new_df = pd.DataFrame(articles)
                    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                    combined_df.to_csv(filepath, index=False, encoding='utf-8-sig')
                elif export_format == 'json':
                    with open(filepath, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                    existing_data.extend(articles)
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(existing_data, f, ensure_ascii=False, indent=2, default=str)
            else:
                # 文件不存在，创建新文件
                if export_format == 'xlsx':
                    df = pd.DataFrame(articles)
                    df.to_excel(filepath, index=False, engine='openpyxl')
                elif export_format == 'csv':
                    df = pd.DataFrame(articles)
                    df.to_csv(filepath, index=False, encoding='utf-8-sig')
                elif export_format == 'json':
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(articles, f, ensure_ascii=False, indent=2, default=str)
            
            logger.info(f"追加 {len(articles)} 篇{category}文章到: {filepath}")
            
        except Exception as e:
            logger.error(f"追加文章失败: {e}")
    
    def run_full_crawl(self, journals, start_date_str, end_date_str, export_format='xlsx', target_subjournal=None):
        """执行全量爬取"""
        logger.info("="*60)
        logger.info("统一学术期刊爬虫系统 - 全量爬取模式")
        logger.info(f"目标期刊: {', '.join(journals)}")
        logger.info(f"爬取时间范围: {start_date_str} 至 {end_date_str}")
        logger.info(f"导出格式: {export_format}")
        if target_subjournal:
            logger.info(f"目标子刊: {target_subjournal}")
        logger.info("="*60)
        
        results = {}
        
        for journal in journals:
            try:
                logger.info(f"初始化{journal.upper()}期刊组件...")
                self.initialize_journal(journal)
                
                # 获取期刊列表
                journal_list = self.config_manager.get_journal_list(journal)
                if not journal_list:
                    logger.warning(f"{journal}期刊列表为空")
                    continue
            
                # 如果指定了子刊，过滤期刊列表
                if target_subjournal:
                    original_count = len(journal_list)
                    original_list = journal_list.copy()
                    journal_list = [j for j in journal_list if j['name'] == target_subjournal]
                    if not journal_list:
                        logger.error(f"未找到指定的子刊: {target_subjournal}")
                        logger.info(f"可用的{journal.upper()}子刊列表:")
                        for j in original_list[:10]:  # 只显示前10个
                            logger.info(f"  - {j['name']}")
                        if len(original_list) > 10:
                            logger.info(f"  ... 等共 {len(original_list)} 个子刊")
                        results[journal] = {"error": f"子刊不存在: {target_subjournal}"}
                        continue
                    logger.info(f"{journal.upper()}期刊: 已过滤到指定子刊 {target_subjournal} (1/{original_count})")
                else:
                    logger.info(f"{journal.upper()}期刊列表加载完成: 共 {len(journal_list)} 个子刊")
                
                # 使用用户指定的时间范围
                from datetime import datetime
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                
                logger.info(f"{journal.upper()}全量爬取: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}")
                
                # 爬取数据
                total_papers = 0
                total_ai_papers = 0
                total_non_ai_papers = 0
                successful_subjournals = 0
                failed_subjournals = []
                parser = self.parsers[journal]
                agent = self.agents[journal]
                
                for journal_info in journal_list:
                    subjournal_name = journal_info['name']
                    logger.info(f"开始处理 {journal.upper()} 子刊: {subjournal_name}")
                    
                    try:
                        papers = parser.scrape_journal(
                            journal_name=subjournal_name,
                            base_url=journal_info['link'],
                            start_date=start_date,
                            end_date=end_date
                        )
                        
                        # 只要没有抛出异常就算成功（即使没有论文也算成功）
                        successful_subjournals += 1
                    except Exception as e:
                        # 出现错误（如403、404等）才算失败
                        failed_subjournals.append(subjournal_name)
                        logger.warning(f"{journal.upper()} 子刊 {subjournal_name} 处理失败: {e}")
                        continue
                    
                    if papers:
                        # 完全复用Nature原始的AI分析逻辑
                        card_infos = []
                        for paper in papers:
                            card_infos.append({
                                'title': paper.get('title', ''),
                                'abstract': paper.get('abstract', ''),
                                'date': paper.get('date'),
                                'doi': paper.get('doi', ''),
                                'link': paper.get('url', ''),  # Nature使用'link'而不是'url'
                                'authors': paper.get('authors', ''),
                                'type': 'full'
                            })
                        
                        ai_papers = []
                        non_ai_papers = []
                        
                        if card_infos:
                            # 为每个item添加id
                            for i, item in enumerate(card_infos, start=1):
                                item['id'] = str(i)
                            logger.info(f"开始批量分析 {len(card_infos)} 篇文章")

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
                                    # AI分析失败，标记为分析失败并归类为非AI
                                    logger.warning(f"AI分析失败，将论文归类为非AI: {item.get('title', 'Unknown')[:50]}...")
                                    item['reason'] = 'AI分析失败'
                                    item['ai_relevant'] = False
                                    non_ai_papers.append(item)
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

                            logger.info(f"AI相关论文数: {len(ai_papers)}，非AI: {len(non_ai_papers)}")
                            
                            # 轻量版不保存到数据库，直接导出文件
                            total_papers += len(papers)
                            total_ai_papers += len(ai_papers)
                            total_non_ai_papers += len(non_ai_papers)
                            
                            # 导出AI相关论文
                            if ai_papers:
                                self.append_articles_to_file(ai_papers, journal, 'AI相关', start_date_str, end_date_str, export_format)
                            
                            # 导出非AI相关论文
                            if non_ai_papers:
                                self.append_articles_to_file(non_ai_papers, journal, '非AI相关', start_date_str, end_date_str, export_format)
                        
                        logger.info(f"{journal.upper()} {journal_info['name']}: 抓取{len(papers)}篇，AI相关{len(ai_papers)}篇，已导出文件")
                    else:
                        logger.info(f"{journal.upper()} {journal_info['name']}: 未获取到论文数据")
                
                results[journal] = {
                    "total_papers": total_papers, 
                    "ai_papers": total_ai_papers,
                    "non_ai_papers": total_non_ai_papers,
                    "successful_subjournals": successful_subjournals,
                    "total_subjournals": len(journal_list),
                    "failed_subjournals": failed_subjournals
                }
                
            except Exception as e:
                logger.error(f"{journal.upper()}期刊爬取失败: {e}")
                results[journal] = {"error": str(e)}
        
        self.print_summary(results, "全量爬取")
        return results
    
    def print_summary(self, results, mode):
        """打印总结"""
        logger.info("="*80)
        logger.info(f"统一学术期刊爬虫系统 - {mode}完成总结")
        logger.info("="*80)
        
        # 表格头部
        logger.info(f"{'期刊':<12} {'抓取文章':<12} {'AI相关':<12} {'非AI相关':<12} {'子刊成功':<12} {'状态':<12}")
        logger.info("-"*88)
        
        total_papers = 0
        total_ai = 0
        total_non_ai = 0
        success_count = 0
        
        for journal, result in results.items():
            if 'error' in result:
                status = "失败"
                papers = 0
                ai_papers = 0
                non_ai_papers = 0
                subjournal_status = "0/0"
                logger.info(f"{journal.upper():<12} {papers:<12} {ai_papers:<12} {non_ai_papers:<12} {subjournal_status:<12} {status:<12}")
                logger.info(f"  错误: {result['error']}")
            else:
                papers = result.get('total_papers', 0)
                ai_papers = result.get('ai_papers', 0)
                non_ai_papers = result.get('non_ai_papers', 0)
                successful_subs = result.get('successful_subjournals', 0)
                total_subs = result.get('total_subjournals', 0)
                failed_subs = result.get('failed_subjournals', [])
                
                subjournal_status = f"{successful_subs}/{total_subs}"
                status = "成功" if not failed_subs else f"部分成功"
                
                logger.info(f"{journal.upper():<12} {papers:<12} {ai_papers:<12} {non_ai_papers:<12} {subjournal_status:<12} {status:<12}")
                
                if failed_subs:
                    logger.info(f"  失败子刊: {', '.join(failed_subs)}")
                
                total_papers += papers
                total_ai += ai_papers
                total_non_ai += non_ai_papers
                success_count += 1
        
        logger.info("-"*88)
        total_journals = len(results)
        logger.info(f"{'总计':<12} {total_papers:<12} {total_ai:<12} {total_non_ai:<12} {'--':<12} {f'{success_count}/{total_journals}成功':<12}")
        logger.info("="*88)
    
    def cleanup(self):
        """清理资源"""
        for journal, parser in self.parsers.items():
            if hasattr(parser, 'close'):
                parser.close()
            elif hasattr(parser, 'cleanup'):
                parser.cleanup()

def parse_journals(journals_str):
    """解析期刊参数"""
    if not journals_str:
        return []
    
    journals = [j.strip().lower() for j in journals_str.split(',')]
    valid_journals = ['nature', 'science', 'cell', 'plos']
    invalid = [j for j in journals if j not in valid_journals]
    
    if invalid:
        logger.error(f"不支持的期刊: {', '.join(invalid)}")
        logger.info(f"支持的期刊: {', '.join(valid_journals)}")
        return []
    
    return journals

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='统一学术期刊爬虫系统 - 全量爬取',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 爬取Nature期刊（默认Excel格式）
  python main.py -j nature --start-date 2025-09-12 --end-date 2025-09-16
  
  # 爬取多个期刊并导出为CSV格式
  python main.py -j nature,science --start-date 2025-09-12 --end-date 2025-09-16 --format csv
  
  # 爬取Cell期刊并导出为JSON格式
  python main.py -j cell --start-date 2025-09-12 --end-date 2025-09-16 --format json
  
  # 只爬取Nature主刊
  python main.py -j nature --subjournal "Nature" --start-date 2025-09-12 --end-date 2025-09-16
  
  # 只爬取特定Cell子刊
  python main.py -j cell --subjournal "Cell Death & Differentiation" --start-date 2025-09-12 --end-date 2025-09-16
        """
    )
    
    parser.add_argument(
        '-j', '--journals',
        required=True,
        help='指定要爬取的期刊，支持: nature,science,cell,plos'
    )
    
    parser.add_argument(
        '--subjournal', '-sub',
        type=str,
        help='指定特定子刊名称（可选），例如: "Nature" 或 "Cell Death & Differentiation"'
    )
    
    parser.add_argument(
        '--start-date', '-s',
        type=str,
        required=True,
        help='开始日期 (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--end-date', '-e', 
        type=str,
        required=True,
        help='结束日期 (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--format', '-f',
        type=str,
        default='xlsx',
        choices=['xlsx', 'csv', 'json'],
        help='导出格式 (默认: xlsx)'
    )
    
    args = parser.parse_args()
    
    # 解析期刊参数
    journals = parse_journals(args.journals)
    if not journals:
        return 1
    
    # 创建爬虫系统
    crawler = CrawlerSystem()
    
    try:
        # 执行爬取（指定时间范围和导出格式）
        results = crawler.run_full_crawl(journals, args.start_date, args.end_date, args.format, args.subjournal)
        
        # 检查结果
        failed = [j for j, r in results.items() if 'error' in r]
        if failed:
            logger.warning(f"失败的期刊: {', '.join(failed)}")
            return 1
        else:
            logger.info("所有期刊爬取成功完成")
            return 0
            
    except KeyboardInterrupt:
        logger.info("用户中断爬取任务")
        return 1
    except Exception as e:
        logger.error(f"系统执行异常: {e}")
        return 1
    finally:
        crawler.cleanup()

# ====================================================================
# 全量爬取时间范围配置 
# ====================================================================

def get_full_crawl_time_range():
    """
    配置全量爬取的时间范围
    
    返回值:
        tuple: (start_date, end_date) 开始和结束时间
    
    说明:
        - start_date: 爬取开始时间，建议设置为期刊开始发表的年份
        - end_date: 爬取结束时间，通常设置为当前时间
        - 可以根据需要调整时间范围，比如只爬取最近几年的数据
    """
    
    # 默认配置：过去一周
    start_date = datetime.now() - timedelta(days=7)
    end_date = datetime.now()
    
    # 可选配置示例（取消注释来使用）:
    
    # 只爬取最近1年的数据
    # start_date = datetime.now() - timedelta(days=365)
    # end_date = datetime.now()
    
    # 只爬取最近3年的数据  
    # start_date = datetime.now() - timedelta(days=365*3)
    # end_date = datetime.now()
    
    # 爬取特定年份范围
    # start_date = datetime(2022, 1, 1)
    # end_date = datetime(2024, 12, 31)
    
    # 爬取最近6个月的数据
    # start_date = datetime.now() - timedelta(days=180)
    # end_date = datetime.now()
    
    return start_date, end_date

if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
