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

# 导入模块
from db import UnifiedDB
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
        self.databases = {}
        self.agents = {}
    
    def initialize_journal(self, journal_name):
        """初始化期刊组件"""
        self.databases[journal_name] = UnifiedDB(journal_name)
        self.agents[journal_name] = PaperAgent(logger=logger)
        self.parsers[journal_name] = create_parser(journal_name, self.databases[journal_name], self.agents[journal_name])
        logger.info(f"{journal_name.upper()}期刊组件初始化完成")
    
    def run_full_crawl(self, journals):
        """执行全量爬取"""
        logger.info("="*60)
        logger.info("统一学术期刊爬虫系统 - 全量爬取模式")
        logger.info(f"目标期刊: {', '.join(journals)}")
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
                
                logger.info(f"{journal.upper()}期刊列表加载完成: 共 {len(journal_list)} 个子刊")
                
                # 全量爬取时间范围 - 配置在文件底部
                start_date, end_date = get_full_crawl_time_range()
                
                logger.info(f"{journal.upper()}全量爬取: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}")
                
                # 爬取数据
                total_papers = 0
                total_saved = 0
                parser = self.parsers[journal]
                db = self.databases[journal]
                agent = self.agents[journal]
                
                for journal_info in journal_list:
                    papers = parser.scrape_journal(
                        journal_name=journal_info['name'],
                        base_url=journal_info['link'],
                        start_date=start_date,
                        end_date=end_date
                    )
                    
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
                            
                            # 保存AI数据到数据库
                            saved_count = 0
                            for paper in ai_papers:
                                if db.save_paper(paper, journal_info['name']):
                                    saved_count += 1
                            
                            # 保存非AI论文到JSON文件
                            if non_ai_papers:
                                self._save_non_ai_papers_to_json(journal, non_ai_papers, start_date, end_date)
                            
                            total_papers += len(papers)
                            total_saved += saved_count
                        
                        logger.info(f"{journal.upper()} {journal_info['name']}: 抓取{len(papers)}篇，AI相关{len(ai_papers)}篇，新增{saved_count}篇")
                    else:
                        logger.info(f"{journal.upper()} {journal_info['name']}: 未获取到论文数据")
                
                results[journal] = {"total_papers": total_papers, "total_saved": total_saved}
                
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
        logger.info(f"{'期刊':<12} {'数据库':<8} {'表名':<12} {'抓取':<8} {'新增':<8} {'状态':<12}")
        logger.info("-"*80)
        
        total_papers = 0
        total_saved = 0
        success_count = 0
        
        for journal, result in results.items():
            # 获取数据库和表信息
            db_name = "paper"
            table_name = journal
            
            if 'error' in result:
                status = "失败"
                papers = 0
                saved = 0
                logger.info(f"{journal.upper():<12} {db_name:<8} {table_name:<12} {papers:<8} {saved:<8} {status:<12}")
                logger.info(f"  错误: {result['error']}")
            else:
                papers = result.get('total_papers', 0)
                saved = result.get('total_saved', 0)
                status = "成功"
                logger.info(f"{journal.upper():<12} {db_name:<8} {table_name:<12} {papers:<8} {saved:<8} {status:<12}")
                total_papers += papers
                total_saved += saved
                success_count += 1
        
        logger.info("-"*80)
        logger.info(f"{'总计':<12} {'paper':<8} {'4个表':<12} {total_papers:<8} {total_saved:<8} {f'{success_count}/4成功':<12}")
        logger.info("="*80)
        
        # 数据库表结构信息
        logger.info("\n数据库结构:")
        logger.info(f"数据库名: paper")
        logger.info(f"表结构:")
        for journal in ['nature', 'science', 'cell', 'plos']:
            logger.info(f"  - {journal}: 主表")
            logger.info(f"  - {journal}_recent: 最近论文表")
        logger.info("="*80)
    
    def _save_non_ai_papers_to_json(self, journal, non_ai_papers, start_date, end_date):
        """保存非AI论文到JSON文件"""
        try:
            os.makedirs("exports/json/forward", exist_ok=True)
            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')
            json_file = f"exports/json/forward/no_ai_{journal}_{start_str}_{end_str}.json"
            
            papers_to_save = []
            for paper in non_ai_papers:
                paper_data = {
                    'title': paper.get('title', ''),
                    'abstract': paper.get('abstract', ''),
                    'date': paper.get('date').strftime('%Y-%m-%d') if hasattr(paper.get('date'), 'strftime') else str(paper.get('date', '')),
                    'doi': paper.get('doi', ''),
                    'link': paper.get('url', ''),
                    'authors': paper.get('authors', ''),
                    'type': paper.get('type', 'full_crawl')
                }
                papers_to_save.append(paper_data)
            
            existing_papers = []
            if os.path.exists(json_file):
                with open(json_file, 'r', encoding='utf-8') as f:
                    existing_papers = json.load(f)
            
            # 合并新论文（避免重复）
            existing_titles = {p.get('title', '') for p in existing_papers}
            new_papers = [p for p in papers_to_save if p.get('title', '') not in existing_titles]
            
            if new_papers:
                all_papers = existing_papers + new_papers
                # 按日期排序
                all_papers.sort(key=lambda x: x.get('date', ''), reverse=True)
                
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(all_papers, f, ensure_ascii=False, indent=2)
                
                logger.info(f"保存{len(new_papers)}篇非AI论文到 {json_file}")
            else:
                logger.info(f"没有新的非AI论文需要保存到 {json_file}")
                
        except Exception as e:
            logger.error(f"保存非AI论文到JSON时发生错误: {e}")
    
    def cleanup(self):
        """清理资源"""
        for journal, parser in self.parsers.items():
            parser.cleanup()
        for journal, db in self.databases.items():
            db.close()

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
  # 全量爬取Nature期刊
  python main.py -j nature
  
  # 全量爬取多个期刊
  python main.py -j nature,science,cell,plos
        """
    )
    
    parser.add_argument(
        '-j', '--journals',
        required=True,
        help='指定要爬取的期刊，支持: nature,science,cell,plos'
    )
    
    args = parser.parse_args()
    
    # 解析期刊参数
    journals = parse_journals(args.journals)
    if not journals:
        return 1
    
    # 创建爬虫系统
    crawler = CrawlerSystem()
    
    try:
        # 执行全量爬取
        results = crawler.run_full_crawl(journals)
        
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
    
    # 默认配置：从2016年开始到现在
    start_date = datetime(2016, 12, 31)
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
