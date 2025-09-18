#!/usr/bin/env python3
"""
PLOS期刊备选爬取逻辑
当主逻辑访问失败时，通过volume页面获取期刊列表
"""

import os
import sys
import json
import logging
import time
import random
import requests
from datetime import datetime, date
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

class PLOSFallbackParser:
    """PLOS期刊备选解析器"""
    
    def __init__(self, main_parser=None):
        self.main_parser = main_parser
        self.session = requests.Session()
        
        # 使用与主解析器相同的User-Agent
        if main_parser:
            self.session.headers.update(main_parser.session.headers)
        else:
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
    
    def scrape_journal_fallback(self, journal_name: str, base_url: str, start_date: datetime, end_date: datetime):
        """
        PLOS期刊备选爬取逻辑
        通过 /volume 页面获取期刊列表，然后进入具体期次
        """
        logger.info(f"启动PLOS备选爬取逻辑: {journal_name}")
        articles = []
        
        try:
            # 处理日期格式
            if isinstance(start_date, datetime):
                start_date = start_date.date()
            if isinstance(end_date, datetime):
                end_date = end_date.date()
            
            # 构建volume页面URL
            volume_url = base_url.rstrip('/') + '/volume'
            logger.info(f"访问PLOS volume页面: {volume_url}")
            
            # 获取volume页面
            response = self.session.get(volume_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 解析年份和月份期次
            issue_links = self._extract_issue_links(soup, start_date, end_date)
            logger.info(f"找到 {len(issue_links)} 个符合时间范围的期次")
            
            # 遍历每个期次
            for issue_info in issue_links:
                issue_url = issue_info['url']
                issue_date = issue_info['date']
                
                logger.info(f"处理期次: {issue_date} - {issue_url}")
                
                # 获取期次页面的文章
                issue_articles = self._scrape_issue_page(issue_url, journal_name, start_date, end_date)
                articles.extend(issue_articles)
                
                # 添加延迟
                time.sleep(random.uniform(1, 2))
            
            logger.info(f"PLOS备选爬取完成: {journal_name}，获得 {len(articles)} 篇文章")
            return articles
            
        except Exception as e:
            logger.error(f"PLOS备选爬取失败: {journal_name} - {e}")
            return []
    
    def _extract_issue_links(self, soup, start_date, end_date):
        """从volume页面提取符合时间范围的期次链接"""
        issue_links = []
        
        try:
            # 查找年份滑块容器
            journal_slides = soup.find('ul', id='journal_slides')
            if not journal_slides:
                logger.warning("未找到期刊年份滑块容器")
                return issue_links
            
            # 遍历每年的期次
            year_slides = journal_slides.find_all('li', class_='slide')
            for year_slide in year_slides:
                year_id = year_slide.get('id')
                if not year_id or not year_id.isdigit():
                    continue
                
                year = int(year_id)
                
                # 检查年份是否在时间范围内
                if year < start_date.year or year > end_date.year:
                    continue
                
                logger.debug(f"处理年份: {year}")
                
                # 查找该年的月份期次
                month_links = year_slide.find_all('a', href=True)
                for link in month_links:
                    href = link.get('href')
                    month_span = link.find('span')
                    
                    if href and month_span:
                        month_name = month_span.get_text(strip=True)
                        
                        # 将月份名称转换为月份数字
                        month_num = self._month_name_to_number(month_name)
                        if month_num is None:
                            continue
                        
                        # 构建该期次的日期
                        try:
                            issue_date = date(year, month_num, 1)
                            
                            # 检查是否在时间范围内
                            if self._is_issue_in_range(issue_date, start_date, end_date):
                                full_url = urljoin('https://journals.plos.org', href)
                                issue_links.append({
                                    'url': full_url,
                                    'date': issue_date,
                                    'year': year,
                                    'month': month_name
                                })
                                logger.debug(f"添加期次: {year}-{month_name} -> {full_url}")
                        
                        except ValueError as e:
                            logger.debug(f"日期解析失败: {year}-{month_name} - {e}")
                            continue
            
            # 按日期排序（从新到旧）
            issue_links.sort(key=lambda x: x['date'], reverse=True)
            
        except Exception as e:
            logger.error(f"提取期次链接失败: {e}")
        
        return issue_links
    
    def _month_name_to_number(self, month_name):
        """将月份名称转换为数字"""
        month_mapping = {
            'January': 1, 'February': 2, 'March': 3, 'April': 4,
            'May': 5, 'June': 6, 'July': 7, 'August': 8,
            'September': 9, 'October': 10, 'November': 11, 'December': 12
        }
        return month_mapping.get(month_name.capitalize())
    
    def _is_issue_in_range(self, issue_date, start_date, end_date):
        """检查期次日期是否在范围内"""
        # 对于月份，我们检查该月是否与时间范围有重叠
        issue_month_start = issue_date.replace(day=1)
        
        # 计算该月的最后一天
        if issue_date.month == 12:
            issue_month_end = issue_date.replace(year=issue_date.year + 1, month=1, day=1)
        else:
            issue_month_end = issue_date.replace(month=issue_date.month + 1, day=1)
        
        # 检查重叠
        return not (issue_month_end.replace(day=1) <= start_date or issue_month_start > end_date)
    
    def _scrape_issue_page(self, issue_url, journal_name, start_date, end_date):
        """爬取具体期次页面的文章"""
        articles = []
        
        try:
            response = self.session.get(issue_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找文章section
            sections = soup.find_all('div', class_='section')
            
            for section in sections:
                # 查找section中的文章
                article_items = section.find_all('div', class_='item cf')
                
                for item in article_items:
                    try:
                        # 提取文章信息
                        article_info = self._extract_article_from_item(item, journal_name)
                        
                        if article_info:
                            # 检查日期是否在范围内
                            article_date = article_info.get('date')
                            if article_date and isinstance(article_date, date):
                                if start_date <= article_date <= end_date:
                                    articles.append(article_info)
                                    logger.info(f"PLOS备选文章: {article_info.get('title', 'Unknown')[:80]}")
                                else:
                                    logger.debug(f"文章日期 {article_date} 超出范围，跳过")
                            else:
                                # 如果没有日期或日期解析失败，也包含进去
                                articles.append(article_info)
                                logger.info(f"PLOS备选文章: {article_info.get('title', 'Unknown')[:80]}")
                    
                    except Exception as e:
                        logger.error(f"解析文章项失败: {e}")
                        continue
            
        except Exception as e:
            logger.error(f"爬取期次页面失败: {issue_url} - {e}")
        
        return articles
    
    def _extract_article_from_item(self, item, journal_name):
        """从文章项中提取信息"""
        try:
            # 提取标题和链接
            title_elem = item.find('h3', class_='item--article-title')
            if not title_elem:
                return None
            
            title_link = title_elem.find('a', href=True)
            if not title_link:
                return None
            
            title = title_link.get_text(strip=True)
            article_url = urljoin('https://journals.plos.org', title_link.get('href'))
            
            # 提取DOI
            doi = None
            article_info_elem = item.find('p', class_='article-info')
            if article_info_elem:
                doi_link = article_info_elem.find('a', href=True)
                if doi_link and 'doi.org' in doi_link.get('href', ''):
                    doi = doi_link.get('href')
            
            # 提取发表日期
            pub_date = None
            if article_info_elem:
                date_span = article_info_elem.find('span', class_='article-info--date')
                if date_span:
                    date_text = date_span.get_text(strip=True)
                    # 解析日期 "published January 30, 2025"
                    date_text = date_text.replace('published', '').strip()
                    try:
                        pub_date = dateparser.parse(date_text).date()
                    except:
                        logger.debug(f"日期解析失败: {date_text}")
            
            # 提取作者
            authors = ''
            authors_elem = item.find('p', class_='authors')
            if authors_elem:
                authors = authors_elem.get_text(strip=True)
            
            # 获取详细信息（如果主解析器可用）
            abstract = ''
            if self.main_parser and hasattr(self.main_parser, '_get_plos_article_details_from_page'):
                try:
                    detailed_info = self.main_parser._get_plos_article_details_from_page(article_url)
                    if detailed_info:
                        abstract = detailed_info.get('abstract', '')
                        if not pub_date and detailed_info.get('date'):
                            pub_date = detailed_info['date']
                except Exception as e:
                    logger.debug(f"获取详细信息失败: {e}")
            
            return {
                'title': title,
                'abstract': abstract,
                'doi': doi or article_url,  # 如果没有DOI，使用URL
                'url': article_url,
                'date': pub_date or date.today(),
                'journal': journal_name,
                'authors': authors,
                'type': 'fallback'
            }
            
        except Exception as e:
            logger.error(f"提取文章信息失败: {e}")
            return None
    
    def close(self):
        """关闭会话"""
        try:
            self.session.close()
        except:
            pass
