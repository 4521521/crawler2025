#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一学术期刊爬虫系统 - 解析器模块
包含Nature、Science、Cell、PLOS四个期刊的实际爬虫解析逻辑
"""

import os
import sys
import json
import logging
import time
import random
import re
import requests
from datetime import datetime, date
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
from dateutil import parser as dateparser

# 设置logger
logger = logging.getLogger(__name__)

# Selenium imports
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# pandas导入（可选）
try:
    import pandas as pd
except ImportError:
    pd = None
    logger.warning("pandas未安装，某些功能可能不可用")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BaseParser:
    """基础解析器类"""
    
    def __init__(self, journal_type, database=None, paper_agent=None, use_selenium=False):
        self.journal_type = journal_type
        self.db = database
        self.paper_agent = paper_agent
        self.use_selenium = use_selenium and SELENIUM_AVAILABLE
        self.driver = None
        self.session = requests.Session()
        
        # 通用用户代理
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0'
        ]
        
        # 设置请求头（参考cell目录的成功配置）
        self.session.headers.update({
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'DNT': '1',
            # 增强反爬虫措施（参考cell目录成功配置）
            'Referer': 'https://www.cell.com/',
            'Origin': 'https://www.cell.com'
        })
        
        # 配置超时和重试
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        retry_strategy = Retry(
            total=8,  # 进一步增加重试次数
            backoff_factor=5,  # 更长的退避时间
            status_forcelist=[403, 429, 500, 502, 503, 504],
            respect_retry_after_header=True
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # 初始化Selenium（如果需要）
        if self.use_selenium:
            self._init_selenium_driver()
    
    def _init_selenium_driver(self):
        """初始化Selenium WebDriver - 优先使用本地驱动，回退到自动下载"""
        if not SELENIUM_AVAILABLE:
            logger.warning("Selenium不可用，回退到requests方式")
            self.use_selenium = False
            return
        
        try:
            from selenium.webdriver.chrome.service import Service
            
            # 尝试多个可能的本地chromedriver路径
            current_dir = os.path.dirname(os.path.abspath(__file__))
            possible_paths = [
                # 与crawler同级的chrome-win64目录
                os.path.join(os.path.dirname(current_dir), 'chrome-win64', 'chromedriver_140.0.7339.82_x64.exe'),
                # 直接在chrome-win64目录下的chromedriver.exe
                os.path.join(os.path.dirname(current_dir), 'chrome-win64', 'chromedriver.exe'),
                # 其他可能的路径
                os.path.join(current_dir, 'chromedriver.exe'),
            ]
            
            service = None
            local_driver_found = False
            
            # 直接使用自动下载方式，因为本地驱动版本不兼容
            logger.info("使用Selenium自动下载ChromeDriver（确保兼容性）")
            service = None
            
            # 配置Chrome选项
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument(f'--user-agent={random.choice(self.user_agents)}')
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            
            # 减少日志输出
            chrome_options.add_argument('--disable-logging')
            chrome_options.add_argument('--log-level=3')
            chrome_options.add_argument('--silent')
            
            # 初始化WebDriver
            if service:
                logger.info(f"{self.journal_type}: 使用本地chromedriver启动（快速模式）")
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                logger.info(f"{self.journal_type}: 使用自动下载chromedriver启动（可能需要等待）")
                self.driver = webdriver.Chrome(options=chrome_options)
                
            logger.info(f"{self.journal_type} Selenium初始化成功")
            
        except Exception as e:
            logger.error(f"{self.journal_type} Selenium初始化失败: {e}")
            self.use_selenium = False
    
    def human_like_delay(self, min_delay=0.1, max_delay=0.8):
        """模拟人类浏览行为的随机延迟 - 控制在1秒内"""
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)
    
    def _is_date_in_range(self, article_date, start_date, end_date) -> bool:
        """检查文章日期是否在指定范围内"""
        try:
            # 统一转换为date对象
            if isinstance(article_date, str):
                article_date = datetime.strptime(article_date, '%Y-%m-%d').date()
            elif isinstance(article_date, datetime):
                article_date = article_date.date()
            
            if isinstance(start_date, datetime):
                start_date = start_date.date()
            if isinstance(end_date, datetime):
                end_date = end_date.date()
            
            return start_date <= article_date <= end_date
        except Exception as e:
            logger.error(f"日期范围检查失败: {e}")
            return False
    
    def wait_for_page_load(self, driver, max_wait=60):
        """等待页面完全加载，处理'Just a moment...'等反爬虫页面 - 增强版"""
        if not driver:
            return False
        
        start_time = time.time()
        consecutive_anti_bot = 0
        
        while time.time() - start_time < max_wait:
            try:
                # 等待页面基本结构加载
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                # 检查页面标题和内容
                title = driver.title.lower()
                page_source = driver.page_source.lower()
                
                # 检测反爬虫页面
                anti_bot_phrases = [
                    'just a moment', 'please wait', 'checking your browser',
                    'cloudflare', 'ddos protection', 'access denied',
                    'blocked', 'security check', 'ray id', 'performance & security'
                ]
                
                is_anti_bot = any(phrase in title or phrase in page_source for phrase in anti_bot_phrases)
                
                if is_anti_bot:
                    consecutive_anti_bot += 1
                    elapsed = int(time.time() - start_time)
                    logger.info(f"检测到反爬虫页面，继续等待加载完成... (已等待 {elapsed}s, 连续检测 {consecutive_anti_bot} 次)")
                    
                    # 检查是否是"Just a moment"页面，给予更长等待时间
                    is_just_a_moment = 'just a moment' in title or 'just a moment' in page_source
                    
                    # 如果连续多次检测到反爬虫页面，尝试一些操作
                    if consecutive_anti_bot > 5:
                        logger.info("尝试模拟人类行为...")
                        try:
                            # 滚动页面
                            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                            time.sleep(1)
                            driver.execute_script("window.scrollTo(0, 0);")
                            time.sleep(2)
                            
                            # 尝试点击页面（如果有可点击元素）
                            clickable = driver.find_elements(By.TAG_NAME, "button")
                            if not clickable:
                                clickable = driver.find_elements(By.TAG_NAME, "a")
                            if clickable:
                                try:
                                    clickable[0].click()
                                    time.sleep(3)
                                except:
                                    pass
                        except Exception as e:
                            logger.debug(f"模拟人类行为失败: {e}")
                    
                    # Just a moment页面需要更长等待时间
                    wait_time = 8 if is_just_a_moment else (5 if consecutive_anti_bot > 3 else 3)
                    time.sleep(wait_time)
                    continue
                else:
                    consecutive_anti_bot = 0
                
                # 检查页面是否有实际内容
                if len(page_source) > 1000:  # 页面有足够内容
                    # 进一步检查是否有期望的内容
                    if any(keyword in page_source for keyword in ['science', 'research', 'article', 'doi']):
                        logger.info("页面加载完成，包含期望内容")
                        return True
                    
                time.sleep(2)
                
            except Exception as e:
                logger.warning(f"等待页面加载时出错: {e}")
                time.sleep(3)
        
        logger.warning(f"页面加载超时 ({max_wait}秒)")
        return False
    
    def get_page_with_retry(self, url, max_retries=3, timeout=60, use_selenium_fallback=True):
        """增强的请求方法，支持Selenium备选方案"""
        # 第一阶段：使用requests方式，最多重试3次
        for attempt in range(max_retries):
            try:
                # 轮换User-Agent
                if hasattr(self, 'user_agents'):
                    user_agent = random.choice(self.user_agents)
                    self.session.headers['User-Agent'] = user_agent
                elif hasattr(self, 'science_user_agents'):
                    user_agent = random.choice(self.science_user_agents)
                    self.session.headers['User-Agent'] = user_agent
                elif hasattr(self, 'cell_user_agents'):
                    user_agent = random.choice(self.cell_user_agents)
                    self.session.headers['User-Agent'] = user_agent
                
                # 增加随机延迟避免被检测
                if attempt > 0:
                    delay = random.uniform(5, 15) * (attempt + 1)  # 更长的延迟
                    logger.info(f"Requests第{attempt + 1}次尝试前等待 {delay:.1f} 秒...")
                    time.sleep(delay)
                
                logger.info(f"requests方式访问 {url} (第 {attempt + 1} 次)")
                response = self.session.get(url, timeout=timeout)
                
                if response.status_code == 200:
                    logger.info(f"成功获取页面: {url}")
                    return response
                elif response.status_code == 403:
                    logger.warning(f"收到403错误 (第 {attempt + 1} 次): {url}")
                    if attempt < max_retries - 1:
                        # 403错误时等待更长时间
                        time.sleep(random.uniform(10, 20))  # 403错误更长等待
                        continue
                else:
                    logger.warning(f"HTTP {response.status_code}: {url}")
                    
            except Exception as e:
                logger.warning(f"requests请求失败 (第 {attempt + 1} 次): {e}")
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(5, 12))  # 更长的错误恢复时间
        
        # 第二阶段：如果requests失败且支持Selenium，使用Selenium备选方案
        if use_selenium_fallback and self.use_selenium and hasattr(self, 'driver') and self.driver:
            logger.info(f"Requests失败，尝试Selenium备选方案: {url}")
            try:
                self.driver.get(url)
                
                # 等待页面完全加载
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                from selenium.webdriver.common.by import By
                
                WebDriverWait(self.driver, 30).until(
                    lambda driver: driver.execute_script("return document.readyState") == "complete"
                )
                
                # 额外等待动态内容加载
                time.sleep(8)
                
                # 检查页面是否成功加载（不是错误页面）
                page_source = self.driver.page_source
                if "403" not in page_source and "Forbidden" not in page_source and len(page_source) > 1000:
                    logger.info(f"Selenium成功获取页面: {url}")
                    # 创建一个模拟的response对象
                    class SeleniumResponse:
                        def __init__(self, text, status_code=200):
                            self.text = text
                            self.status_code = status_code
                            self.content = text.encode('utf-8')
                    
                    return SeleniumResponse(page_source)
                else:
                    logger.warning(f"Selenium获取的页面可能有问题: {url}")
                    
            except Exception as e:
                logger.error(f"Selenium备选方案也失败: {e}")
        
        logger.error(f"所有方式都失败: {url}")
        return None
    
    def _load_is_journal_config(self, journal_type):
        """加载is_journal配置文件"""
        try:
            config_file = f"journals_config/{journal_type}_is_journal.json"
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_file)
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            logger.info(f"加载{journal_type}的is_journal配置成功")
            return config
            
        except Exception as e:
            logger.warning(f"加载{journal_type}的is_journal配置失败: {e}")
            return {}
    
    def cleanup(self):
        """清理资源"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info(f"{self.journal_type} Selenium驱动已关闭")
            except Exception as e:
                logger.error(f"关闭{self.journal_type} Selenium驱动失败: {e}")

class NatureParser(BaseParser):
    """Nature期刊解析器 - 完全基于独立版paper_parser.py逻辑"""
    
    def __init__(self, database=None, paper_agent=None):
        super().__init__('nature', database, paper_agent, use_selenium=False)
        self.non_ai_set = set()
        # 设置独立版的请求头
        self.headers = {'User-Agent': 'Mozilla/5.0'}
        self.session.headers.update(self.headers)
    
    def fetch_abstract(self, url, base_link):
        """
        抓取 Nature 文章页面中 article__teaser 部分作为摘要
        完全基于独立版逻辑
        """
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 首先尝试找到标准的摘要标签
        abstract_tag = soup.find('div', {'id': 'Abs1-content'})
        if not abstract_tag:
            # 按独立版的优先级顺序尝试不同的摘要标签
            abstract_divs = soup.find_all("p", class_="article__teaser")
            if abstract_divs:
                abstract = " ".join(div.get_text(strip=True) for div in abstract_divs)
            else:
                abstract_divs = soup.find_all("div", class_="article__teaser")
                if abstract_divs:
                    abstract = " ".join(div.get_text(strip=True) for div in abstract_divs)
                else:
                    abstract_divs = soup.find_all("div", class_="c-article-section__content")
                    if abstract_divs:
                        abstract = " ".join(div.get_text(strip=True) for div in abstract_divs)
                    else:
                        abstract_divs = soup.find_all("div", class_="c-article-body main-content")
                        if abstract_divs:
                            abstract = " ".join(div.get_text(strip=True) for div in abstract_divs)
                        else:
                            logger.error(f"{base_link}未找到摘要")
                            abstract = "未找到摘要"
        else:
            abstract = abstract_tag.get_text(strip=True)

        return abstract
    
    def fetch_abstract_and_authors(self, url, base_link):
        """
        抓取 Nature 文章页面的摘要和作者信息
        基于独立版逻辑，并添加作者提取
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt == max_retries - 1:
                    logger.error(f"抓取摘要和作者时发生错误（尝试{max_retries}次后失败）: {e}")
                    return "抓取摘要失败", ""
                logger.warning(f"网络超时，正在重试 ({attempt+1}/{max_retries}): {url}")
                import time
                time.sleep(2 * (attempt + 1))  # 递增延迟：2秒、4秒、6秒
                continue
        
        try:

            # 获取摘要 - 使用原有逻辑
            abstract = ""
            # 定义摘要选择器在条件语句外面，避免作用域问题
            abstract_selectors = [
                ("p", "article__teaser"),
                ("div", "article__teaser"),
                ("div", "c-article-section__content"),
                ("div", "c-article-body main-content")
            ]
            
            abstract_tag = soup.find('div', {'id': 'Abs1-content'})
            if not abstract_tag:
                # 按独立版的优先级顺序尝试不同的摘要标签
                for tag, class_name in abstract_selectors:
                    abstract_divs = soup.find_all(tag, class_=class_name)
                    if abstract_divs:
                        abstract = " ".join(div.get_text(strip=True) for div in abstract_divs)
                        break
                
                if not abstract:
                    logger.error(f"{base_link}未找到摘要")
                    abstract = "未找到摘要"
            else:
                abstract = abstract_tag.get_text(strip=True)

            # 获取作者信息 - 添加Nature特有的作者选择器
            authors = ""
            author_selectors = [
                'meta[name="citation_author"]',  # 优先使用meta标签
                'div.c-author-list',  # Nature常用的作者容器
                'ul.c-author-list',
                'div.authors',
                '.author-list',
                'span.authors',
                '.c-article-author-list',
                'div.c-article-header__authors',
                'div.c-nature-box__body .authors'
            ]
            
            for selector in author_selectors:
                if selector.startswith('meta'):
                    # 处理meta标签
                    author_metas = soup.find_all('meta', attrs={'name': 'citation_author'})
                    if author_metas:
                        authors = '; '.join([meta.get('content', '') for meta in author_metas])
                        break
                else:
                    authors_elem = soup.select_one(selector)
                    if authors_elem:
                        # 尝试提取链接中的作者名
                        author_links = authors_elem.find_all('a')
                        if author_links:
                            author_names = []
                            for link in author_links:
                                text = link.get_text(strip=True)
                                # 跳过明显的非作者链接
                                if (not text.startswith('http') and 
                                    'orcid' not in text.lower() and
                                    len(text) > 1 and len(text) < 100):
                                    author_names.append(text)
                            
                            if author_names:
                                authors = '; '.join(author_names)
                            else:
                                # 如果没找到有效的作者链接，使用整个元素文本
                                authors = authors_elem.get_text(strip=True)
                        else:
                            authors = authors_elem.get_text(strip=True)
                        
                        # 清理作者信息
                        if authors:
                            import re
                            # 移除常见的无关文本
                            authors = re.sub(r'Show\s*authors?', '', authors, flags=re.IGNORECASE)
                            authors = re.sub(r'View\s*ORCID\s*Profile', '', authors, flags=re.IGNORECASE)
                            authors = re.sub(r'Authors?\s*&?\s*Affiliations?', '', authors, flags=re.IGNORECASE)
                            # 清理多余的分号和空格
                            authors = re.sub(r';\s*;+', ';', authors)
                            authors = re.sub(r'^\s*;\s*|\s*;\s*$', '', authors)
                            authors = re.sub(r'\s+', ' ', authors)
                            authors = authors.strip()
                        
                        if authors and len(authors) > 3:
                            break

            return abstract, authors
            
        except Exception as e:
            logger.error(f"抓取摘要和作者时发生错误: {e}")
            return "抓取摘要失败", ""
    
    def fetch_real_abstract_and_doi(self, url):
        """
        请求文章页面，解析出摘要和 DOI
        完全基于独立版逻辑
        """
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            # 摘要    
            abstract = self.fetch_abstract(url, "")
            
            # DOI - 使用独立版的解析逻辑
            doi_tag = soup.find('meta', attrs={'name': 'citation_doi'}) \
                   or soup.find('meta', attrs={'name': 'dc.Identifier'})
            doi = doi_tag['content'].strip() if doi_tag and doi_tag.get('content') else "未找到 DOI"
            
            return abstract, doi
        except Exception as e:
            logger.error(f"抓取摘要和DOI时发生错误: {e}")
            return f"【抓取摘要出错：{e}】", f"【抓取 DOI 出错：{e}】"
    
    def load_non_ai_set(self, filepath='exports/json/non_ai_papers.json'):
        """加载非AI论文集合 - 独立版逻辑"""
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        self.non_ai_set.add((data['title'], data['link']))
                    except Exception:
                        continue
        return
    
    def scrape_journal(self, journal_name: str, base_url: str, start_date: datetime, end_date: datetime):
        """
        完全基于独立版的Nature期刊爬取逻辑
        保持访问机制、请求头设置、页面解析细节与独立版一致
        但保留合并版的数据库保存逻辑
        """
        logger.info(f"开始爬取Nature期刊: {journal_name}")
        articles = []
        
        # 尝试两种类型的文章：news-and-comment 和 research-articles
        article_types = ['news-and-comment', 'research-articles']
        
        for article_type in article_types:
            logger.info(f"抓取 {journal_name} 的 {article_type} 类型文章")
            
            # 构建页面URL - 使用独立版的URL构建逻辑
            page_url = urljoin(base_url, article_type)
            error_link = []
            non_ai_articles = []
            card_infos = []
            ret_date = None
            
            # 加载非AI论文集合
            self.load_non_ai_set()

            # 处理日期格式
            if isinstance(start_date, datetime):
                start_date = start_date.date()
            if isinstance(end_date, datetime):
                end_date = end_date.date()
            
            # 分页抓取逻辑 - 完全使用独立版逻辑
            while page_url:
                try:
                    resp = requests.get(page_url, headers=self.headers, timeout=30)
                    resp.raise_for_status()
                    soup = BeautifulSoup(resp.text, 'html.parser')
                except Exception as e:
                    logger.error(f"请求网页失败: {e}")
                    error_link.append(base_url)
                    break

                try:
                    cards = soup.find_all('article', class_='c-card')
                    logger.info(f"[{page_url}] 找到 {len(cards)} 篇文章")
                except Exception as e:
                    logger.error(f"查找文章卡片时出错: {e}")
                    error_link.append(base_url)
                    break
                
                for card in cards:
                    try:
                        title_tag = card.find('h3', class_='c-card__title')
                        if not title_tag:
                            continue
                        a = title_tag.find('a', href=True)
                        title = a.get_text(strip=True)
                        link = urljoin('https://www.nature.com', a['href'])
                        logger.info(f"开始抓取文章: {title} ({link})")
                        
                        # 日期解析 - 使用独立版逻辑
                        time_tag = card.find('time')
                        raw_date = time_tag.get('datetime', time_tag.get_text(strip=True)) if time_tag else ''
                        try:
                            pub_date = dateparser.parse(raw_date)
                        except Exception:
                            pub_date = None
                        if pub_date:
                            pub_date = pub_date.date()
                        
                        ret_date = pub_date
                        
                        # 日期过滤逻辑 - 使用独立版逻辑
                        if pub_date:
                            if start_date and pub_date < start_date:
                                logger.info(f"跳过早于起始日期的论文: {title}, 发布日期: {pub_date}")
                                continue
                            if end_date and pub_date > end_date:
                                logger.info(f"跳过晚于终止日期的论文: {title}, 发布日期: {pub_date}")
                                continue
                        
                        # 独立版的延迟设置
                        import time as time_module
                        time_module.sleep(0.6)  # 减少请求频率

                        # 获取摘要和作者信息 - 增强版逻辑
                        real_abs, authors = self.fetch_abstract_and_authors(link, base_url)
                        doi = link.split('/')[-1]  # 假设 DOI 是 URL 的最后一部分

                        # 检查论文是否已存在 - 使用合并版的数据库逻辑
                        if self.db and hasattr(self.db, 'paper_exists') and self.db.paper_exists(doi=doi):
                            logger.info(f"论文已存在，跳过: {title}")
                            continue
                                
                        # 检查是否在非AI集合中
                        if (title, link) in self.non_ai_set:
                            logger.info(f"跳过已记录为非AI的论文: {title}")
                            continue
                                
                        card_infos.append({
                            'title': title,
                            'url': link,  # 使用合并版的字段名
                            'abstract': real_abs,
                            'date': pub_date,
                            'doi': doi,
                            'type': article_type,
                            'journal': journal_name,
                            'authors': authors  # 从文章页面提取的作者信息
                        })

                    except Exception as e:
                        logger.error(f"处理文章卡片时出错: {e}")
                        continue
                            
                # 分页逻辑 - 使用独立版逻辑
                next_page = None
                li_next = soup.find('li', attrs={'data-test': 'page-next'})
                if li_next:
                    a = li_next.find('a', class_='c-pagination__link', href=True)
                    if a:
                        next_page = urljoin('https://www.nature.com', a['href'])
                        logger.info(f"从 li[data-test=page-next] 找到下一页: {next_page}")
                        
                if next_page:
                    # 安全检查 - 独立版逻辑
                    if isinstance(ret_date, datetime):
                        ret_date = ret_date.date()
                    if ret_date and start_date and ret_date < start_date:
                        logger.info(f"查询到的论文日期 {ret_date} 早于起始时间 {start_date}，停止翻页")
                        page_url = None
                    else:
                        logger.info(f"跳转到下一页: {next_page}")
                        page_url = next_page
                else:
                    logger.info("未找到下一页，结束分页抓取")
                    page_url = None

            # AI分析逻辑 - 使用独立版的三重验证机制
            if card_infos and self.paper_agent:
                for i, item in enumerate(card_infos, start=1):
                    item['id'] = str(i)
                logger.info(f"开始批量分析 {len(card_infos)} 篇文章")

                contents = [{"id": item['id'], "title": item['title'], "abstract": item['abstract']} for item in card_infos]
                result1 = self.paper_agent.batch_analyze_papers_in_batches_concurrent(contents, batch_size=10)
                
                # 两次AI分析之间添加延迟，避免API限流
                import time as time_module
                import random
                delay = random.uniform(1, 3)  # 2-5秒随机延迟
                # logger.info(f"第一轮AI分析完成，等待 {delay:.1f} 秒后进行第二轮分析...")
                time_module.sleep(delay)
                
                result2 = self.paper_agent.batch_analyze_papers_in_batches_concurrent(contents, batch_size=10)
                
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
                        articles.append(item)
                    elif not r1['is_ai_related'] and not r2['is_ai_related']:
                        item['reason'] = r1['explanation']
                        non_ai_articles.append(item)
                    else:
                        review = self.paper_agent.analyze_paper(item['title'], item['abstract'])
                        item['reason'] = review.get('explanation', 'reviewed')
                        if review['is_ai_related']:
                            articles.append(item)
                        else:
                            non_ai_articles.append(item)

                logger.info(f"AI相关论文数: {len(articles)}，非AI: {len(non_ai_articles)}")
                
                # 保存非AI论文到文件 - 独立版逻辑
                try:
                    import os
                    os.makedirs("exports/json", exist_ok=True)
                    with open('exports/json/non_ai_papers.json', 'a', encoding='utf-8') as f:
                        for item in non_ai_articles:
                            filtered_item = {
                                "title": item["title"],
                                "link": item["url"]  # 注意字段名映射
                            }
                            json.dump(filtered_item, f, ensure_ascii=False)
                            f.write('\n')
                except Exception as e:
                    logger.error(f"保存非AI论文列表失败: {e}")
        else:
            # 如果没有AI分析器，直接添加所有文章
            articles.extend(card_infos)
        
        # 排序 - 使用独立版逻辑
        articles.sort(key=lambda x: x['date'] or dateparser.parse('1900-01-01'), reverse=True)
        logger.info(f"Nature {journal_name}爬取完成，获得{len(articles)}篇文章")
        return articles

class ScienceParser(BaseParser):
    """Science期刊解析器 - 基于实际science_requests_parser.py逻辑"""
    
    def __init__(self, database=None, paper_agent=None):
        super().__init__('science', database, paper_agent, use_selenium=True)
        
        # 加载is_journal配置
        self.is_journal_config = self._load_is_journal_config('science')
        
        # Science专用的User-Agent列表，优先使用最新的
        self.science_user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',  # 最优先使用
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0',  # 次优先
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
        ]
        
        # 失败期刊记录
        self.failed_journals = []
        
        # Science特定的请求头设置
        self.session.headers.update({
            'User-Agent': self.science_user_agents[0],  # 优先使用最新的User-Agent
            'Referer': 'https://www.science.org/',
            'Origin': 'https://www.science.org'
        })
        
        # Science子刊Archive URL映射
        self.science_archive_urls = {
            'Science': 'https://www.science.org/loi/science',
            'Science Advances': 'https://www.science.org/loi/sciadv', 
            'Science Immunology': 'https://www.science.org/loi/sciimmunol',
            'Science Robotics': 'https://www.science.org/loi/scirobotics',
            'Science Signaling': 'https://www.science.org/loi/signaling',
            'Science Translational Medicine': 'https://www.science.org/loi/stm'
        }
        
        # 重新初始化Selenium以使用新的User-Agent
        if self.use_selenium and hasattr(self, 'driver') and self.driver:
            self.cleanup()  # 使用正确的方法名
            self._init_science_selenium_driver()
    
    def _init_science_selenium_driver(self):
        """初始化Science专用的Selenium WebDriver，使用最新的User-Agent"""
        if not SELENIUM_AVAILABLE:
            logger.warning("Selenium不可用，回退到requests方式")
            self.use_selenium = False
            return
        
        try:
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            # 配置Chrome选项 - Science专用
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument(f'--user-agent={self.science_user_agents[0]}')  # 使用最新的User-Agent
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            
            # 减少日志输出
            chrome_options.add_argument('--disable-logging')
            chrome_options.add_argument('--log-level=3')
            chrome_options.add_argument('--silent')
            
            # 初始化WebDriver - 使用Selenium自动下载（参考paperagent1.4的方式）
            try:
                logger.info("Science: 使用Selenium自动下载chromedriver启动（可能需要等待）")
                self.driver = webdriver.Chrome(options=chrome_options)
                logger.info("Science Selenium WebDriver初始化成功(自动下载)")
            except Exception as e:
                logger.error(f"Science Chrome驱动自动下载失败: {e}")
                raise Exception(f"Science Chrome驱动初始化失败: {e}")
                
        except Exception as e:
            logger.error(f"Science Selenium初始化失败: {e}")
            self.use_selenium = False
            self.driver = None
    
    def scrape_journal(self, journal_name: str, base_url: str, start_date: datetime, end_date: datetime):
        """爬取Science期刊数据 - 基于Archive页面年份-卷次逻辑"""
        logger.info(f"开始爬取Science期刊: {journal_name}")
        articles = []
        
        try:
            # 处理日期格式
            if isinstance(start_date, datetime):
                start_date = start_date.date()
            if isinstance(end_date, datetime):
                end_date = end_date.date()
            
            # 获取Archive URL
            archive_url = self.science_archive_urls.get(journal_name)
            if not archive_url:
                logger.warning(f"未找到{journal_name}的Archive URL，使用默认")
                archive_url = 'https://www.science.org/loi/science'
            
            logger.info(f"Science使用Archive URL: {archive_url}")
            
            # 根据日期范围确定需要爬取的年份
            target_years = set(range(start_date.year, end_date.year + 1))
            logger.info(f"目标年份范围: {sorted(target_years)}")
            
            # 为每个年份构建URL并爬取
            for year in sorted(target_years):
                year_volumes = self._get_science_year_volumes(archive_url, year, start_date, end_date)
                if year_volumes:
                    logger.info(f"年份 {year}: 找到 {len(year_volumes)} 个符合条件的卷次")
                    
                    # 爬取每个卷次的文章
                    for volume_info in year_volumes:
                        volume_url = volume_info['url']
                        volume_title = volume_info['title']
                        
                        logger.info(f"正在爬取卷次: {volume_title}")
                        volume_articles = self._scrape_science_volume_articles(volume_url, journal_name, start_date, end_date)
                        
                        if volume_articles:
                            articles.extend(volume_articles)
                            logger.info(f"卷次 {volume_title} 获得 {len(volume_articles)} 篇文章")
                        
                        # 添加延迟避免过快请求
                        time.sleep(random.uniform(2, 4))
                else:
                    logger.info(f"年份 {year}: 没有符合条件的卷次")
            
        except Exception as e:
            logger.error(f"Science期刊爬取失败: {e}")
            
            # 如果是403错误，尝试备选方案
            if '403' in str(e) or 'Forbidden' in str(e):
                logger.warning(f"Science {journal_name} 收到403错误，尝试备选方案...")
                articles = self._science_fallback_scrape(journal_name, base_url, start_date, end_date)
            
        logger.info(f"Science {journal_name}爬取完成，获得{len(articles)}篇文章")
        return articles
    
    def _science_fallback_scrape(self, journal_name: str, base_url: str, start_date: date, end_date: date):
        """Science期刊403错误备选方案"""
        logger.info(f"启动Science {journal_name} 403错误备选方案")
        articles = []
        
        try:
            # 备选方案1: 使用不同的User-Agent和更长延迟
            logger.info("备选方案1: 切换User-Agent重试...")
            self._rotate_user_agent()
            time.sleep(random.uniform(30, 60))  # 长时间等待
            
            # 尝试用Selenium访问
            if self.use_selenium and hasattr(self, 'driver') and self.driver:
                archive_url = self.science_archive_urls.get(journal_name, 'https://www.science.org/loi/science')
                articles = self._scrape_with_selenium(archive_url, journal_name, start_date, end_date, max_wait=300)  # 5分钟等待
                
                if articles:
                    logger.info(f"Selenium备选方案成功获取 {len(articles)} 篇文章")
                    return articles
            
            # 备选方案2: 尝试研究页面直接访问
            logger.info("备选方案2: 尝试/research页面...")
            research_url = f"https://www.science.org/journal/{journal_name.lower().replace(' ', '')}/research"
            research_articles = self._try_research_page(research_url, journal_name, start_date, end_date)
            if research_articles:
                articles.extend(research_articles)
            
            # 备选方案3: 延长等待时间后重试
            if not articles:
                logger.info("备选方案3: 长时间等待后重试...")
                time.sleep(random.uniform(120, 180))  # 2-3分钟等待
                
                # 重试一次主要流程，但使用更保守的参数
                try:
                    articles = self._conservative_science_scrape(journal_name, start_date, end_date)
                except Exception as retry_e:
                    logger.error(f"保守重试也失败: {retry_e}")
                    
        except Exception as e:
            logger.error(f"Science备选方案失败: {e}")
            
        return articles
    
    def _rotate_user_agent(self):
        """轮换User-Agent"""
        if hasattr(self, 'science_user_agents') and len(self.science_user_agents) > 1:
            current_ua = self.session.headers.get('User-Agent', '')
            # 选择一个不同的User-Agent
            available_uas = [ua for ua in self.science_user_agents if ua != current_ua]
            if available_uas:
                new_ua = random.choice(available_uas)
                self.session.headers['User-Agent'] = new_ua
                logger.info(f"已切换User-Agent")
                
                # 如果有Selenium driver，也更新它
                if self.use_selenium and hasattr(self, 'driver') and self.driver:
                    try:
                        self.driver.execute_script(f"Object.defineProperty(navigator, 'userAgent', {{get: function(){{return '{new_ua}'}}}});")
                    except:
                        pass
    
    def _try_research_page(self, research_url: str, journal_name: str, start_date: date, end_date: date):
        """尝试通过research页面获取文章"""
        articles = []
        try:
            logger.info(f"尝试访问研究页面: {research_url}")
            
            # 使用更保守的请求
            time.sleep(random.uniform(10, 20))
            response = self.session.get(research_url, timeout=90)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 查找文章元素
                article_elements = soup.find_all('div', class_='card') or soup.find_all('article')
                logger.info(f"在research页面找到 {len(article_elements)} 个可能的文章元素")
                
                for elem in article_elements[:20]:  # 限制处理数量
                    try:
                        article_data = self._extract_science_article_from_element(elem, journal_name, start_date, end_date)
                        if article_data:
                            articles.append(article_data)
                    except Exception as e:
                        logger.debug(f"解析文章元素失败: {e}")
                        continue
                        
        except Exception as e:
            logger.warning(f"research页面访问失败: {e}")
            
        return articles
    
    def _conservative_science_scrape(self, journal_name: str, start_date: date, end_date: date):
        """保守的Science爬取方法"""
        articles = []
        
        logger.info(f"启动保守爬取模式: {journal_name}")
        
        # 只爬取最近的一年或两年，减少请求量
        current_year = datetime.now().year
        target_years = [current_year]
        if start_date.year < current_year:
            target_years.append(current_year - 1)
            
        archive_url = self.science_archive_urls.get(journal_name, 'https://www.science.org/loi/science')
        
        for year in target_years:
            try:
                logger.info(f"保守模式爬取年份: {year}")
                time.sleep(random.uniform(30, 45))  # 长延迟
                
                # 使用最长等待时间
                year_volumes = self._get_science_year_volumes(archive_url, year, start_date, end_date)
                
                if year_volumes:
                    # 只处理前几个最新的卷次
                    for volume_info in year_volumes[:5]:  # 限制数量
                        try:
                            volume_articles = self._scrape_science_volume_articles(
                                volume_info['url'], journal_name, start_date, end_date
                            )
                            articles.extend(volume_articles)
                            time.sleep(random.uniform(15, 25))  # 更长的卷次间延迟
                        except Exception as ve:
                            logger.warning(f"保守模式卷次爬取失败: {ve}")
                            continue
                            
            except Exception as ye:
                logger.warning(f"保守模式年份爬取失败: {ye}")
                continue
                
        return articles
    
    def _extract_science_article_from_element(self, elem, journal_name: str, start_date: date, end_date: date):
        """从HTML元素中提取Science文章信息"""
        try:
            # 提取标题和链接
            title_elem = elem.find('h3') or elem.find('h2') or elem.find('a')
            if not title_elem:
                return None
                
            title = title_elem.get_text(strip=True)
            if not title:
                return None
                
            # 提取链接
            link_elem = title_elem if title_elem.name == 'a' else title_elem.find('a')
            if not link_elem:
                return None
                
            href = link_elem.get('href', '')
            if not href:
                return None
                
            # 构建完整URL
            if href.startswith('/'):
                full_url = 'https://www.science.org' + href
            elif not href.startswith('http'):
                full_url = 'https://www.science.org/' + href
            else:
                full_url = href
            
            # 提取日期
            article_date = None
            date_elem = elem.find('time') or elem.find(class_=lambda x: x and 'date' in x.lower())
            if date_elem:
                date_text = date_elem.get('datetime') or date_elem.get_text(strip=True)
                try:
                    import dateparser
                    parsed_date = dateparser.parse(date_text)
                    if parsed_date:
                        article_date = parsed_date.date()
                except:
                    pass
            
            # 检查日期范围
            if article_date and not self._is_date_in_range(article_date, start_date, end_date):
                return None
            
            # 提取摘要
            abstract = ""
            abstract_elem = elem.find('p') or elem.find(class_=lambda x: x and ('abstract' in x.lower() or 'summary' in x.lower()))
            if abstract_elem:
                abstract = abstract_elem.get_text(strip=True)[:500]  # 限制长度
            
            return {
                'title': title,
                'url': full_url,
                'abstract': abstract or "未找到摘要",
                'date': article_date or datetime.now().date(),
                'doi': self._extract_doi_from_url(full_url),
                'journal': journal_name,
                'authors': "未找到作者信息"
            }
            
        except Exception as e:
            logger.debug(f"提取Science文章信息失败: {e}")
            return None
    
    def _extract_doi_from_url(self, url: str):
        """从URL中提取DOI"""
        try:
            # Science URL格式通常是 /doi/10.1126/science.xxx 或 /content/xxx
            if '/doi/' in url:
                doi_part = url.split('/doi/')[-1]
                return doi_part.split('?')[0]  # 去掉查询参数
            elif '/content/' in url:
                content_id = url.split('/content/')[-1].split('/')[0]
                return f"science.{content_id}"
            else:
                # 从URL最后一部分生成DOI
                url_id = url.rstrip('/').split('/')[-1]
                return f"science.{url_id}"
        except:
            return "未找到DOI"
    
    def _get_science_year_volumes(self, archive_url: str, year: int, start_date: date, end_date: date):
        """获取Science指定年份的卷次列表，根据日期筛选"""
        volumes = []
        
        try:
            # 根据年份构建URL：d2010.y2015 或 d2020.y2023
            if year >= 2020:
                decade_start = 2020
                year_url = f"{archive_url}/group/d{decade_start}.y{year}"
            else:
                decade_start = 2010  
                year_url = f"{archive_url}/group/d{decade_start}.y{year}"
            
            logger.info(f"获取年份 {year} 的卷次: {year_url}")
            
            # 使用requests获取页面
            response = self.get_page_with_retry(year_url, max_retries=3, timeout=30)
            if not response:
                logger.warning(f"无法访问年份页面: {year_url}")
                return volumes
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 根据HTML结构查找卷次信息
            volume_selectors = [
                'div.col-12.col-sm-3.col-lg-2.mb-4.mb-sm-3',  # 基于提供的HTML结构
                'div.past-issue',
                'a.past-issue--loi'
            ]
            
            volume_elements = []
            for selector in volume_selectors:
                elements = soup.select(selector)
                if elements:
                    logger.info(f"使用选择器 {selector} 找到 {len(elements)} 个卷次元素")
                    volume_elements = elements
                    break
            
            if not volume_elements:
                logger.warning(f"年份 {year} 未找到卷次元素")
                return volumes
            
            # 解析每个卷次
            for volume_elem in volume_elements:
                try:
                    # 提取封面日期
                    date_elem = volume_elem.select_one('.past-issue__content__item--cover-date')
                    if not date_elem:
                        continue
                    
                    date_text = date_elem.get_text(strip=True)  # 如 "22 December"
                    
                    # 解析日期（需要加上年份）
                    try:
                        import dateparser
                        full_date_text = f"{date_text} {year}"
                        parsed_date = dateparser.parse(full_date_text)
                        if parsed_date:
                            volume_date = parsed_date.date()
                            
                            # 检查日期是否在范围内
                            if not self._is_date_in_range(volume_date, start_date, end_date):
                                logger.debug(f"卷次日期 {volume_date} 超出范围，跳过")
                                continue
                            
                            # 提取卷次链接
                            link_elem = volume_elem.select_one('a[href*="/toc/"]')
                            if link_elem:
                                href = link_elem.get('href')
                                volume_url = urljoin('https://www.science.org', href)
                                
                                # 提取卷次标题
                                volume_elem_title = volume_elem.select_one('.past-issue__content__item--volume')
                                issue_elem = volume_elem.select_one('.past-issue__content__item--issue')
                                
                                volume_title = ""
                                if volume_elem_title:
                                    volume_title += volume_elem_title.get_text(strip=True)
                                if issue_elem:
                                    volume_title += " " + issue_elem.get_text(strip=True)
                                
                                volumes.append({
                                    'url': volume_url,
                                    'title': f"{volume_title} ({date_text})",
                                    'date': volume_date,
                                    'cover_date': date_text
                                })
                                
                                logger.debug(f"找到符合条件的卷次: {volume_title} - {volume_date}")
                    
                    except Exception as e:
                        logger.debug(f"解析卷次日期失败: {date_text}, 错误: {e}")
                        continue
                
                except Exception as e:
                    logger.error(f"解析卷次元素失败: {e}")
                    continue
            
            logger.info(f"年份 {year} 共找到 {len(volumes)} 个符合条件的卷次")
            
            # 如果严格范围内没找到卷次，尝试宽松模式（找最近的前后卷次）
            if len(volumes) == 0:
                logger.info(f"年份 {year} 严格范围内无卷次，启用宽松模式寻找最近卷次")
                volumes = self._find_nearest_volumes_science(volume_elements, start_date, end_date, year)
                if volumes:
                    logger.info(f"宽松模式下找到 {len(volumes)} 个最近卷次")
            
        except Exception as e:
            logger.error(f"获取年份 {year} 卷次失败: {e}")
        
        return volumes
    
    def _find_nearest_volumes_science(self, volume_elements, start_date: date, end_date: date, year: int):
        """寻找最接近目标日期范围的Science卷次（宽松模式）"""
        volumes_with_dates = []
        target_center = start_date + (end_date - start_date) / 2  # 目标范围中心点
        
        try:
            for volume_elem in volume_elements:
                date_elem = volume_elem.select_one('.past-issue__content__item--cover-date')
                if not date_elem:
                    continue
                
                date_text = date_elem.get_text(strip=True)
                full_date_text = f"{date_text} {year}"
                
                try:
                    import dateparser
                    parsed_date = dateparser.parse(full_date_text)
                    if parsed_date:
                        volume_date = parsed_date.date()
                        
                        # 计算与目标范围中心的距离
                        distance = abs((volume_date - target_center).days)
                        
                        # 提取卷次链接和标题
                        link_elem = volume_elem.select_one('a[href*="/toc/"]')
                        if link_elem:
                            href = link_elem.get('href')
                            if href:
                                volume_url = urljoin('https://www.science.org', href)
                                
                                # 提取标题
                                title_elem = volume_elem.select_one('.past-issue__content__item--title')
                                volume_title = title_elem.get_text(strip=True) if title_elem else f"Volume (Date: {date_text})"
                                
                                volumes_with_dates.append({
                                    'url': volume_url,
                                    'title': volume_title,
                                    'date': volume_date,
                                    'distance': distance
                                })
                                
                except Exception as e:
                    logger.debug(f"解析卷次日期失败: {date_text}, 错误: {e}")
                    continue
            
            # 按距离排序，选择最近的1-2个卷次
            volumes_with_dates.sort(key=lambda x: x['distance'])
            nearest_volumes = volumes_with_dates[:2]  # 最多选择2个最近的卷次
            
            if nearest_volumes:
                logger.info(f"找到最近卷次: {[v['title'] + ' (' + str(v['date']) + ')' for v in nearest_volumes]}")
                return [{'url': v['url'], 'title': v['title']} for v in nearest_volumes]
            
        except Exception as e:
            logger.error(f"宽松模式寻找最近卷次失败: {e}")
        
        return []
    
    def _scrape_science_volume_articles(self, volume_url: str, journal_name: str, start_date: date, end_date: date):
        """爬取Science指定卷次的文章 - 优化版：先筛选日期再获取详情"""
        articles = []
        
        try:
            logger.info(f"爬取卷次文章: {volume_url}")
            
            # 获取卷次页面
            response = self.get_page_with_retry(volume_url, max_retries=3, timeout=30)
            if not response:
                logger.warning(f"无法访问卷次页面: {volume_url}")
                return articles
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找所有section（文章分组）
            sections = soup.select('section.toc__section.mt-lg-2_5x.mt-2x')
            logger.info(f"找到 {len(sections)} 个文章分组")
            
            # 第一步：收集所有文章链接和基本信息，进行初步日期筛选
            candidate_articles = []
            
            for section in sections:
                # 查找文章标题和链接
                article_links = section.select('h3.article-title a.sans-serif.text-reset.animation-underline')
                
                for link_elem in article_links:
                    try:
                        href = link_elem.get('href')
                        if href and '/doi/' in href:
                            # 构建完整的文章URL
                            article_url = urljoin('https://www.science.org', href)
                            title = link_elem.get_text(strip=True)
                            
                            # 尝试从卷次页面获取文章的发表日期
                            article_date = None
                            
                            # 查找文章对应的日期信息
                            parent_section = link_elem.find_parent('section')
                            if parent_section:
                                # 查找日期元素
                                date_elems = parent_section.select('time, .pub-date, .article-date, .date')
                                for date_elem in date_elems:
                                    date_text = date_elem.get('datetime') or date_elem.get_text(strip=True)
                                    if date_text:
                                        try:
                                            from dateutil import parser as dateparser
                                            article_date = dateparser.parse(date_text).date()
                                            break
                                        except:
                                            continue
                            
                            # 如果能够在列表页面确定日期且不在范围内，直接跳过
                            if article_date and not self._is_date_in_range(article_date, start_date, end_date):
                                logger.debug(f"文章 {title[:50]} 日期 {article_date} 超出范围，跳过详情获取")
                                continue
                            
                            # 添加到候选列表
                            candidate_articles.append({
                                'url': article_url,
                                'title': title,
                                'preliminary_date': article_date
                            })
                                    
                    except Exception as e:
                        logger.error(f"处理文章链接失败: {e}")
                        continue
            
            logger.info(f"经过初步筛选，需要获取详情的文章数: {len(candidate_articles)}")
            
            # 第二步：只对通过初步筛选的文章获取详细信息
            for candidate in candidate_articles:
                try:
                    # 获取文章详细信息
                    article_details = self._get_science_article_details(candidate['url'])
                    if article_details:
                        # 使用详情页面的精确日期进行最终筛选
                        article_date = article_details.get('date')
                        if article_date and self._is_date_in_range(article_date, start_date, end_date):
                            article_details['journal'] = journal_name
                            articles.append(article_details)
                            logger.info(f"Science文章: {article_details.get('title', 'Unknown')[:80]}")
                        else:
                            logger.debug(f"文章日期 {article_date} 超出范围，跳过")
                    
                    # 添加延迟
                    time.sleep(random.uniform(1, 2))
                            
                except Exception as e:
                    logger.error(f"获取文章详情失败: {e}")
                    continue
                        
            logger.info(f"卷次 {volume_url} 共获得 {len(articles)} 篇符合条件的文章")
                            
        except Exception as e:
            logger.error(f"爬取卷次文章失败: {e}")
            
        return articles
    
    def _scrape_with_selenium(self, url, journal_name, start_date, end_date, max_wait=180):
        """使用Selenium爬取Science期刊 - Science默认3分钟等待"""
        articles = []
        
        # Science期刊需要访问/research路径来获取文章列表
        if not url.endswith('/research'):
            url = url.rstrip('/') + '/research'
        logger.info(f"Selenium访问Science URL: {url}")
        
        try:
            self.driver.get(url)
            
            # 使用改进的等待机制处理反爬虫页面 - 使用传入的max_wait时间
            if not self.wait_for_page_load(self.driver, max_wait=max_wait):
                logger.error(f"Science页面加载失败或超时 ({max_wait}秒)")
                return []
            
            logger.info(f"Selenium成功访问Science: {url}")
            
            # 使用Selenium解析页面
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            article_elements = soup.find_all('div', class_='card')
            if not article_elements:
                # 备选选择器
                article_elements = soup.select('.search-result__body .card')
            logger.info(f"Selenium找到 {len(article_elements)} 个Science文章元素")
            
            for article_elem in article_elements:
                try:
                    link_elem = article_elem.find('a', href=True)
                    if link_elem:
                        href = link_elem.get('href')
                        full_url = urljoin(url, href)
                        
                        # 获取标题 - 使用Science的正确选择器
                        title_elem = article_elem.find('h2', class_='article-title')
                        if not title_elem:
                            title_elem = article_elem.find(['h1', 'h2', 'h3'])
                        title = title_elem.get_text(strip=True) if title_elem else ''
                        
                        if title and not re.match(r'(download|pdf|view|read)', title, re.I):
                            # 解析发表日期
                            pub_date = datetime.now().date()
                            time_tag = article_elem.find('time')
                            if time_tag:
                                raw_date = time_tag.get('datetime', time_tag.get_text(strip=True))
                                try:
                                    pub_date = dateparser.parse(raw_date).date()
                                except:
                                    pass
                            
                            article = {
                                'title': title,
                                'abstract': '',
                                'doi': '',
                                'url': full_url,
                                'date': pub_date,
                                'journal': journal_name,
                                'authors': ''
                            }
                            
                            # 时间范围过滤
                            if self._is_date_in_range(pub_date, start_date, end_date):
                                articles.append(article)
                            
                except Exception as e:
                    logger.error(f"Selenium解析Science文章失败: {e}")
                    continue
                
                # 移除所有数量限制，处理所有符合时间要求的文章
                    
        except Exception as e:
            logger.error(f"Selenium爬取Science失败: {e}")
        
        return articles
    
    def _get_science_article_details(self, url: str):
        """获取Science文章详细信息 - 基于实际HTML结构优化"""
        try:
            response = self.get_page_with_retry(url, max_retries=3, timeout=30)
            if not response:
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 标题: 多种选择器确保获取成功
            title = ''
            title_selectors = [
                'h1[property="name"]',  # 基于截图的实际结构
                'h1.article-title',
                'h1',
                '.article-title'
            ]
            
            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    break
            
            # 摘要: 多种选择器
            abstract = ''
            abstract_selectors = [
                'section#abstract[property="abstract"]',  # 基于截图
                'div#abstracts',
                'section[role="doc-abstract"]',
                'div.abstractContent',
                '.abstract-content'
            ]
            
            for selector in abstract_selectors:
                abstract_elem = soup.select_one(selector)
                if abstract_elem:
                    abstract = abstract_elem.get_text(strip=True)
                    break
            
            # 作者信息: 多种选择器
            authors = ''
            authors_selectors = [
                'div.contributors',  # 基于截图
                'div.core-authors',
                '.author-list',
                'meta[name="citation_author"]',
                '.hlFld-ContribAuthor'  # 补充的选择器
            ]
            
            for selector in authors_selectors:
                if selector.startswith('meta'):
                    # 处理meta标签
                    author_metas = soup.find_all('meta', attrs={'name': 'citation_author'})
                    if author_metas:
                        authors = '; '.join([meta.get('content', '') for meta in author_metas])
                        break
                elif selector == '.hlFld-ContribAuthor':
                    # 处理Science特有的作者选择器 - 补充选择器
                    author_elems = soup.select(selector)
                    if author_elems:
                        author_names = []
                        for auth_elem in author_elems:
                            author_name = auth_elem.get_text(strip=True)
                            if author_name and author_name not in author_names:
                                # 排除无效的作者名
                                if author_name.lower() not in ['by', 'and', '+31 authors', '+authors', 'authors']:
                                    author_names.append(author_name)
                        
                        if author_names:
                            authors = ', '.join(author_names[:20])  # 最多显示20个作者
                        break
                else:
                    authors_elem = soup.select_one(selector)
                    if authors_elem:
                        author_links = authors_elem.find_all('a')
                        if author_links:
                            # 过滤掉纯URL的链接，只保留作者姓名
                            author_names = []
                            for link in author_links:
                                text = link.get_text(strip=True)
                                # 跳过以http开头的纯URL链接
                                if not text.startswith('http'):
                                    author_names.append(text)
                            
                            if author_names:
                                authors = '; '.join(author_names)
                            else:
                                # 如果没找到有效的作者链接，回退到整个元素文本并清理URL
                                import re
                                full_text = authors_elem.get_text(strip=True)
                                authors = re.sub(r'https?://[^\s;]+', '', full_text)
                                authors = re.sub(r';\s*;', ';', authors)
                                authors = authors.strip().rstrip(';')
                        else:
                            authors = authors_elem.get_text(strip=True)
                        
                        # 清理作者信息，移除常见的无关文本
                        if authors:
                            import re
                            # 移除ORCID链接
                            authors = re.sub(r'https?://orcid\.org/[0-9\-X]+', '', authors)
                            # 移除常见无关文本
                            authors = re.sub(r'Authors?\s*Info\s*&?\s*Affiliations?', '', authors, flags=re.IGNORECASE)
                            authors = re.sub(r'View\s*ORCID\s*Profile', '', authors, flags=re.IGNORECASE)
                            # 清理多余的分号和空格
                            authors = re.sub(r';\s*;+', ';', authors)
                            authors = re.sub(r'^\s*;\s*|\s*;\s*$', '', authors)
                            authors = re.sub(r'\s+', ' ', authors)
                            authors = authors.strip()
                        
                        break
            
            # DOI信息: 多种方式获取
            doi = ''
            
            # 方法1: 从property="sameAs"的链接中提取
            doi_link = soup.find('a', {'property': 'sameAs', 'href': True})
            if doi_link and 'doi.org' in doi_link.get('href', ''):
                doi_url = doi_link.get('href')
                if '/10.' in doi_url:
                    doi = doi_url.split('/10.')[-1]
                    doi = '10.' + doi
                    logger.info(f"从sameAs链接提取DOI: {doi}")
            
            # 方法2: 从DOI文本中提取
            if not doi:
                doi_selectors = [
                    'div.doi',
                    '.doi-link',
                    'a[href*="doi.org"]'
                ]
                
                for selector in doi_selectors:
                    doi_elem = soup.select_one(selector)
                    if doi_elem:
                        doi_text = doi_elem.get_text(strip=True)
                        if 'doi:' in doi_text.lower():
                            doi = doi_text.split('doi:')[-1].strip()
                        elif '10.' in doi_text:
                            # 提取DOI号码
                            import re
                            doi_match = re.search(r'10\.\d+/[^\s]+', doi_text)
                            if doi_match:
                                doi = doi_match.group()
                        break
            
            # 方法3: 从meta标签获取
            if not doi:
                doi_meta = soup.find('meta', attrs={'name': 'citation_doi'})
                if doi_meta:
                    doi = doi_meta.get('content', '')
            
            # 发表日期: 基于截图的实际结构
            pub_date = datetime.now().date()
            date_selectors = [
                'span[property="datePublished"]',  # 基于截图
                '.core-date-published span',
                'time[datetime]',
                'meta[name="citation_publication_date"]'
            ]
            
            for selector in date_selectors:
                if selector.startswith('meta'):
                    date_meta = soup.find('meta', attrs={'name': 'citation_publication_date'})
                    if date_meta:
                        date_text = date_meta.get('content', '')
                else:
                    date_elem = soup.select_one(selector)
                    if date_elem:
                        date_text = date_elem.get('datetime') or date_elem.get_text(strip=True)
                        
                        if date_text:
                            try:
                                pub_date = dateparser.parse(date_text).date()
                                break
                            except:
                                continue
            
            # 添加详细日志记录验证信息提取
            logger.info(f"Science文章信息提取完成:")
            logger.info(f"  标题: {title[:100]}{'...' if len(title) > 100 else ''}")
            logger.info(f"  摘要: {abstract[:100]}{'...' if len(abstract) > 100 else ''}")
            logger.info(f"  DOI: {doi}")
            logger.info(f"  作者: {authors[:100]}{'...' if len(authors) > 100 else ''}")
            logger.info(f"  日期: {pub_date}")
            
            # 构建正确的Science文章URL
            science_url = url
            if doi and not url.startswith('https://www.science.org/doi/'):
                # 如果有DOI，构建标准的Science DOI URL
                science_url = f"https://www.science.org/doi/{doi}"
                logger.info(f"构建Science DOI URL: {science_url}")
            
            return {
                'title': title,
                'abstract': abstract,
                'doi': doi,
                'url': science_url,  # 使用正确的URL
                'date': pub_date,
                'authors': authors
            }
            
        except Exception as e:
            logger.error(f"获取Science文章详情失败: {e}")
            return None
    
    def _close_selenium_driver(self):
        """关闭Selenium WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Science Selenium WebDriver已关闭")
            except Exception as e:
                logger.error(f"关闭Science Selenium WebDriver失败: {e}")
            finally:
                self.driver = None
    
    def close(self):
        """关闭资源"""
        self._close_selenium_driver()
        
        if self.session:
            try:
                self.session.close()
                logger.info("Science Requests session已关闭")
            except Exception as e:
                logger.error(f"关闭Science requests session失败: {e}")

class CellParser(BaseParser):
    """Cell期刊解析器 - 基于Cell目录成功实现的架构"""
    
    def __init__(self, database=None, paper_agent=None):
        super().__init__('cell', database, paper_agent, use_selenium=True)
        
        # 初始化失败期刊记录
        self.failed_journals = []
        
        # 初始化失败期刊管理器
        try:
            from .tools.failed_journals_manager import FailedJournalsManager
        except ImportError:
            from tools.failed_journals_manager import FailedJournalsManager
        self.failed_manager = FailedJournalsManager('cell')
        
        # 动态更新期刊配置（每次启动时检查）
        self._update_cell_journals_if_needed()
        
        # 加载is_journal配置
        self.is_journal_config = self._load_is_journal_config('cell')
        
        # Cell专用的User-Agent列表，优先使用最新的
        self.cell_user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',  # 最优先使用
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0',  # 次优先
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
        ]
        
        # 初始化动态期刊URL列表
        self.cell_journal_urls = {}
        self._update_cell_journal_urls()
    
    def _update_cell_journal_urls(self):
        """动态获取Cell子刊URL列表，每次爬虫执行时更新JSON配置"""
        import json
        import os
        import time as time_module
        
        start_time = time_module.time()
        timeout_seconds = 300  # 5分钟超时
        
        try:
            logger.info("Cell爬虫开始动态获取子刊URL...")
            
            # 使用重试机制获取主页
            response = self._get_page_with_retry('https://www.cell.com/')
            if not response:
                logger.warning("无法访问Cell主页，使用现有JSON配置")
                self._load_existing_json_config()
                return
            
            # 检查超时
            if time_module.time() - start_time > timeout_seconds:
                logger.warning("Cell动态更新超时，使用现有JSON配置")
                self._load_existing_json_config()
                return
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找子刊链接，格式：<a alt="Cell" href="/cell/home">Cell</a>
            journal_links = soup.find_all('a', href=True)
            valid_journals = {}
            failed_journals = []
            
            logger.info(f"找到 {len(journal_links)} 个链接，开始筛选Cell子刊...")
            
            # 限制处理的链接数量，避免过度处理
            processed_count = 0
            max_process_count = 100  # 最多处理100个链接
            
            for link in journal_links:
                # 检查超时
                if time_module.time() - start_time > timeout_seconds:
                    logger.warning("Cell动态更新处理超时，停止处理")
                    break
                    
                if processed_count >= max_process_count:
                    logger.info(f"已处理{max_process_count}个链接，停止处理以避免过度消耗资源")
                    break
                href = link.get('href', '')
                alt_text = link.get('alt', '')
                link_text = link.get_text(strip=True)
                
                # 查找模式：/xxx/home 的链接
                if href.startswith('/') and href.endswith('/home'):
                    processed_count += 1
                    journal_path = href.replace('/home', '').strip('/')
                    # 构建issues URL（home改为issues，这是年份-卷次页面）
                    issues_url = f"https://www.cell.com/{journal_path}/issues"
                    
                    # 使用alt属性、链接文本或路径作为期刊名称
                    journal_name = alt_text or link_text or journal_path
                    
                    if journal_name:
                        # 使用轻量级HEAD请求检查
                        try:
                            # 禁用SSL警告
                            import urllib3
                            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                            
                            check_response = self.session.head(issues_url, timeout=10, verify=False)
                            if check_response.status_code == 200:
                                valid_journals[journal_name] = issues_url
                                logger.debug(f"找到有效Cell子刊: {journal_name}")
                            elif check_response.status_code == 404:
                                failed_journals.append({
                                    'name': journal_name,
                                    'url': issues_url,
                                    'reason': '404 Not Found'
                                })
                                logger.debug(f"Cell子刊404: {journal_name} -> {issues_url}")
                            else:
                                failed_journals.append({
                                    'name': journal_name,
                                    'url': issues_url,
                                    'reason': f'HTTP {check_response.status_code}'
                                })
                        except Exception as check_error:
                            failed_journals.append({
                                'name': journal_name,
                                'url': issues_url,
                                'reason': str(check_error)
                            })
            
            # 检查动态获取结果的质量
            if not valid_journals or len(valid_journals) <= 50:
                if not valid_journals:
                    logger.warning("动态获取结果为空，使用现有JSON配置")
                else:
                    logger.warning(f"动态获取结果数量不足（{len(valid_journals)} <= 50），使用现有JSON配置")
                self._load_existing_json_config()
                return
            
            # 动态获取成功且数量充足，更新配置
            logger.info(f"动态获取成功，获得{len(valid_journals)}个有效期刊（>50），更新JSON配置")
            self.cell_journal_urls = valid_journals
            
            # 写入JSON文件（转换为/home格式）
            self._update_cell_journals_json(valid_journals, failed_journals)
            
        except Exception as e:
            logger.error(f"Cell子刊动态获取异常: {e}")
            logger.info("回退到现有JSON配置")
            self._load_existing_json_config()
    
    def _load_existing_json_config(self):
        """加载现有的JSON配置作为回退"""
        import json
        import os
        
        try:
            config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'journals_config/cell_journals.json')
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    journal_list = json.load(f)
                
                # 转换为issues URL格式
                self.cell_journal_urls = {}
                for item in journal_list:
                    name = item.get('name', '')
                    link = item.get('link', '')
                    if name and link:
                        # 将/home转换为/issues
                        issues_url = link.replace('/home', '/issues')
                        self.cell_journal_urls[name] = issues_url
                
                logger.info(f"加载现有JSON配置成功: {len(self.cell_journal_urls)} 个期刊")
            else:
                logger.warning("未找到cell_journals.json，使用硬编码配置")
                self._use_hardcoded_config()
                
        except Exception as e:
            logger.error(f"加载JSON配置失败: {e}，使用硬编码配置")
            self._use_hardcoded_config()
    
    def _use_hardcoded_config(self):
        """使用硬编码的期刊配置"""
        self.cell_journal_urls = {
            'Cell': 'https://www.cell.com/cell/issues',
            'Cancer Cell': 'https://www.cell.com/cancer-cell/issues',
            'Cell Metabolism': 'https://www.cell.com/cell-metabolism/issues',
            'Developmental Cell': 'https://www.cell.com/developmental-cell/issues',
            'Immunity': 'https://www.cell.com/immunity/issues',
            'Molecular Cell': 'https://www.cell.com/molecular-cell/issues',
            'Neuron': 'https://www.cell.com/neuron/issues',
            'Structure': 'https://www.cell.com/structure/issues'
        }
        logger.info(f"使用硬编码配置: {len(self.cell_journal_urls)} 个期刊")
    
    def _update_cell_journals_json(self, valid_journals, failed_journals):
        """更新cell_journals.json配置文件"""
        import json
        import os
        from datetime import datetime
        
        try:
            # 转换为/home格式的配置
            journal_list = []
            for name, issues_url in valid_journals.items():
                home_url = issues_url.replace('/issues', '/home')
                journal_list.append({
                    "name": name,
                    "link": home_url
                })
            
            # 按名称排序
            journal_list.sort(key=lambda x: x['name'])
            
            # 写入配置文件
            config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'journals_config/cell_journals.json')
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(journal_list, f, ensure_ascii=False, indent=4)
            
            # 使用智能更新器保存筛选期刊到动态文件
            self._save_cell_journals_to_json(valid_journals, failed_journals)
            
        except Exception as e:
            logger.error(f"更新cell_journals.json失败: {e}")
    
    def _save_cell_journals_to_json(self, valid_journals, failed_journals):
        """将动态获取的Cell期刊信息保存到JSON文件"""
        try:
            import json
            import os
            from datetime import datetime
            
            # 构建数据结构
            # 转换为期刊列表格式
            journal_list = []
            for name, issues_url in valid_journals.items():
                # 将issues URL转换为home URL以匹配静态文件格式
                home_url = issues_url.replace('/issues', '/home')
                journal_list.append({
                    "name": name,
                    "link": home_url
                })
            
            # 使用智能更新器：只更新筛选期刊的链接，不添加新期刊
            try:
                from tools.smart_journal_updater import SmartJournalUpdater
                updater = SmartJournalUpdater(base_dir=os.path.dirname(__file__))
                success = updater.update_cell_journals(journal_list)
                if success:
                    pass  # 智能更新器会输出详细信息
                else:
                    logger.warning("智能更新失败，保留现有筛选配置不变")
            except Exception as e:
                # 如果导入或执行失败，保留现有配置不变
                logger.warning(f"智能更新器异常: {e}，保留现有筛选配置不变")
            
        except Exception as e:
            logger.error(f"保存Cell期刊JSON文件失败: {e}")
    
    def _init_cell_selenium_driver(self):
        """初始化Cell专用的Selenium WebDriver，使用最新的User-Agent和增加等待时间"""
        if not SELENIUM_AVAILABLE:
            logger.warning("Selenium不可用，回退到requests方式")
            self.use_selenium = False
            return
        
        try:
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            # 配置Chrome选项 - Cell专用
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument(f'--user-agent={self.cell_user_agents[0]}')  # 使用最新的User-Agent
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            
            # 减少日志输出
            chrome_options.add_argument('--disable-logging')
            chrome_options.add_argument('--log-level=3')
            chrome_options.add_argument('--silent')
            
            # 初始化WebDriver - 使用Selenium自动下载（参考paperagent1.4的方式）
            try:
                logger.info("Cell: 使用Selenium自动下载chromedriver启动（可能需要等待）")
                self.driver = webdriver.Chrome(options=chrome_options)
                logger.info("Cell Selenium WebDriver初始化成功(自动下载)")
            except Exception as e:
                logger.error(f"Cell Chrome驱动自动下载失败: {e}")
                raise Exception(f"Cell Chrome驱动初始化失败: {e}")
                
        except Exception as e:
            logger.error(f"Cell Selenium初始化失败: {e}")
            self.use_selenium = False
            self.driver = None
    
    def scrape_journal(self, journal_name: str, base_url: str, start_date: datetime, end_date: datetime):
        """爬取Cell期刊数据 - 使用Cell目录的成功策略"""
        logger.info(f"开始爬取Cell期刊: {journal_name}")
        articles = []
        
        try:
            # 处理日期格式
            if isinstance(start_date, datetime):
                start_date = start_date.date()
            if isinstance(end_date, datetime):
                end_date = end_date.date()
            
            # 第1步：构造Archive页面URL - /issues
            # 构造Archive页面URL - 优先issues，失败时回退到archive
            primary_url = base_url.replace('/home', '/issues')
            logger.info(f"正在访问Archive页面（优先issues）: {primary_url}")
            
            # 确保使用最新的User-Agent
            self.session.headers['User-Agent'] = self.cell_user_agents[0]
            
            # 第2步：获取所有期次链接，支持issues到archive回退
            issue_links, access_error = self._extract_volume_issue_links_with_fallback(primary_url, base_url, start_date, end_date)
            if not issue_links:
                if access_error and ('403' in str(access_error) or 'Forbidden' in str(access_error)):
                    # 只有真正的403错误才记录为失败
                    logger.warning(f"403访问错误，记录失败期刊: {journal_name}")
                    reason = f'403访问被拒绝: {access_error}'
                    self.failed_manager.add_failed_journal(journal_name, base_url, reason)
                    self.failed_journals.append({
                        'journal_name': journal_name,
                        'url': base_url,
                        'reason': reason
                    })
                else:
                    # 时间范围导致的0篇文章，不算失败
                    logger.info(f"时间范围内未找到期次或文章: {journal_name}（不算失败）")
                return []
            
            logger.info(f"找到 {len(issue_links)} 个期次，开始逐一爬取")
            
            # 第3步：遍历每个期次，获取文章
            for i, issue_info in enumerate(issue_links, 1):
                try:
                    issue_title = issue_info['title']
                    issue_url = urljoin('https://www.cell.com', issue_info['url'])
                    
                    logger.info(f"正在爬取期次 {i}/{len(issue_links)}: {issue_title}")
                    
                    # 提取期次文章
                    issue_articles = self._extract_articles_from_issue(issue_url, journal_name, start_date, end_date)
                    
                    if issue_articles:
                        logger.info(f"期次 {issue_title} 提取了 {len(issue_articles)} 篇文章")
                        articles.extend(issue_articles)
                    else:
                        logger.warning(f"期次 {issue_title} 未找到文章")
                    
                    # 添加延迟，模拟人类行为 - 增加等待时间确保稳定性
                    time.sleep(random.uniform(3, 6))
                        
                except Exception as e:
                    logger.error(f"爬取期次失败: {issue_title}, 错误: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"Cell期刊爬取失败: {e}")
        
        logger.info(f"Cell {journal_name}爬取完成，获得{len(articles)}篇文章")
        
        # 输出失败期刊信息
        if hasattr(self, 'failed_journals') and self.failed_journals:
            logger.warning(f"Cell爬取过程中有 {len(self.failed_journals)} 个期刊失败：")
            for failed_journal in self.failed_journals:
                logger.warning(f"  - {failed_journal['journal_name']}: {failed_journal['reason']}")
        
        return articles
    
    def retry_failed_journals(self, start_date: datetime, end_date: datetime, retry_timeout: int = 300):
        """重试失败的期刊，等待时间更长"""
        failed_journals = self.failed_manager.get_failed_journals()
        
        if not failed_journals:
            logger.info("没有失败的Cell期刊需要重试")
            return []
        
        logger.info(f"开始重试 {len(failed_journals)} 个失败的Cell期刊，超时时间: {retry_timeout}秒")
        retry_articles = []
        
        for journal_record in failed_journals:
            journal_name = journal_record['journal_name']
            base_url = journal_record['url']
            
            logger.info(f"重试失败期刊: {journal_name}")
            
            try:
                # 更新重试信息
                self.failed_manager.update_retry_info(journal_name)
                
                # 使用更长的超时时间重试
                articles = self._retry_single_journal(journal_name, base_url, start_date, end_date, retry_timeout)
                
                if articles:
                    logger.info(f"重试成功: {journal_name}，获得 {len(articles)} 篇文章")
                    retry_articles.extend(articles)
                    # 从失败列表中移除成功的期刊
                    self.failed_manager.remove_successful_journal(journal_name)
                else:
                    logger.warning(f"重试仍然失败: {journal_name}")
                    
            except Exception as e:
                logger.error(f"重试期刊 {journal_name} 时出错: {e}")
        
        logger.info(f"重试完成，获得 {len(retry_articles)} 篇新文章")
        return retry_articles
    
    def _retry_single_journal(self, journal_name: str, base_url: str, start_date: datetime, end_date: datetime, timeout: int):
        """重试单个期刊，使用更长超时时间"""
        articles = []
        
        try:
            # 构造Archive页面URL - 优先issues，失败时回退到archive
            primary_url = base_url.replace('/home', '/issues')
            
            # 使用更长的超时时间获取期次链接
            logger.info(f"重试获取期次链接: {primary_url} (超时: {timeout}秒)")
            issue_links = self._extract_volume_issue_links_with_fallback_retry(primary_url, base_url, start_date, end_date, timeout)
            
            if not issue_links:
                logger.warning(f"重试获取期次链接仍然失败: {journal_name}")
                return []
            
            logger.info(f"重试成功获取 {len(issue_links)} 个期次，开始爬取")
            
            # 遍历每个期次，获取文章
            for i, issue_info in enumerate(issue_links, 1):
                try:
                    logger.info(f"正在爬取期次 {i}/{len(issue_links)}: {issue_info['title']}")
                    issue_articles = self._extract_articles_from_issue_retry(issue_info['url'], start_date, end_date, timeout)
                    articles.extend(issue_articles)
                    
                    # 重试时使用更长的延迟
                    if i < len(issue_links):
                        delay = random.uniform(8, 15)  # 更长的延迟
                        logger.info(f"重试期次间延迟 {delay:.1f} 秒...")
                        time.sleep(delay)
                        
                except Exception as e:
                    logger.error(f"重试爬取期次失败: {issue_info['title']} - {e}")
                    continue
            
        except Exception as e:
            logger.error(f"重试期刊 {journal_name} 失败: {e}")
        
        return articles
    
    def _extract_volume_issue_links_with_fallback_retry(self, primary_url, base_url, start_date, end_date, timeout):
        """支持重试的卷期链接提取，使用更长超时"""
        urls_to_try = [
            primary_url,  # /issues
            base_url.replace('/home', '/archive'),  # /archive
            base_url.replace('/home', '/archive') + '?isCoverWidget=true'  # /archive?isCoverWidget=true
        ]
        
        for i, url in enumerate(urls_to_try):
            logger.info(f"重试第{i+1}个URL: {url}")
            issue_links = self._extract_volume_issue_links_retry(url, start_date, end_date, timeout)
            if issue_links:
                logger.info(f"重试URL成功，获取到{len(issue_links)}个期次链接: {url}")
                return issue_links
            else:
                logger.warning(f"重试URL无结果: {url}")
        
        logger.error("重试所有URL都失败，无法获取期次链接")
        return []
    
    def _extract_volume_issue_links_retry(self, url, start_date, end_date, timeout):
        """重试版本的期次链接提取，使用更长超时"""
        try:
            response = self.session.get(url, timeout=timeout)
            if response.status_code != 200:
                return []
            
            return self._parse_issue_links_from_response(response, start_date, end_date)
            
        except Exception as e:
            logger.error(f"重试提取期次链接失败: {e}")
            return []
    
    def _extract_articles_from_issue_retry(self, issue_url, start_date, end_date, timeout):
        """重试版本的文章提取，使用更长超时"""
        try:
            response = self.session.get(issue_url, timeout=timeout)
            if response.status_code != 200:
                return []
            
            # 这里可以调用现有的文章解析逻辑
            return self._parse_articles_from_issue_page(response, start_date, end_date)
            
        except Exception as e:
            logger.error(f"重试提取文章失败: {e}")
            return []
    
    def _extract_volume_issue_links_with_fallback(self, primary_url, base_url, start_date=None, end_date=None):
        """支持issues到archive回退的卷期链接提取，返回(链接列表, 错误信息)"""
        # 尝试顺序：issues -> archive -> archive?isCoverWidget=true
        urls_to_try = [
            primary_url,  # /issues
            base_url.replace('/home', '/archive'),  # /archive
            base_url.replace('/home', '/archive') + '?isCoverWidget=true'  # /archive?isCoverWidget=true
        ]
        
        last_error = None
        
        for i, url in enumerate(urls_to_try):
            logger.info(f"尝试第{i+1}个URL: {url}")
            try:
                issue_links = self._extract_volume_issue_links(url, start_date, end_date)
                if issue_links:
                    logger.info(f"URL成功，获取到{len(issue_links)}个期次链接: {url}")
                    return issue_links, None
                else:
                    logger.warning(f"URL无结果: {url}")
            except Exception as e:
                last_error = e
                if '403' in str(e) or 'Forbidden' in str(e):
                    logger.error(f"403访问错误: {url} - {e}")
                    return [], e  # 立即返回403错误
                else:
                    logger.warning(f"URL访问异常: {url} - {e}")
        
        logger.error("所有URL都失败，无法获取期次链接")
        return [], last_error
    
    def _extract_volume_issue_links(self, archive_url, start_date=None, end_date=None):
        """从Archive页面提取年份/卷期链接 - 基于Cell目录的成功实现，包含Selenium备选
        
        Args:
            archive_url: Archive页面URL
            start_date: 开始日期，用于年份筛选
            end_date: 结束日期，用于年份筛选
        """
        logger.info(f"正在提取 {archive_url} 的卷期链接...")
        
        # 第一阶段：优先使用requests，并检测403错误
        try:
            response = self._get_page_with_retry(archive_url)
            if not response:
                # 404回退逻辑：尝试带?isCoverWidget=true参数的URL
                if '?' not in archive_url:
                    fallback_url = f"{archive_url}?isCoverWidget=true"
                    logger.info(f"原始URL失败，尝试回退URL: {fallback_url}")
                    response = self._get_page_with_retry(fallback_url)
                    
                    if response:
                        logger.info(f"回退URL成功: {fallback_url}")
                    else:
                        logger.warning("requests和Selenium都无法获取Archive页面（包括回退URL）")
                        return []
                else:
                    logger.warning("requests和Selenium都无法获取Archive页面")
                    return []
        except Exception as e:
            # 如果是403错误，向上传播
            if '403' in str(e) or 'Forbidden' in str(e):
                raise e
            logger.warning(f"访问页面出错: {e}")
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        volume_issue_links = []
        
        # 根据Cell目录成功实现的选择器
        issue_link_selectors = [
            'ul.list-of-issues__list li a',  # Cell目录验证过的选择器
            '.list-of-issues__list a',
            'a[href*="/issue?pii="]',  # Cell期次链接的特征
            'a[href*="/issue"]'
        ]
        
        # 调试：输出页面的基本信息
        page_title = soup.find('title')
        if page_title:
            logger.info(f"Archive页面标题: {page_title.get_text(strip=True)}")
        
        # 调试：查找所有可能的issue链接
        all_links = soup.find_all('a', href=True)
        issue_related_links = [link for link in all_links if 'issue' in link.get('href', '').lower()]
        logger.info(f"页面总共{len(all_links)}个链接，其中{len(issue_related_links)}个包含'issue'")
        
        # 调试：输出前5个issue相关链接
        if issue_related_links:
            sample_issue_links = issue_related_links[:5]
            for i, link in enumerate(sample_issue_links):
                logger.info(f"Issue链接示例{i+1}: {link.get('href', '')} -> {link.get_text(strip=True)[:50]}")
        
        # 首先进行年份筛选 - 提取Volume信息
        volume_sections = soup.find_all(['h2', 'h3', 'div'], string=lambda text: text and 'Volume' in text and '(' in text and ')' in text)
        valid_years = set()
        
        if start_date and end_date:
            target_years = set(range(start_date.year, end_date.year + 1))
            logger.info(f"目标年份范围: {min(target_years)} - {max(target_years)}")
            
            for volume_element in volume_sections:
                volume_text = volume_element.get_text(strip=True) if volume_element else ""
                # 匹配 "Volume 37 (2025)" 格式
                year_match = re.search(r'Volume\s+\d+\s*\((\d{4})\)', volume_text)
                if year_match:
                    year = int(year_match.group(1))
                    if year in target_years:
                        valid_years.add(year)
                        logger.info(f"年份 {year} 符合条件，将处理该卷的期次")
                    else:
                        logger.info(f"年份 {year} 超出范围 {min(target_years)}-{max(target_years)}，跳过")
        
        # 完全照搬cell目录成功的选择器处理逻辑，但增加日期筛选
        all_found_links = []  # 保存所有找到的链接，用于宽松模式
        for selector in issue_link_selectors:
            try:
                links = soup.select(selector)
                if links:
                    logger.info(f"使用选择器 {selector} 找到 {len(links)} 个期次链接")
                    all_found_links = links  # 保存所有找到的链接
                    for link in links:
                        href = link.get('href', '')
                        spans = link.select('span')
                        if href and spans:
                            # 提取期次信息：Issue X, Date, Pages
                            issue_text = ' '.join([span.get_text(strip=True) for span in spans])
                            
                            # 日期筛选优化：从span中查找日期信息
                            should_include = True
                            if start_date and end_date and spans:
                                for span in spans:
                                    span_text = span.get_text(strip=True)
                                    # 查找日期模式（如 "September 02, 2025"）
                                    date_match = re.search(r'(\w+)\s+(\d{1,2}),\s+(\d{4})', span_text)
                                    if date_match:
                                        try:
                                            month_name, day, year = date_match.groups()
                                            # 使用dateparser解析日期
                                            import dateparser
                                            parsed_date = dateparser.parse(f"{month_name} {day}, {year}")
                                            if parsed_date:
                                                issue_date = parsed_date.date()
                                                # 检查日期是否在范围内
                                                if issue_date < start_date:
                                                    logger.debug(f"期次 {issue_text} 日期 {issue_date} 早于开始日期 {start_date}，跳过")
                                                    should_include = False
                                                elif issue_date > end_date:
                                                    logger.debug(f"期次 {issue_text} 日期 {issue_date} 晚于结束日期 {end_date}，跳过")
                                                    should_include = False
                                                else:
                                                    logger.debug(f"期次 {issue_text} 日期 {issue_date} 在范围内")
                                                break
                                        except Exception as e:
                                            logger.debug(f"解析期次日期失败: {span_text}, 错误: {e}")
                            
                            if should_include:
                                volume_issue_links.append({
                                    'title': issue_text,
                                    'url': href
                                })
                                logger.info(f"找到期次: {issue_text} -> {href}")
                            else:
                                logger.debug(f"跳过期次: {issue_text}（日期超出范围）")
                    break  # 找到有效链接就退出
            except Exception as e:
                logger.error(f"解析选择器 {selector} 失败: {e}")
                continue
        
        # 统计优化效果
        if start_date and end_date:
            skipped_count = 0
            if valid_years:
                logger.info(f"年份筛选优化：检测到年份 {sorted(valid_years)}，已跳过不相关年份的期次")
            
            # 统计跳过的期次数量
            if all_found_links and len(all_found_links) > len(volume_issue_links):
                skipped_count = len(all_found_links) - len(volume_issue_links)
                logger.info(f"日期筛选优化：共检测到 {len(all_found_links)} 个期次，跳过 {skipped_count} 个超出日期范围的期次，节省 {skipped_count} 次页面访问")
        
        logger.info(f"最终获得 {len(volume_issue_links)} 个有效期次链接")
        
        # 如果严格范围内没找到期次，尝试宽松模式（找最近的前后期次）
        if len(volume_issue_links) == 0 and start_date and end_date and all_found_links:
            logger.info("严格范围内无期次，启用宽松模式寻找最近期次")
            logger.info(f"宽松模式将分析已找到的 {len(all_found_links)} 个期次链接")
            nearest_issues = self._find_nearest_issues_cell(all_found_links, start_date, end_date)
            if nearest_issues:
                logger.info(f"宽松模式下找到 {len(nearest_issues)} 个最近期次")
                volume_issue_links.extend(nearest_issues)
        
        return volume_issue_links
    
    def _find_nearest_issues_cell(self, all_issue_links, start_date: date, end_date: date):
        """寻找最接近目标日期范围的Cell期次（宽松模式）"""
        issues_with_dates = []
        target_center = start_date + (end_date - start_date) / 2  # 目标范围中心点
        
        try:
            for link in all_issue_links:
                href = link.get('href', '')
                spans = link.select('span')
                if href and spans:
                    # 提取期次信息
                    issue_text = ' '.join([span.get_text(strip=True) for span in spans])
                    
                    # 查找日期信息
                    issue_date = None
                    for span in spans:
                        span_text = span.get_text(strip=True)
                        # 查找日期模式（如 "September 02, 2025"）
                        date_match = re.search(r'(\w+)\s+(\d{1,2}),\s+(\d{4})', span_text)
                        if date_match:
                            try:
                                month_name, day, year = date_match.groups()
                                # 使用dateparser解析日期
                                import dateparser
                                parsed_date = dateparser.parse(f"{month_name} {day}, {year}")
                                if parsed_date:
                                    issue_date = parsed_date.date()
                                    break
                            except Exception as e:
                                logger.debug(f"解析期次日期失败: {span_text}, 错误: {e}")
                                continue
                    
                    if issue_date:
                        # 计算与目标范围中心的距离
                        distance = abs((issue_date - target_center).days)
                        
                        issues_with_dates.append({
                            'title': issue_text,
                            'url': href,
                            'date': issue_date,
                            'distance': distance
                        })
            
            # 按距离排序，选择最近的1-2个期次
            issues_with_dates.sort(key=lambda x: x['distance'])
            nearest_issues = issues_with_dates[:2]  # 最多选择2个最近的期次
            
            if nearest_issues:
                logger.info(f"找到最近期次: {[i['title'] + ' (' + str(i['date']) + ')' for i in nearest_issues]}")
                return [{'title': i['title'], 'url': i['url']} for i in nearest_issues]
            
        except Exception as e:
            logger.error(f"宽松模式寻找最近期次失败: {e}")
        
        return []
    
    def _update_cell_journals_if_needed(self):
        """检查并运行期刊配置更新，支持超时回退到旧版本"""
        try:
            import subprocess
            import os
            from datetime import datetime, timedelta
            
            # 检查配置文件的修改时间
            config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'journals_config/cell_journals.json')
            
            should_update = False
            
            # 情况1：配置文件不存在
            if not os.path.exists(config_file):
                logger.info("期刊配置文件不存在，使用动态获取")
                should_update = True
            else:
                # 情况2：配置文件超过24小时未更新
                file_mtime = datetime.fromtimestamp(os.path.getmtime(config_file))
                if datetime.now() - file_mtime > timedelta(hours=24):
                    logger.info(f"期刊配置文件已超过24小时未更新（上次更新: {file_mtime}），尝试动态更新")
                    should_update = True
            
            if should_update:
                logger.info("Cell爬虫开始动态获取子刊URL...")
                try:
                    # 使用内部方法动态获取，设置超时时间为60秒
                    self._discover_cell_journals_with_timeout(timeout=60)
                    logger.info("动态获取子刊成功")
                    
                except Exception as e:
                    logger.warning(f"动态获取子刊失败: {e}")
                    self._fallback_to_old_config(config_file)
            else:
                logger.debug("期刊配置文件较新，跳过更新")
                
        except Exception as e:
            logger.warning(f"检查期刊配置更新失败: {e}")
            # 如果整体检查失败，也尝试回退到旧配置
            config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'journals_config/cell_journals.json')
            self._fallback_to_old_config(config_file)
    
    def _discover_cell_journals_with_timeout(self, timeout=60):
        """动态获取Cell期刊，带超时控制"""
        import time as time_module
        start_time = time_module.time()
        
        try:
            # 获取Cell主页
            response = self.session.get('https://www.cell.com/', timeout=30)
            if response.status_code != 200:
                raise Exception(f"无法访问Cell主页: HTTP {response.status_code}")
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找所有链接
            links = soup.find_all('a', href=True)
            logger.info(f"找到 {len(links)} 个链接，开始筛选Cell子刊...")
            
            valid_journals = {}
            failed_journals = []
            processed_count = 0
            
            for link in links:
                # 检查超时
                if time_module.time() - start_time > timeout:
                    logger.warning(f"动态获取超时（{timeout}秒），停止处理")
                    raise TimeoutError(f"动态获取超时（{timeout}秒）")
                
                href = link.get('href', '')
                text = link.get_text(strip=True)
                
                # 筛选Cell子刊 - 简化逻辑，直接检查URL模式
                if href and 'cell.com' in href and ('/issues' in href or '/home' in href):
                    # 提取期刊名称
                    journal_name = text.strip() if text else ''
                    if not journal_name and href:
                        # 从URL提取名称
                        path_parts = href.strip('/').split('/')
                        if len(path_parts) >= 2:
                            journal_name = path_parts[-2].replace('-', ' ').title()
                    
                    if journal_name and journal_name not in valid_journals:
                        issues_url = href if href.endswith('/issues') else href.replace('/home', '/issues')
                        valid_journals[journal_name] = issues_url
                        logger.debug(f"发现Cell子刊: {journal_name} -> {issues_url}")
                
                processed_count += 1
                # 限制处理数量以避免过度消耗
                if processed_count >= 100:
                    logger.info("已处理100个链接，停止处理以避免过度消耗资源")
                    break
            
            if len(valid_journals) >= 10:  # 如果获取到足够的期刊（Cell实际约35个）
                logger.info(f"动态获取成功，获得{len(valid_journals)}个有效期刊（>=10），更新JSON配置")
                self._update_cell_journals_json(valid_journals, failed_journals)
            else:
                logger.warning(f"动态获取期刊数量不足: {len(valid_journals)} < 10，不更新配置文件")
                raise Exception(f"获取期刊数量不足: {len(valid_journals)} < 10")
            
        except Exception as e:
            logger.error(f"动态获取Cell期刊失败: {e}")
            raise
    
    def _fallback_to_old_config(self, config_file):
        """回退到旧版本的期刊配置"""
        try:
            # 尝试加载现有配置文件
            if os.path.exists(config_file):
                logger.info("使用现有期刊配置文件")
                return
            
            # 如果配置文件不存在，使用硬编码的备份配置
            logger.warning("配置文件不存在，使用硬编码备份配置")
            backup_journals = [
                {"name": "Cell", "link": "https://www.cell.com/cell/home"},
                {"name": "Cancer Cell", "link": "https://www.cell.com/cancer-cell/home"},
                {"name": "Cell Stem Cell", "link": "https://www.cell.com/cell-stem-cell/home"},
                {"name": "Cell Metabolism", "link": "https://www.cell.com/cell-metabolism/home"},
                {"name": "Developmental Cell", "link": "https://www.cell.com/developmental-cell/home"},
                {"name": "Molecular Cell", "link": "https://www.cell.com/molecular-cell/home"},
                {"name": "Neuron", "link": "https://www.cell.com/neuron/home"},
                {"name": "Immunity", "link": "https://www.cell.com/immunity/home"},
                {"name": "Current Biology", "link": "https://www.cell.com/current-biology/home"},
                {"name": "Cell Host & Microbe", "link": "https://www.cell.com/cell-host-microbe/home"}
            ]
            
            # 创建配置文件目录
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            
            # 保存备份配置
            with open(config_file, 'w', encoding='utf-8') as f:
                import json
                json.dump(backup_journals, f, ensure_ascii=False, indent=4)
            
            logger.info(f"已创建备份配置文件，包含 {len(backup_journals)} 个期刊")
            
        except Exception as e:
            logger.error(f"回退到旧配置失败: {e}")
            # 最后的备选方案：使用内存中的硬编码配置
            self._use_hardcoded_config()
    
    def _get_page_with_retry(self, url, max_retries=3):
        """带重试机制的requests优先 + selenium回退方法 - 基于Cell目录的成功实现"""
        
        # 第一阶段：优先使用requests
        logger.debug("优先使用requests方式访问页面")
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_time = random.uniform(4, 8)  # 增加等待时间
                    logger.info(f"第{attempt + 1}次尝试前等待 {wait_time:.1f} 秒，让网页充分加载...")
                    time.sleep(wait_time)
                
                # 随机轮换User-Agent
                user_agents = [
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
                ]
                self.session.headers.update({
                    'User-Agent': random.choice(user_agents),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Referer': 'https://www.cell.com/'
                })
                
                # 禁用SSL警告
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                
                logger.info(f"requests方式访问 {url} (第 {attempt + 1} 次)")
                response = self.session.get(url, timeout=90, verify=False)  # 30秒超时，避免过长等待
                
                # 处理403错误
                if response.status_code == 403:
                    logger.warning(f"收到403错误，第{attempt + 1}次尝试")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        logger.error("requests方式多次403错误")
                        raise Exception(f"403 Forbidden after {max_retries} attempts: {url}")
                
                # 处理429错误
                if response.status_code == 429:
                    logger.warning(f"收到429错误（请求频繁），第{attempt + 1}次尝试")
                    if attempt < max_retries - 1:
                        time.sleep(random.uniform(3, 6))
                        continue
                    else:
                        logger.info("requests方式多次429错误，切换到Selenium")
                        break
                
                # 检查响应是否成功
                response.raise_for_status()
                
                # 检查是否返回了有效内容
                if response.text and len(response.text) > 1000:
                    logger.debug("requests方式成功获取页面内容")
                    return response
                else:
                    logger.warning(f"requests获取内容过少（{len(response.text)}字符），可能页面未完全加载")
                    if attempt < max_retries - 1:
                        continue
                
            except Exception as e:
                logger.warning(f"requests请求失败 (第 {attempt + 1} 次): {e}")
                if attempt == max_retries - 1:
                    logger.info("requests方式彻底失败，切换到Selenium")
                    break
        
        # 第二阶段：Selenium回退模式
        if self.use_selenium:
            logger.info("==== 切换到Selenium回退模式 ====")
            if not self.driver:
                logger.warning("Selenium未预先启用，尝试临时初始化...")
                self._init_selenium_driver()
            
            if self.driver:
                logger.info(f"使用Selenium访问: {url}")
                
                # Selenium也需要重试机制
                for selenium_attempt in range(2):  # Selenium重试2次
                    try:
                        if selenium_attempt > 0:
                            logger.info(f"Selenium第{selenium_attempt + 1}次尝试，先等待网页加载...")
                            time.sleep(random.uniform(3, 5))
                        
                        page_source = self._get_page_with_selenium(url, max_wait=180)  # Cell给3分钟等待
                        if page_source and len(page_source) > 1000:
                            logger.info("Selenium成功获取页面内容")
                            
                            # 创建模拟response对象
                            class MockResponse:
                                def __init__(self, text, status_code=200):
                                    self.text = text
                                    self.status_code = status_code
                                    self.content = text.encode('utf-8')
                                    
                                def raise_for_status(self):
                                    pass
                            
                            return MockResponse(page_source)
                        else:
                            logger.warning(f"Selenium获取内容过少，第{selenium_attempt + 1}次尝试")
                            
                    except Exception as e:
                        logger.warning(f"Selenium失败 (第{selenium_attempt + 1}次): {e}")
                
                logger.error("Selenium方式也失败了")
            else:
                logger.error("Selenium初始化失败，无法使用浏览器模式")
        else:
            logger.error("Selenium不可用，无法使用浏览器模式")
        
        logger.error(f"==== 所有方式都失败了: {url} ====")
        return None
    
    def _get_page_with_selenium(self, url, max_wait=180):
        """使用Selenium获取页面内容 - 完全照搬cell目录的成功实现"""
        if not self.use_selenium or not self.driver:
            return None
        
        try:
            logger.info(f"Cell使用Selenium访问: {url}")
            
            # 设置页面加载超时
            self.driver.set_page_load_timeout(20)
            
            # 访问页面
            self.driver.get(url)
            
            # 使用改进的等待机制处理反爬虫页面
            if not self.wait_for_page_load(self.driver, max_wait=max_wait):
                logger.error("Cell页面加载失败或超时")
                return None
            
            # 等待Cell期刊特有的文章容器加载 - 完全照搬cell目录成功的选择器
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '.article-item')),
                        EC.presence_of_element_located((By.CSS_SELECTOR, '.toc-item')),
                        EC.presence_of_element_located((By.CSS_SELECTOR, '.article-link')),
                        EC.presence_of_element_located((By.CSS_SELECTOR, '.journal-article')),
                        EC.presence_of_element_located((By.CSS_SELECTOR, '.js-article')),
                        EC.presence_of_element_located((By.CSS_SELECTOR, '[data-article-path]')),
                        EC.presence_of_element_located((By.CSS_SELECTOR, '.issue-item')),
                        EC.presence_of_element_located((By.CSS_SELECTOR, '.archive-link')),
                        EC.presence_of_element_located((By.CSS_SELECTOR, '.list-of-issues__list'))
                    )
                )
                logger.debug("Cell文章容器已加载")
            except TimeoutException:
                logger.warning("等待Cell文章容器加载超时，继续处理")
            
            # 滚动页面确保所有内容加载 - 完全照搬cell目录的成功实现
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight/4);")
            time.sleep(3)  # 增加等待时间，让Cell页面更稳定
            
            # 继续滚动
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            time.sleep(3)
            
            # 滚动到页面底部
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(4)  # 等待更长时间加载更多内容
            
            # 回到顶部
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(2)
            
            # 获取页面源码
            page_source = self.driver.page_source
            logger.info(f"Cell Selenium成功获取页面，内容长度: {len(page_source)} 字符")
            
            return page_source
            
        except TimeoutException:
            logger.error(f"Cell Selenium访问超时: {url}")
            return None
        except WebDriverException as e:
            logger.error(f"Cell Selenium访问失败: {url}, 错误: {e}")
            return None
        except Exception as e:
            logger.error(f"Cell Selenium未知错误: {e}")
            return None
    
    def _extract_articles_from_issue(self, issue_url, journal_name, start_date, end_date):
        """从期次页面提取文章 - 基于Cell目录的成功实现"""
        logger.info(f"正在提取期次文章: {issue_url}")
        articles = []
        total_articles_found = 0
        articles_out_of_range = 0  # 统计超出时间范围的文章数量
        
        try:
            response = self._get_page_with_retry(issue_url)
            if not response:
                logger.warning(f"期次页面访问失败: {issue_url}")
                return articles
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 基于截图优化Cell期刊文章选择器 - 处理多个section结构
            logger.info("开始解析Cell期刊的section结构...")
            
            # 查找所有的section
            sections = soup.select('section.toc__section')
            if not sections:
                # 备选选择器
                sections = soup.select('.toc__section, section[class*="toc"]')
            
            # 如果没有找到section，直接查找文章元素
            if not sections:
                direct_articles = soup.select('li.articleCitation')
                if direct_articles:
                    sections = [soup]  # 将整个页面作为一个section处理
            
            total_articles_found = 0
            
            # 遍历每个section
            for section_idx, section in enumerate(sections, 1):
                try:
                    section_title = ""
                    section_title_elem = section.select_one('.toc__heading_header, h2, h3')
                    if section_title_elem:
                        section_title = section_title_elem.get_text(strip=True)
                    
                    # 在每个section中查找文章（全面的备选选择器）
                    article_selectors = [
                        'li.articleCitation',  # 最外层li元素（主要选择器）
                        'div.toc__item.clearfix',  # 基于您提供的HTML结构
                        '.toc__item.clearfix',  # 简化版本
                        'li.toc__item',  # 可能的li包装
                        '.toc__item_clearfix',  # 备选选择器（下划线格式）
                        '.toc__item',  # 通用toc item
                        '.article-item',  # 通用文章元素
                        '.articleCitation',  # 文章引用类
                        'li[data-pii]',  # 基于data-pii属性的li
                        'div[data-pii]',  # 基于data-pii属性的div
                        'article',  # HTML5语义元素
                        '.citation',  # 引用类
                        '.paper-item',  # 论文项目
                        '.journal-article',  # 期刊文章
                        'li:has(a[href*="fulltext"])',  # 包含fulltext链接的li
                        'div:has(a[href*="fulltext"])',  # 包含fulltext链接的div
                        'li:has(h3)',  # 包含h3标题的li
                        'div:has(h3)',  # 包含h3标题的div
                        '[class*="toc"]',  # 任何包含toc的类名
                        '[class*="article"]',  # 任何包含article的类名
                        '[class*="citation"]'  # 任何包含citation的类名
                    ]
                    
                    section_articles = []
                    for selector in article_selectors:
                        elements = section.select(selector)
                        if elements:
                            logger.info(f"使用选择器 '{selector}' 在section中找到 {len(elements)} 个文章元素")
                            section_articles = elements
                            break
                    
                    if not section_articles:
                        # 最后备选：在整个section中查找任何可能的文章元素
                        logger.debug(f"使用常规选择器未找到文章，尝试备选方案...")
                        fallback_elements = []
                        
                        # 查找包含Cell特征的元素
                        potential_articles = section.find_all(['li', 'div', 'h3'], recursive=True)
                        for elem in potential_articles:
                            # 检查是否包含Cell文章的特征
                            if (elem.get('data-pii') or 
                                elem.select_one('a[href*="fulltext"]') or
                                elem.select_one('a[href*="abstract"]') or
                                elem.select_one('a[href*="/cell/"]') or
                                elem.select_one('a[href*="S0092-8674"]') or
                                (elem.select_one('h3') and elem.select_one('a')) or
                                # 新增：检查ID中是否包含PII模式
                                (elem.get('id') and re.search(r'S\d{10,15}', elem.get('id', ''))) or
                                # 检查子元素中是否有包含PII模式的ID
                                elem.select_one('[id*="S0092867425"]') or
                                elem.select_one('[id*="S00"]')):
                                fallback_elements.append(elem)
                        
                        if fallback_elements:
                            section_articles = fallback_elements
                            logger.info(f"备选方案找到 {len(fallback_elements)} 个潜在文章元素")
                        else:
                            continue
                    
                    # 处理section中的每篇文章
                    for article_elem in section_articles:
                        try:
                            # 方法1: 在文章元素内部查找包含data-pii的子元素 (基于截图)
                            pii = None
                            pii_element = None
                            
                            # 查找包含data-pii的子元素（全面的备选选择器）
                            pii_selectors = [
                                'div.toc__item.clearfix[data-pii]',  # 基于您提供的HTML结构（主要）
                                'div[data-pii]',  # 通用div选择器
                                '.toc__item.clearfix[data-pii]',  # 简化版本
                                '.toc__item_clearfix[data-pii]',  # 下划线格式
                                '.toc__item[data-pii]',  # 通用toc item
                                'li[data-pii]',  # li元素
                                'article[data-pii]',  # HTML5语义元素
                                '[data-pii]',  # 最宽泛：任何包含data-pii的元素
                                '*[data-pii]',  # 显式通配符
                                # 属性值模式匹配
                                '[data-pii*="S00"]',  # Cell的PII通常以S00开头
                                '[data-pii^="S"]',  # 以S开头的PII
                                # 类名组合
                                '.toc__item[data-pii]',
                                '.article-item[data-pii]',
                                '.articleCitation[data-pii]',
                                '.citation[data-pii]',
                                # 嵌套查找
                                'div.toc__item div[data-pii]',
                                'li.articleCitation div[data-pii]',
                                '.toc__item_body [data-pii]',
                                '.toc__item__body [data-pii]'
                            ]
                            
                            # 尝试从各种元素中提取PII
                            for pii_selector in pii_selectors:
                                pii_element = article_elem.select_one(pii_selector)
                                if pii_element and pii_element.get('data-pii'):
                                    pii = pii_element.get('data-pii')
                                    logger.debug(f"找到data-pii: {pii} (使用选择器: {pii_selector})")
                                    break
                                elif pii_element:
                                    logger.debug(f"选择器 '{pii_selector}' 找到元素但无data-pii属性")
                            
                            # 如果没找到data-pii属性，尝试从ID中提取PII
                            if not pii:
                                # 查找包含PII模式的ID元素
                                id_selectors = [
                                    'h3.toc__item__title[id*="S0092867425"]',  # 您提供的新例子
                                    'h3[id*="S0092867425"]',  # h3标签包含PII的ID
                                    'h2[id*="S0092867425"]',  # h2标签
                                    'h4[id*="S0092867425"]',  # h4标签
                                    '[id*="S0092867425"]',  # 任何包含Cell PII模式的ID
                                    '[id*="S00"]',  # 更宽泛的PII模式
                                    '[id^="S0092867425"]',  # 以PII开头的ID
                                    '.toc__item__title[id]',  # 有ID的标题元素
                                    '.toc__item_title[id]',  # 单下划线版本
                                    'h3[id]',  # 任何有ID的h3
                                    '[id*="-title"]'  # 包含-title的ID
                                ]
                                
                                for id_selector in id_selectors:
                                    id_element = article_elem.select_one(id_selector)
                                    if id_element:
                                        element_id = id_element.get('id', '')
                                        # 从ID中提取PII（如：S0092867425008098-title -> S0092867425008098）
                                        import re
                                        pii_match = re.search(r'(S\d{10,15})', element_id)
                                        if pii_match:
                                            pii = pii_match.group(1)
                                            pii_element = id_element
                                            logger.info(f"从ID提取PII: {pii} (元素ID: {element_id}, 选择器: {id_selector})")
                                            break
                            
                            # 检查文章元素本身是否有data-pii
                            if not pii:
                                pii = article_elem.get('data-pii')
                                if pii:
                                    pii_element = article_elem
                                    logger.info(f"在文章元素本身找到data-pii: {pii}")
                                else:
                                    logger.warning(f"未找到data-pii属性或ID中的PII，文章元素类: {article_elem.get('class', 'N/A')}")
                            
                            if pii and pii_element:
                                # 获取期刊名称来构建正确的URL
                                journal_path = self._get_cell_journal_path(issue_url)
                                detail_url = f"https://www.cell.com/{journal_path}/fulltext/{pii}"
                                
                                # 获取标题 - 优先从pii_element获取
                                title = self._extract_cell_article_title(pii_element)
                                if not title or title in ["未知标题", "标题提取失败"]:
                                    title = self._extract_cell_article_title(article_elem)
                                
                                # 获取文章详细信息
                                article_details = self._get_cell_article_details_from_abstract(detail_url)
                                if article_details:
                                    article_details['journal'] = journal_name
                                    article_details['pii'] = pii
                                    
                                    # 时间范围过滤
                                    article_date = article_details.get('date')
                                    if article_date and self._is_date_in_range(article_date, start_date, end_date):
                                        articles.append(article_details)
                                        total_articles_found += 1
                                        logger.info(f"Cell文章: {article_details.get('title', 'Unknown')[:80]}")
                                    elif article_date:
                                        articles_out_of_range += 1
                                    else:
                                        # 日期未知，默认包含
                                        articles.append(article_details)
                                        total_articles_found += 1
                    
                        except Exception as e:
                            logger.error(f"处理PII方法文章失败: {e}")
                    
                    # 方法2: 传统方式获取链接（全面的备选选择器）
                    try:
                        link_selectors = [
                            'h3.toc__item__title a',  # 基于您提供的HTML结构（主要）
                            'h3 a[href*="fulltext"]',  # fulltext链接（优先）
                            'h3 a[href*="abstract"]',  # abstract链接
                            '.toc__item__title a',  # 标题链接（双下划线）
                            '.toc__item_title a',  # 标题链接（单下划线）
                            'h3 a',  # 任何h3中的链接
                            'h2 a',  # h2中的链接
                            'h4 a',  # h4中的链接
                            '.title a',  # 标题类中的链接
                                '.article-title a',  # 文章标题链接
                                '.paper-title a',  # 论文标题链接
                                'a[href*="/cell/fulltext/"]',  # Cell fulltext链接
                                'a[href*="/cell/abstract/"]',  # Cell abstract链接
                                'a[href*="/cell/"]',  # 任何Cell链接
                                'a[href*="fulltext"]',  # 任何fulltext链接
                                'a[href*="abstract"]',  # 任何abstract链接
                                'a[href*="pdf"]',  # PDF链接
                                'a[href*="S0092-8674"]',  # Cell期刊特定模式
                                'a[href*="S00"]',  # PII模式链接
                                'a[title*="full"]',  # title属性包含full
                                'a[title*="abstract"]',  # title属性包含abstract
                                '.toc__item__body a',  # 文章体中的链接
                                '.toc__item_body a',  # 文章体中的链接（单下划线）
                                '.article-link',  # 文章链接类
                                '.paper-link',  # 论文链接类
                                'a'  # 最后备选：任何链接
                        ]
                        
                        title_elem = None
                        for link_selector in link_selectors:
                            title_elem = article_elem.select_one(link_selector)
                            if title_elem and title_elem.get('href'):
                                break
                        
                        if title_elem:
                            title = title_elem.get_text(strip=True)
                            article_link = title_elem.get('href', '')
                            
                            if title and article_link:
                                # 构建完整URL
                                if article_link.startswith('/'):
                                    detail_url = f"https://www.cell.com{article_link}"
                                else:
                                    detail_url = urljoin(issue_url, article_link)
                                
                                # 获取文章详细信息
                                if '/abstract/' in detail_url or '/fulltext/' in detail_url:
                                    article_details = self._get_cell_article_details_from_abstract(detail_url)
                                else:
                                    article_details = self._get_cell_article_details(detail_url)
                                
                                if article_details:
                                    article_details['journal'] = journal_name
                                    
                                    # 时间范围过滤
                                    article_date = article_details.get('date')
                                    if article_date and self._is_date_in_range(article_date, start_date, end_date):
                                        articles.append(article_details)
                                        total_articles_found += 1
                                        logger.info(f"Cell文章: {article_details.get('title', 'Unknown')[:80]}")
                                    elif article_date:
                                        articles_out_of_range += 1
                                    else:
                                        # 日期未知，默认包含
                                        articles.append(article_details)
                                        total_articles_found += 1
                                
                                # 添加延迟
                                time.sleep(random.uniform(1, 3))
                    
                    except Exception as e:
                        logger.error(f"处理传统方法文章失败: {e}")
                        continue
                    
                except Exception as e:
                    logger.error(f"处理section失败: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"提取期次文章失败 {issue_url}: {e}")
        
        # 输出统计信息
        if articles_out_of_range > 0:
            logger.info(f"期次 {issue_url} 提取了 {len(articles)} 篇文章，{articles_out_of_range} 篇文章超出时间范围 ({start_date} 到 {end_date}) 被跳过")
        else:
            logger.info(f"期次 {issue_url} 提取了 {len(articles)} 篇文章")
        return articles
    
    def _get_cell_journal_path(self, issue_url):
        """从期次URL中提取期刊路径名"""
        try:
            # 从URL如 https://www.cell.com/cell/issue?pii=... 中提取 'cell'
            # 或从 https://www.cell.com/cell-metabolism/issue?pii=... 中提取 'cell-metabolism'
            if '/cell/' in issue_url:
                return 'cell'
            elif '/cell-metabolism/' in issue_url:
                return 'cell-metabolism'
            elif '/molecular-cell/' in issue_url:
                return 'molecular-cell'
            elif '/developmental-cell/' in issue_url:
                return 'developmental-cell'
            elif '/current-biology/' in issue_url:
                return 'current-biology'
            elif '/structure/' in issue_url:
                return 'structure'
            elif '/immunity/' in issue_url:
                return 'immunity'
            elif '/neuron/' in issue_url:
                return 'neuron'
            elif '/cancer-cell/' in issue_url:
                return 'cancer-cell'
            elif '/cell-stem-cell/' in issue_url:
                return 'cell-stem-cell'
            else:
                # 通用提取方法
                import re
                match = re.search(r'cell\.com/([^/]+)/', issue_url)
                if match:
                    return match.group(1)
                return 'cell'  # 默认返回cell
        except Exception as e:
            logger.error(f"提取期刊路径失败: {e}")
            return 'cell'
    
    def _extract_cell_article_title(self, article_elem):
        """从文章元素中提取标题"""
        try:
            # 全面的标题选择器
            title_selectors = [
                'h3.toc__item__title a',  # 基于您提供的HTML结构（主要）
                '.toc__item__title a',  # 双下划线版本
                '.toc__item_title a',  # 单下划线版本
                'h3 a',  # h3中的链接
                'h2 a',  # h2中的链接
                'h4 a',  # h4中的链接
                '.title a',  # 标题类链接
                '.article-title a',  # 文章标题链接
                '.paper-title a',  # 论文标题链接
                'a[href*="fulltext"]',  # fulltext链接
                'a[href*="abstract"]',  # abstract链接
                'a[href*="/cell/"]',  # Cell链接
                'a[href*="S0092-8674"]',  # Cell期刊模式
                'a[href*="S00"]',  # PII模式
                '.toc__item__body a',  # 文章体链接
                '.toc__item_body a',  # 文章体链接（单下划线）
                '.citation-title a',  # 引用标题
                '.entry-title a',  # 条目标题
                'a[title]',  # 有title属性的链接
                'a'  # 最后备选：任何链接
            ]
            
            for selector in title_selectors:
                title_elem = article_elem.select_one(selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if title and len(title) > 10:  # 确保不是空标题或太短的标题
                        return title
            
            # 如果没有找到链接中的标题，尝试直接查找文本
            title_text_selectors = [
                '.toc__item_title',
                'h3',
                '.title'
            ]
            
            for selector in title_text_selectors:
                title_elem = article_elem.select_one(selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if title and len(title) > 10:
                        return title
            
            return "未知标题"
            
        except Exception as e:
            logger.error(f"提取文章标题失败: {e}")
            return "标题提取失败"
    
    
    def _get_cell_article_details(self, url: str):
        """获取Cell文章详细信息"""
        try:
            response = self.session.get(url, timeout=30)
            if response.status_code != 200:
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 标题: <h1 class="article-title article-title-main">
            title_elem = soup.find('h1', class_='article-title article-title-main')
            title = title_elem.get_text(strip=True) if title_elem else ''
            
            # 摘要: <div id="abstracts">
            abstract = ''
            abstract_elem = soup.find('div', id='abstracts')
            if abstract_elem:
                abstract = abstract_elem.get_text(strip=True)
            
            # 发表日期: <div class="content--publishDate"> August 26, 2024</div>
            pub_date = datetime.now().date()
            date_elem = soup.find('div', class_='content--publishDate')
            if date_elem:
                date_text = date_elem.get_text(strip=True)
                try:
                    pub_date = dateparser.parse(date_text).date()
                except:
                    pass
            
            # DOI
            doi = ''
            doi_elem = soup.find('meta', attrs={'name': 'citation_doi'})
            if doi_elem:
                doi = doi_elem.get('content', '')
            
            # 作者信息
            authors = ''
            author_elems = soup.find_all('meta', attrs={'name': 'citation_author'})
            if author_elems:
                authors = '; '.join([elem.get('content', '') for elem in author_elems])
            
            return {
                'title': title,
                'abstract': abstract,
                'doi': doi,
                'url': url,
                'date': pub_date,
                'authors': authors
            }
            
        except Exception as e:
            logger.error(f"获取Cell文章详情失败: {e}")
            return None
    
    def _get_cell_article_details_from_abstract(self, abstract_url: str):
        """从摘要页面获取Cell文章详细信息 - 基于Cell目录的成功实现"""
        try:
            response = self.session.get(abstract_url, timeout=30)
            if response.status_code != 200:
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 标题提取
            title = ''
            title_selectors = ['h1[property="name"]', 'h1.article-title', '.title h1', 'h1']
            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    break
            
            # 作者信息提取
            authors = ''
            author_selectors = ['span.authors', '.author-list', '.authors']
            for selector in author_selectors:
                author_elem = soup.select_one(selector)
                if author_elem:
                    authors = author_elem.get_text(strip=True)
                    break
            
            # 摘要提取
            abstract = ''
            abstract_selectors = ['div#abstracts', '.abstract', '.abstractInFull']
            for selector in abstract_selectors:
                abstract_elem = soup.select_one(selector)
                if abstract_elem:
                    abstract = abstract_elem.get_text(strip=True)
                    break
            
            # 基于Cell目录成功实现的摘要提取策略
            if not abstract or len(abstract) < 100:
                # 尝试更精确的Cell摘要选择器
                detailed_abstract_selectors = [
                    'section#author-abstract[property="abstract"]',  # 最精确匹配
                    'section#author-abstract',  # 摘要section
                    'div#abspara0010[role="paragraph"]',  # 具体的摘要段落ID
                    '#author-abstract div[role="paragraph"]',  # 摘要段落内容
                    '#author-abstract',  # 直接通过ID
                    'section[property="abstract"]',  # 基于属性
                    '[data-section="abstract"]',
                    '.abstract-content',
                    '.summary'
                ]
                
                for selector in detailed_abstract_selectors:
                    try:
                        abstract_elem = soup.select_one(selector)
                        if abstract_elem:
                            detail_abstract = abstract_elem.get_text(strip=True)
                            
                            # 清理摘要文本
                            if detail_abstract:
                                # 移除常见的无用前缀
                                prefixes_to_remove = [
                                    'Abstract', 'ABSTRACT', 'Summary', 'SUMMARY',
                                    'Abstract:', 'ABSTRACT:', 'Summary:', 'SUMMARY:'
                                ]
                                for prefix in prefixes_to_remove:
                                    if detail_abstract.startswith(prefix):
                                        detail_abstract = detail_abstract[len(prefix):].strip()
                                
                                # 验证摘要长度和质量
                                if 50 <= len(detail_abstract) <= 5000:
                                    abstract = detail_abstract
                                    logger.info(f"成功获取详情页摘要（选择器: {selector}），长度: {len(abstract)} 字符")
                                    break
                                elif len(detail_abstract) > 5000:
                                    # 如果摘要太长，截取前5000字符
                                    abstract = detail_abstract[:5000] + "..."
                                    logger.warning(f"摘要过长，截取前5000字符")
                                    break
                    except Exception as e:
                        logger.debug(f"摘要选择器 {selector} 失败: {e}")
                        continue
                
                # 如果仍然没有找到摘要，尝试查找Main text（如Cell目录实现）
                if not abstract or len(abstract) < 50:
                    logger.warning("未找到传统摘要，尝试查找Main text")
                    main_text_selectors = [
                        'section#main-text',
                        '#main-text',
                        '.main-text',
                        'section[data-section="main"]',
                        'div[id*="main"]',
                        # 基于Cell图片中的结构，Main text可能在特定的section中
                        'section[id="bodymatter"] div[class="core-container"]',
                        'div[class="core-container"] section'
                    ]
                    
                    for selector in main_text_selectors:
                        try:
                            main_elem = soup.select_one(selector)
                            if main_elem:
                                main_text = main_elem.get_text(strip=True)
                                
                                if main_text and len(main_text) > 100:
                                    # 截取Main text的前500字符作为摘要替代
                                    abstract = main_text[:500] + "..."
                                    logger.info(f"使用Main text作为摘要替代，长度: {len(abstract)} 字符")
                                    break
                        except Exception as e:
                            logger.debug(f"Main text选择器 {selector} 失败: {e}")
                            continue
            
            # 发表日期提取 - 基于Cell目录的成功实现，包含勘误处理逻辑
            pub_date = datetime.now().date()
            
            # 检查是否是勘误文章（Correction）
            is_correction = False
            correction_indicators = [
                'h1:contains("Correction")',
                '.article-type:contains("Correction")', 
                'span:contains("Correction")',
                '[class*="correction"]',
                'div:contains("Corrected:")',
            ]
            
            for indicator in correction_indicators:
                try:
                    correction_elem = soup.select_one(indicator)
                    if correction_elem:
                        correction_text = correction_elem.get_text(strip=True)
                        if 'correction' in correction_text.lower():
                            is_correction = True
                            logger.info(f"检测到勘误文章，将使用发表日期而非勘误日期")
                            break
                except Exception as e:
                    logger.debug(f"勘误检查失败: {e}")
                    continue
            
            # 根据是否是勘误选择不同的日期选择器
            if is_correction:
                # 勘误文章：使用 content--publishDate（原始发表日期）
                date_selectors = [
                    'div.content--publishDate',     # 发表日期格式
                    '.content--publishDate',
                    'div[class*="publishDate"]',
                    '.publish-date',
                    '.publication-date',
                    '.original-date',
                    # 备用选择器
                    '.meta-panel__onlineDate',
                    'span.meta-panel__onlineDate',
                    'time[datetime]',
                    '.pub-date'
                ]
            else:
                # 正常文章：使用 meta-panel__onlineDate（在线日期）
                date_selectors = [
                    'span.meta-panel__onlineDate',   # 在线日期格式
                    '.meta-panel__onlineDate',
                    'span[class*="onlineDate"]',
                    '.online-date',
                    # 备用选择器
                    'div.content--publishDate',
                    '.content--publishDate',
                    'time[datetime]',
                    '.publication-date',
                    '.pub-date'
                ]
            
            # 按优先级尝试提取日期
            for selector in date_selectors:
                date_elem = soup.select_one(selector)
                if date_elem:
                    date_text = date_elem.get_text(strip=True)
                    try:
                        pub_date = dateparser.parse(date_text).date()
                        break
                    except:
                        continue
            
            # DOI提取 - 从URL中提取
            doi = ''
            if '/abstract/' in abstract_url:
                # 例如: https://www.cell.com/cell/abstract/S0092-8674(25)00923-7
                doi_part = abstract_url.split('/abstract/')[-1]
                if doi_part:
                    doi = doi_part
                    logger.info(f"从URL提取DOI: {doi}")
            
            result = {
                'title': title,
                'abstract': abstract,
                'doi': doi,
                'url': abstract_url,
                'date': pub_date,
                'authors': authors
            }
            
            return result
            
        except Exception as e:
            logger.error(f"获取Cell摘要页面详情失败: {e}")
            return None
    
    def _close_selenium_driver(self):
        """关闭Selenium WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Cell Selenium WebDriver已关闭")
            except Exception as e:
                logger.error(f"关闭Cell Selenium WebDriver失败: {e}")
            finally:
                self.driver = None
    
    def close(self):
        """关闭资源"""
        self._close_selenium_driver()
        
        if self.session:
            try:
                self.session.close()
                logger.info("Cell Requests session已关闭")
            except Exception as e:
                logger.error(f"关闭Cell requests session失败: {e}")

class PLOSParser(BaseParser):
    """PLOS期刊解析器 - 基于实际plos_requests_parser.py逻辑"""
    
    def __init__(self, database=None, paper_agent=None):
        super().__init__('plos', database, paper_agent, use_selenium=True)
        
        # 初始化失败期刊记录
        self.failed_journals = []
        
        # 初始化失败期刊管理器
        try:
            from .tools.failed_journals_manager import FailedJournalsManager
        except ImportError:
            from tools.failed_journals_manager import FailedJournalsManager
        self.failed_manager = FailedJournalsManager('plos')
        
        # 动态更新期刊配置（每次启动时检查）
        self._update_plos_journals_if_needed()
        
        # PLOS专用用户代理
        self.plos_user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0'
        ]
        
        # 配置更长的重试和超时
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        retry_strategy = Retry(
            total=10,  # 增加重试次数
            backoff_factor=8,  # 增加退避因子
            status_forcelist=[403, 429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def _update_plos_journals_if_needed(self):
        """动态获取PLOS子刊URL列表，每次爬虫执行时更新JSON配置"""
        logger.info("开始动态获取PLOS期刊列表...")
        
        try:
            # 访问PLOS主域名获取期刊列表
            response = self.session.get('https://plos.org/', timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找期刊菜单容器
            menu_container = soup.find('div', class_='menu-journals-container')
            if not menu_container:
                logger.warning("未找到PLOS期刊菜单容器，使用现有配置")
                return
            
            # 获取期刊列表
            journal_links = menu_container.find_all('a', href=True)
            if not journal_links:
                logger.warning("未找到PLOS期刊链接，使用现有配置")
                return
            
            # 提取期刊信息
            new_journals = []
            for link in journal_links:
                href = link.get('href')
                name = link.get_text(strip=True)
                
                if href and 'journals.plos.org' in href and name.startswith('PLOS'):
                    # 确保URL以斜杠结尾
                    if not href.endswith('/'):
                        href += '/'
                    
                    new_journals.append({
                        'name': name,
                        'link': href
                    })
            
            logger.info(f"从PLOS主站动态获取到 {len(new_journals)} 个期刊")
            
            # 保存结果 - 只有获取到足够期刊时才使用智能更新器
            if len(new_journals) >= 10:
                # 使用智能更新器：只更新筛选期刊的链接，不添加新期刊
                try:
                    from tools.smart_journal_updater import SmartJournalUpdater
                    updater = SmartJournalUpdater(base_dir=os.path.dirname(__file__))
                    success = updater.update_plos_journals(new_journals)
                    if success:
                        pass  # 智能更新器会输出详细信息
                    else:
                        logger.warning("智能更新失败，保留现有筛选配置不变")
                except Exception as e:
                    # 如果导入或执行失败，保留现有配置不变
                    logger.warning(f"智能更新器异常: {e}，保留现有筛选配置不变")
            else:
                logger.warning(f"获取的PLOS期刊数量不足 ({len(new_journals)}个)，保留现有配置")
                
        except Exception as e:
            logger.error(f"动态获取PLOS期刊列表失败: {e}")
            logger.info("将使用现有的PLOS期刊配置")
        
        # PLOS期刊代码映射
        self.journal_code_to_path = {
            'PLOSOne': 'plosone',
            'PLOSBiology': 'plosbiology',
            'PLOSMedicine': 'plosmedicine',
            'PLOSGenetics': 'plosgenetics',
            'PLOSComputationalBiology': 'ploscompbiol',
            'PLOSPathogens': 'plospathogens',
            'PLOSNegTropicalDiseases': 'plosntds',
            'PLOSDigitalHealth': 'digitalhealth',
            'PLOSGlobalPublicHealth': 'globalpublichealth',
            'PLOSClimate': 'climate',
            'PLOSWater': 'water',
            'PLOSSustainabilityTransformation': 'sustainabilitytransformation',
            'PLOSComplexSystems': 'complexsystems',
            'PLOSMentalHealth': 'mentalhealth'
        }
    
    def get_page_with_retry_plos(self, url, max_retries=8, timeout=60):
        """PLOS专用的请求重试方法，使用更长等待时间和重试次数"""
        for attempt in range(max_retries):
            try:
                # 轮换User-Agent
                user_agent = random.choice(self.plos_user_agents)
                self.session.headers['User-Agent'] = user_agent
                
                # 增加随机延迟避免被检测
                if attempt > 0:
                    delay = random.uniform(8, 20) * (attempt + 1)  # PLOS需要更长的延迟
                    logger.info(f"PLOS第{attempt + 1}次尝试前等待 {delay:.1f} 秒...")
                    time.sleep(delay)
                
                logger.info(f"PLOS requests方式访问 {url} (第 {attempt + 1} 次)")
                response = self.session.get(url, timeout=timeout)
                
                if response.status_code == 200:
                    logger.info(f"PLOS成功获取页面: {url}")
                    return response
                elif response.status_code == 403:
                    logger.warning(f"PLOS收到403错误 (第 {attempt + 1} 次): {url}")
                    if attempt < max_retries - 1:
                        # 403错误时等待更长时间
                        time.sleep(random.uniform(15, 30))  # PLOS 403错误更长等待
                        continue
                else:
                    logger.warning(f"PLOS HTTP {response.status_code}: {url}")
                    
            except Exception as e:
                logger.warning(f"PLOS requests请求失败 (第 {attempt + 1} 次): {e}")
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(8, 15))  # PLOS更长的错误恢复时间
        
        logger.error(f"PLOS requests方式彻底失败: {url}")
        return None
    
    def build_search_url(self, journal_name, start_date, end_date):
        """构建PLOS搜索URL（返回第一个URL用于兼容性）"""
        urls = self.build_search_url_with_page(journal_name, start_date, end_date, 1)
        return urls[0] if urls else ""
    
    def scrape_journal(self, journal_name: str, base_url: str, start_date: datetime, end_date: datetime):
        """爬取PLOS期刊数据 - 主逻辑 + 备选逻辑"""
        logger.info(f"开始爬取PLOS期刊: {journal_name}")
        articles = []
        
        try:
            # 主逻辑：优先使用现有的爬取方式
            scrape_success = False
            if self.driver:
                logger.info(f"PLOS使用Selenium方式爬取（页面动态加载）: {journal_name}")
                articles, scrape_success = self._scrape_all_pages_with_selenium(journal_name, start_date, end_date)
            else:
                # 如果Selenium不可用，尝试requests（可能获取不到动态内容）
                logger.warning(f"Selenium不可用，尝试requests方式（可能无结果）: {journal_name}")
                articles, scrape_success = self._scrape_with_requests(journal_name, start_date, end_date)

            # 检查是否需要启动备选逻辑
            if not scrape_success:
                logger.warning(f"PLOS主逻辑爬取失败，启动备选爬取逻辑: {journal_name}")
                articles = self._scrape_with_fallback_logic(journal_name, base_url, start_date, end_date)
            elif len(articles) == 0:
                # 当主逻辑成功但没有找到文章时，也尝试备选逻辑（可能是页面结构变化）
                logger.info(f"PLOS {journal_name} 主逻辑未找到文章，尝试备选逻辑验证")
                try:
                    fallback_articles = self._scrape_with_fallback_logic(journal_name, base_url, start_date, end_date)
                    if len(fallback_articles) > 0:
                        logger.info(f"PLOS {journal_name} 备选逻辑找到 {len(fallback_articles)} 篇文章")
                        articles = fallback_articles
                    else:
                        logger.info(f"PLOS {journal_name} 备选逻辑也未找到文章，确认该时间范围内无新文章")
                except Exception as fallback_e:
                    logger.debug(f"PLOS {journal_name} 备选逻辑执行失败: {fallback_e}")
                    logger.info(f"PLOS {journal_name} 在指定日期范围内没有文章，这是正常情况")
            
        except Exception as e:
            logger.error(f"PLOS期刊主逻辑爬取失败: {e}")
            # 主逻辑完全失败时，尝试备选逻辑
            logger.info(f"启动PLOS备选爬取逻辑: {journal_name}")
            try:
                articles = self._scrape_with_fallback_logic(journal_name, base_url, start_date, end_date)
            except Exception as fallback_error:
                logger.error(f"PLOS备选逻辑也失败: {fallback_error}")
                # 记录失败的期刊
                if hasattr(self, 'failed_manager'):
                    self.failed_manager.add_failed_journal(journal_name, base_url, str(fallback_error))
        
        logger.info(f"PLOS {journal_name}爬取完成，获得{len(articles)}篇文章")
        return articles
    
    def _scrape_with_fallback_logic(self, journal_name: str, base_url: str, start_date: datetime, end_date: datetime):
        """PLOS备选爬取逻辑 - 通过volume页面"""
        try:
            from .plos_fallback_parser import PLOSFallbackParser
        except ImportError:
            from plos_fallback_parser import PLOSFallbackParser
        
        fallback_parser = PLOSFallbackParser(main_parser=self)
        try:
            articles = fallback_parser.scrape_journal_fallback(journal_name, base_url, start_date, end_date)
            return articles
        finally:
            fallback_parser.close()
    
    def _scrape_with_requests(self, journal_name: str, start_date: datetime, end_date: datetime):
        """使用requests方式爬取PLOS，基于截图中的HTML结构"""
        articles = []
        page = 1
        scrape_success = True  # 爬取成功标志
        
        # 尝试获取总页数（requests方式）
        total_pages = self._get_plos_total_pages_requests(journal_name, start_date, end_date)
        if total_pages:
            logger.info(f"PLOS {journal_name} 检测到总共 {total_pages} 页（requests方式）")
        else:
            logger.info(f"PLOS {journal_name} 无法检测总页数，将遍历直到空页面结束（requests方式）")

        while True:
            try:
                # 构建分页搜索URL
                search_urls = self.build_search_url_with_page(journal_name, start_date, end_date, page)
                if not search_urls:
                    logger.warning(f"PLOS无法构建搜索URL: {journal_name}")
                    break
                
                logger.info(f"PLOS {journal_name} 第{page}页: {search_urls[0]}")
                
                # 使用增强的请求重试方法
                response = self.get_page_with_retry_plos(search_urls[0])
                if not response:
                    logger.warning(f"PLOS第{page}页访问失败: {journal_name}")
                    break
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 根据截图解析文章，查找 data-doi 属性
                page_articles = []
                
                # 方法1: 查找包含data-doi的dt元素（基于您提供的HTML结构）
                articles_with_doi = soup.find_all('dt', attrs={'data-doi': True})
                logger.info(f"PLOS {journal_name} 第{page}页找到{len(articles_with_doi)}个DOI元素")
                
                processed_count = 0
                filtered_count = 0
                
                for dt_elem in articles_with_doi:
                    try:
                        doi = dt_elem.get('data-doi')
                        if doi:
                            processed_count += 1
                            # 直接从搜索结果页面提取文章信息，根据图片中的HTML结构
                            logger.debug(f"PLOS开始处理DOI: {doi}")
                            article_data = self._extract_plos_article_from_search_result(dt_elem, doi, journal_name)
                            
                            if article_data:
                                # 服务器端已经按时间范围过滤，直接包含所有返回的文章
                                article_title = article_data.get('title', '')[:50]
                                article_date = article_data.get('date')
                                
                                page_articles.append(article_data)
                                logger.info(f"PLOS文章: '{article_title}...', 日期: {article_date}")
                            else:
                                # 这里可能是期刊不匹配被过滤了
                                filtered_count += 1
                                logger.debug(f"PLOS文章被过滤: DOI={doi}")
                            
                    except Exception as e:
                        logger.error(f"PLOS解析dt元素失败: {e}")
                        continue
                
                logger.info(f"PLOS {journal_name} 第{page}页处理完成: 总DOI={len(articles_with_doi)}, 处理={processed_count}, 过滤={filtered_count}, 有效={len(page_articles)}")
                
                # 检测页面有内容但都被过滤的情况
                if len(page_articles) == 0 and len(articles_with_doi) > 0:
                    # 页面有文章但都不属于当前期刊，返回特殊标记（包含DOI总数）
                    page_articles = [{'__page_has_content_but_filtered__': True, '__original_doi_count__': len(articles_with_doi)}]
                elif len(page_articles) > 0:
                    # 有有效文章时，在第一篇文章中添加DOI总数信息
                    page_articles[0]['__original_doi_count__'] = len(articles_with_doi)
                
                # 如果没有找到data-doi，尝试查找DOI链接
                if not page_articles:
                    doi_links = soup.find_all('p', class_='search-results-doi')
                    logger.info(f"PLOS回退方式找到{len(doi_links)}个DOI链接元素")
                        
                    for doi_elem in doi_links:
                            try:
                                link_elem = doi_elem.find('a', href=True)
                                if link_elem:
                                    doi_url = link_elem.get('href')
                                    if 'doi.org' in doi_url:
                                        # 获取文章详情
                                        article_data = self._get_plos_article_details(doi_url)
                                        if article_data:
                                            article_data['journal'] = journal_name
                                        page_articles.append(article_data)
                                            
                            except Exception as e:
                                logger.error(f"PLOS解析DOI链接失败: {e}")
                                continue
                            
                    time.sleep(random.uniform(2, 5))
                
                # 检测真正的空页面：如果页面没有文章，说明已超过实际页数
                if not page_articles:
                    logger.info(f"PLOS {journal_name} 第{page}页为空页面，已超过实际页数，停止分页")
                    break
                
                # 检测页面有内容但都被过滤的情况
                if (len(page_articles) == 1 and 
                    page_articles[0].get('__page_has_content_but_filtered__')):
                    # 获取原始DOI数量判断是否继续翻页
                    original_doi_count = page_articles[0].get('__original_doi_count__', 0)
                    if original_doi_count < 60:
                        logger.info(f"PLOS {journal_name} 第{page}页DOI数量不足60个（{original_doi_count}），已是最后一页")
                        break
                    else:
                        logger.info(f"PLOS {journal_name} 第{page}页有文章但都不属于当前期刊，页面DOI满60个，继续下一页")
                        page += 1
                        time.sleep(random.uniform(3, 8))
                        continue
                
                # 检测是否为最后一页：基于页面DOI总数判断
                original_doi_count = 0
                if len(page_articles) > 0:
                    original_doi_count = page_articles[0].get('__original_doi_count__', len(page_articles))
                
                if original_doi_count < 60:
                    logger.info(f"PLOS {journal_name} 第{page}页DOI数量不足60个（{original_doi_count}），已是最后一页")
                    # 但仍然要处理这一页的有效文章
                else:
                    logger.debug(f"PLOS {journal_name} 第{page}页DOI数量达到60个，可能还有更多页")
                
                # 去重处理（requests版本）
                new_articles = []
                duplicate_count = 0
                if not hasattr(self, '_requests_seen_dois'):
                    self._requests_seen_dois = set()
                
                for article in page_articles:
                    # 跳过特殊标记
                    if article.get('__page_has_content_but_filtered__'):
                        continue
                        
                    doi = article.get('doi', '') if article else ''
                    if doi and doi not in self._requests_seen_dois:
                        self._requests_seen_dois.add(doi)
                        new_articles.append(article)
                    else:
                        duplicate_count += 1
                
                articles.extend(new_articles)
                if total_pages:
                    logger.info(f"PLOS第{page}页（共{total_pages}页）获得{len(page_articles)}篇文章，去重后{len(new_articles)}篇，重复{duplicate_count}篇")
                else:
                    logger.info(f"PLOS第{page}页获得{len(page_articles)}篇文章，去重后{len(new_articles)}篇，重复{duplicate_count}篇")
                
                # 检查是否还有下一页：基于原始DOI数量
                if original_doi_count < 60:
                    logger.info(f"PLOS {journal_name} 第{page}页原始DOI数量不足60个，已是最后一页")
                    break
                
                # 如果检测到总页数，检查是否超过
                if total_pages and page >= total_pages:
                    logger.info(f"PLOS第{page}页已达到检测到的总页数({total_pages})，停止爬取")
                    break
                
                page += 1
                
                # 页面间延迟
                time.sleep(random.uniform(3, 8))
            
            except Exception as e:
                logger.error(f"PLOS第{page}页爬取失败: {e}")
                # 如果是第一页就失败，说明是访问问题，需要备选逻辑
                if page == 1:
                    scrape_success = False
                break
        
        return articles, scrape_success
    
    def _extract_plos_article_from_search_result(self, dt_elem, doi, journal_name):
        """从PLOS搜索结果页面直接提取文章信息，基于图片中的HTML结构"""
        try:
            # 首先检查期刊名称匹配
            article_journal_name = self._check_plos_article_journal_match(dt_elem, journal_name)
            if not article_journal_name:
                logger.debug(f"PLOS文章期刊不匹配，跳过: DOI={doi}")
                return None
            
            # 提取标题
            title = ''
            title_elem = dt_elem.find('a')
            if title_elem:
                title = title_elem.get_text(strip=True)
            
            if not title:
                logger.warning(f"PLOS未找到标题: DOI={doi}")
                return None
            
            # 提取文章URL
            article_url = ''
            link_elem = dt_elem.find('a', href=True)
            if link_elem:
                href = link_elem.get('href')
                if href.startswith('/'):
                    article_url = f"https://journals.plos.org{href}"
                else:
                    article_url = href
            else:
                # 备选方案：从DOI构建URL - 从DOI中提取实际期刊路径
                article_url = self._build_plos_url_from_doi(doi)
            
            # PLOS使用服务器端日期过滤，搜索结果肯定在范围内
            # 直接从详情页面获取完整信息（标题、作者、DOI、日期、摘要）
            pub_date = None
            abstract = ''
            authors = ''
            
            try:
                if article_url:
                    logger.debug(f"PLOS访问详情页面获取完整信息: {article_url}")
                    article_details = self._get_plos_article_details_from_page(article_url)
                    if article_details:
                        # 使用详情页面的完整信息
                        if article_details.get('title'):
                            title = article_details['title']  # 使用详情页面的标题（更完整）
                        pub_date = article_details.get('date')
                        abstract = article_details.get('abstract', '')
                        authors = article_details.get('authors', '')
                        logger.debug(f"PLOS从详情页面获取完整信息成功: {doi}")
                    
            except Exception as detail_error:
                logger.debug(f"PLOS详情页面信息提取失败 (DOI: {doi}): {detail_error}")
                # 保持搜索结果页面的基本信息
            
            # 构建文章数据（使用详情页面的完整信息）
            article_data = {
                'title': title,
                'abstract': abstract,  # 从详情页面获取的摘要
                'url': article_url,
                'doi': doi,
                'date': pub_date,  # 从详情页面获取的日期
                'journal': journal_name,
                'authors': authors  # 从详情页面获取的作者信息
            }
            
            return article_data
            
        except Exception as e:
            logger.error(f"PLOS从搜索结果提取文章信息失败 (DOI: {doi}): {e}")
            return None

    def _get_plos_journal_path(self, journal_name):
        """获取PLOS期刊路径"""
        return self.journal_code_to_path.get(journal_name, 'plosone')
    
    def _check_plos_article_journal_match(self, dt_elem, expected_journal_name):
        """检查PLOS文章的期刊名称是否与当前正在爬取的期刊匹配"""
        try:
            # 查找期刊名称span元素
            # HTML结构: <span id="article-result-X-journal-name">PLOS Neglected Tropical Diseases</span>
            journal_span = None
            
            # 方法1: 查找包含journal-name的span
            parent_dd = dt_elem.find_next_sibling('dd')
            if parent_dd:
                journal_span = parent_dd.find('span', id=lambda x: x and 'journal-name' in x)
            
            # 方法2: 在dt_elem之后查找
            if not journal_span:
                # 从dt元素开始，查找后续的span元素
                next_elem = dt_elem
                for _ in range(10):  # 最多查找10个后续元素
                    next_elem = next_elem.find_next_sibling()
                    if not next_elem:
                        break
                    journal_span = next_elem.find('span', id=lambda x: x and 'journal-name' in x)
                    if journal_span:
                        break
            
            if journal_span:
                article_journal_name = journal_span.get_text(strip=True)
                logger.debug(f"找到文章期刊名称: {article_journal_name}, 期望: {expected_journal_name}")
                
                # 期刊名称匹配检查
                if self._normalize_plos_journal_name(article_journal_name) == self._normalize_plos_journal_name(expected_journal_name):
                    return article_journal_name
                else:
                    logger.info(f"PLOS期刊不匹配: 文章属于'{article_journal_name}'，当前爬取'{expected_journal_name}'")
                    return None
            else:
                logger.debug("未找到期刊名称span，允许处理")
                return expected_journal_name  # 如果找不到期刊名称，默认允许处理
                
        except Exception as e:
            logger.debug(f"检查期刊匹配时出错: {e}")
            return expected_journal_name  # 出错时默认允许处理
    
    def _normalize_plos_journal_name(self, journal_name):
        """标准化PLOS期刊名称用于比较"""
        if not journal_name:
            return ""
        
        # 移除空格，转换为小写，统一格式
        normalized = journal_name.lower().replace(' ', '').replace('plos', '')
        
        # 处理一些常见的变体
        mapping = {
            'neglectedtropicaldiseases': 'neglectedtropicaldiseases',
            'computationalbiology': 'computationalbiology',
            'globalpublichealth': 'globalpublichealth',
            'digitalhealth': 'digitalhealth',
            'complexsystems': 'complexsystems',
            'mentalhealth': 'mentalhealth',
            'sustainabilityandtransformation': 'sustainabilityandtransformation',
            'one': 'one',
            'biology': 'biology',
            'medicine': 'medicine',
            'genetics': 'genetics',
            'pathogens': 'pathogens',
            'climate': 'climate',
            'water': 'water'
        }
        
        return mapping.get(normalized, normalized)

    def _build_plos_url_from_doi(self, doi):
        """从DOI构建正确的PLOS文章URL"""
        try:
            # DOI格式: 10.1371/journal.pXXX.XXXXXXX
            # 其中pXXX部分指示期刊类型
            if 'journal.pone.' in doi:
                journal_path = 'plosone'
            elif 'journal.pbio.' in doi:
                journal_path = 'plosbiology'
            elif 'journal.pmed.' in doi:
                journal_path = 'plosmedicine'
            elif 'journal.pgen.' in doi:
                journal_path = 'plosgenetics'
            elif 'journal.pcbi.' in doi:
                journal_path = 'ploscompbiol'
            elif 'journal.ppat.' in doi:
                journal_path = 'plospathogens'
            elif 'journal.pntd.' in doi:
                journal_path = 'plosntds'
            elif 'journal.pclm.' in doi:
                journal_path = 'climate'
            elif 'journal.pgph.' in doi:
                journal_path = 'globalpublichealth'
            elif 'journal.pdgh.' in doi:
                journal_path = 'digitalhealth'
            elif 'journal.pcsy.' in doi:
                journal_path = 'complexsystems'
            elif 'journal.pmen.' in doi:
                journal_path = 'mentalhealth'
            elif 'journal.pstr.' in doi:
                journal_path = 'sustainabilitytransformation'
            elif 'journal.pwat.' in doi:
                journal_path = 'water'
            else:
                # 默认使用plosone
                journal_path = 'plosone'
                logger.warning(f"无法从DOI确定期刊类型，使用默认plosone: {doi}")
            
            return f"https://journals.plos.org/{journal_path}/article?id={doi}"
        except Exception as e:
            logger.error(f"从DOI构建URL失败: {e}")
            return f"https://journals.plos.org/plosone/article?id={doi}"  # 默认返回plosone
    
    def _get_plos_total_pages(self, journal_name: str, start_date: datetime, end_date: datetime):
        """获取PLOS搜索结果的总页数"""
        try:
            # 构建第一页的URL来检测总页数
            search_urls = self.build_search_url_with_page(journal_name, start_date, end_date, 1)
            if not search_urls:
                return None
                
            # 使用Selenium访问第一页
            self.driver.get(search_urls[0])
            
            # 等待页面加载
            WebDriverWait(self.driver, 15).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            time.sleep(3)
            
            # 解析页面获取总页数信息
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # 方法1：查找分页导航
            pagination_selectors = [
                '.pagination .page-numbers',
                '.pager .page-item',
                '.search-pagination a',
                '.pagination a'
            ]
            
            max_page = 0
            for selector in pagination_selectors:
                page_links = soup.select(selector)
                for link in page_links:
                    text = link.get_text(strip=True)
                    if text.isdigit():
                        max_page = max(max_page, int(text))
            
            if max_page > 0:
                logger.debug(f"通过分页导航检测到总页数: {max_page}")
                return max_page
            
            # 方法2：查找结果统计信息
            result_info_selectors = [
                '.search-results-info',
                '.results-summary',
                '.search-summary'
            ]
            
            for selector in result_info_selectors:
                info_elem = soup.select_one(selector)
                if info_elem:
                    text = info_elem.get_text()
                    # 查找类似 "1-60 of 420 results" 的文本
                    import re
                    match = re.search(r'of\s+(\d+)\s+results?', text, re.IGNORECASE)
                    if match:
                        total_results = int(match.group(1))
                        total_pages = (total_results + 59) // 60  # 每页60篇，向上取整
                        logger.debug(f"通过结果统计检测到总页数: {total_pages} (总结果: {total_results})")
                        return total_pages
            
            # 方法3：通过文章数量估算（如果第一页有60篇，可能还有更多页）
            doi_elements = soup.find_all('dt', attrs={'data-doi': True})
            if len(doi_elements) >= 60:
                logger.debug("第一页有60篇文章，无法确定总页数，返回None")
                return None
            else:
                logger.debug(f"第一页只有{len(doi_elements)}篇文章，可能只有1页")
                return 1
                
        except Exception as e:
            logger.debug(f"获取PLOS总页数失败: {e}")
            return None
    
    def _get_plos_total_pages_requests(self, journal_name: str, start_date: datetime, end_date: datetime):
        """使用requests方式获取PLOS搜索结果的总页数"""
        try:
            # 构建第一页的URL来检测总页数
            search_urls = self.build_search_url_with_page(journal_name, start_date, end_date, 1)
            if not search_urls:
                return None
                
            # 使用requests访问第一页
            response = self.get_page_with_retry_plos(search_urls[0])
            if not response:
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 方法1：查找分页导航
            pagination_selectors = [
                '.pagination .page-numbers',
                '.pager .page-item',
                '.search-pagination a',
                '.pagination a'
            ]
            
            max_page = 0
            for selector in pagination_selectors:
                page_links = soup.select(selector)
                for link in page_links:
                    text = link.get_text(strip=True)
                    if text.isdigit():
                        max_page = max(max_page, int(text))
            
            if max_page > 0:
                logger.debug(f"通过分页导航检测到总页数: {max_page} (requests)")
                return max_page
            
            # 方法2：查找结果统计信息
            result_info_selectors = [
                '.search-results-info',
                '.results-summary',
                '.search-summary'
            ]
            
            for selector in result_info_selectors:
                info_elem = soup.select_one(selector)
                if info_elem:
                    text = info_elem.get_text()
                    # 查找类似 "1-60 of 420 results" 的文本
                    import re
                    match = re.search(r'of\s+(\d+)\s+results?', text, re.IGNORECASE)
                    if match:
                        total_results = int(match.group(1))
                        total_pages = (total_results + 59) // 60  # 每页60篇，向上取整
                        logger.debug(f"通过结果统计检测到总页数: {total_pages} (总结果: {total_results}, requests)")
                        return total_pages
            
            # 方法3：通过文章数量估算
            doi_elements = soup.find_all('dt', attrs={'data-doi': True})
            if len(doi_elements) >= 60:
                logger.debug("第一页有60篇文章，无法确定总页数，返回None (requests)")
                return None
            else:
                logger.debug(f"第一页只有{len(doi_elements)}篇文章，可能只有1页 (requests)")
                return 1
                
        except Exception as e:
            logger.debug(f"获取PLOS总页数失败 (requests): {e}")
            return None
    
    def _scrape_all_pages_with_selenium(self, journal_name: str, start_date: datetime, end_date: datetime):
        """使用Selenium分页爬取PLOS期刊的所有结果"""
        all_articles = []
        page = 1
        scrape_success = True  # 爬取成功标志
        
        # 获取总页数（可选）
        total_pages = self._get_plos_total_pages(journal_name, start_date, end_date)
        if total_pages:
            logger.info(f"PLOS {journal_name} 检测到总共 {total_pages} 页")
        else:
            logger.info(f"PLOS {journal_name} 无法检测总页数，将遍历直到空页面结束")
        
        while True:
            try:
                # 构建分页搜索URL列表（支持回退）
                search_urls = self.build_search_url_with_page(journal_name, start_date, end_date, page)
                if total_pages:
                    logger.info(f"PLOS {journal_name} 第{page}页（共{total_pages}页）尝试URL: {search_urls[0]}")
                else:
                    logger.info(f"PLOS {journal_name} 第{page}页尝试URL: {search_urls[0]}")
                
                # 爬取当前页面，支持URL回退
                page_articles = self._scrape_single_page_with_selenium_fallback(search_urls, journal_name, start_date, end_date)
                
                # 检测真正的空页面：如果页面没有文章，说明已超过实际页数
                if not page_articles:
                    logger.info(f"PLOS {journal_name} 第{page}页为空页面，已超过实际页数，停止分页")
                    break
                
                # 检测页面有内容但都被过滤的情况
                if (len(page_articles) == 1 and 
                    page_articles[0].get('__page_has_content_but_filtered__')):
                    # 获取原始DOI数量判断是否继续翻页
                    original_doi_count = page_articles[0].get('__original_doi_count__', 0)
                    if original_doi_count < 60:
                        logger.info(f"PLOS {journal_name} 第{page}页DOI数量不足60个（{original_doi_count}），已是最后一页")
                        break
                    else:
                        logger.info(f"PLOS {journal_name} 第{page}页有文章但都不属于当前期刊，页面DOI满60个，继续下一页")
                        page += 1
                        time.sleep(2)
                        continue
                
                # 检测是否为最后一页：基于页面DOI总数判断
                original_doi_count = 0
                if len(page_articles) > 0:
                    original_doi_count = page_articles[0].get('__original_doi_count__', len(page_articles))
                
                if original_doi_count < 60:
                    logger.info(f"PLOS {journal_name} 第{page}页DOI数量不足60个（{original_doi_count}），已是最后一页")
                    # 但仍然要处理这一页的有效文章
                else:
                    logger.debug(f"PLOS {journal_name} 第{page}页DOI数量达到60个，可能还有更多页")
                
                # 去重处理（Selenium版本）
                new_articles = []
                duplicate_count = 0
                if not hasattr(self, '_selenium_seen_dois'):
                    self._selenium_seen_dois = set()
                
                for article in page_articles:
                    # 跳过特殊标记
                    if article.get('__page_has_content_but_filtered__'):
                        continue
                        
                    doi = article.get('doi', '') if article else ''
                    if doi and doi not in self._selenium_seen_dois:
                        self._selenium_seen_dois.add(doi)
                        new_articles.append(article)
                    else:
                        duplicate_count += 1
                
                all_articles.extend(new_articles)
                if total_pages:
                    logger.info(f"PLOS {journal_name} 第{page}页（共{total_pages}页）获得{len(page_articles)}篇文章，去重后{len(new_articles)}篇，重复{duplicate_count}篇，累计{len(all_articles)}篇")
                else:
                    logger.info(f"PLOS {journal_name} 第{page}页获得{len(page_articles)}篇文章，去重后{len(new_articles)}篇，重复{duplicate_count}篇，累计{len(all_articles)}篇")
                
                # 检查是否还有下一页：基于原始DOI数量
                if original_doi_count < 60:
                    logger.info(f"PLOS {journal_name} 第{page}页原始DOI数量不足60个，已是最后一页")
                    break
                
                page += 1
                time.sleep(2)  # 避免请求过快
                
            except Exception as e:
                logger.error(f"PLOS {journal_name} 第{page}页爬取失败: {e}")
                # 如果是第一页就失败，说明是访问问题，需要备选逻辑
                if page == 1:
                    scrape_success = False
                break
        
        logger.info(f"PLOS {journal_name} 分页爬取完成，共{page-1}页，获得{len(all_articles)}篇文章")
        return all_articles, scrape_success
    
    def build_search_url_with_page(self, journal_name: str, start_date: datetime, end_date: datetime, page: int = 1):
        """构建带分页的PLOS搜索URL，支持URL回退机制"""
        # 从期刊名称提取代码
        journal_code = journal_name.replace(' ', '').replace('PLOS', 'PLOS')
        journal_path = self.journal_code_to_path.get(journal_code, 'plosone')
        
        # 构建搜索URL
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
        
        # PLOS新的分页格式：使用page参数，从1开始
        # page=0和page=1是相同的，所以确保page>=1
        actual_page = max(1, page)
        
        params = {
            'filterJournals': journal_code,
            'filterStartDate': start_date_str,
            'filterEndDate': end_date_str,  # 添加结束日期过滤
            'resultsPerPage': '60',
            'q': '',
            'sortOrder': 'DATE_NEWEST_FIRST',
            'page': str(actual_page)
        }
        
        # 构建完整URL参数
        param_str = '&'.join([f"{k}={v}" for k, v in params.items()])
        
        # 构建URL列表，优先尝试journal_path，如果404则尝试journal_code
        urls_to_try = []
        
        # 第一个URL：使用映射的路径
        base_search_url1 = f"https://journals.plos.org/{journal_path}/search"
        urls_to_try.append(f"{base_search_url1}?{param_str}")
        
        # 第二个URL：如果第一个失败，尝试使用journal_code（小写）
        if journal_path != journal_code.lower():
            base_search_url2 = f"https://journals.plos.org/{journal_code.lower()}/search"
            urls_to_try.append(f"{base_search_url2}?{param_str}")
        
        # 第三个URL：如果还失败，尝试去掉PLOS前缀
        journal_without_plos = journal_code.replace('PLOS', '').lower()
        if journal_without_plos and journal_without_plos != journal_path:
            base_search_url3 = f"https://journals.plos.org/{journal_without_plos}/search"
            urls_to_try.append(f"{base_search_url3}?{param_str}")
        
        return urls_to_try
    
    def _scrape_single_page_with_selenium_fallback(self, urls: list, journal_name: str, start_date: datetime, end_date: datetime):
        """使用Selenium爬取PLOS期刊单页，支持URL回退机制"""
        for i, url in enumerate(urls):
            try:
                logger.info(f"尝试第{i+1}个URL: {url}")
                articles = self._scrape_single_page_with_selenium(url, journal_name, start_date, end_date)
                if articles:  # 如果成功获取到文章，返回结果
                    logger.info(f"URL成功: {url}")
                    return articles
                else:
                    logger.info(f"URL无结果，尝试下一个")
            except Exception as e:
                logger.warning(f"URL失败: {url}, 错误: {e}")
                if i < len(urls) - 1:  # 如果不是最后一个URL
                    logger.info(f"尝试回退URL...")
                    continue
                else:
                    logger.error(f"所有URL都失败")
                    break
        return []
    
    def _scrape_single_page_with_selenium(self, url: str, journal_name: str, start_date: datetime, end_date: datetime):
        """使用Selenium爬取PLOS期刊单页"""
        articles = []
        try:
            logger.info(f"Selenium开始访问URL: {url}")
            self.driver.get(url)
            
            # 等待页面完全加载
            WebDriverWait(self.driver, 15).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            
            # 额外等待JavaScript动态内容加载
            time.sleep(8)
            
            # 等待搜索结果容器出现（基于截图结构）
            try:
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "search-results-list"))
                )
                logger.info("搜索结果容器已加载")
            except Exception as e:
                logger.debug(f"等待搜索结果容器超时（这是正常情况）: {str(e).split('Stacktrace:')[0].strip()}")
            
            # 再次等待确保动态内容完全渲染
            time.sleep(5)
            
            logger.info(f"Selenium页面和动态内容加载完成: {journal_name}")
            
            # 使用Selenium解析页面
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # 根据实际PLOS页面结构解析（基于用户截图）
            # 方法1：查找data-doi属性的dt元素
            doi_elements = soup.find_all('dt', attrs={'data-doi': True})
            logger.info(f"Selenium找到{len(doi_elements)}个data-doi元素")
            
            # 如果仍然没找到，尝试滚动页面触发懒加载
            if len(doi_elements) == 0:
                logger.info("尝试滚动页面触发懒加载...")
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(3)
                self.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(2)
                
                # 重新解析
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                doi_elements = soup.find_all('dt', attrs={'data-doi': True})
                logger.info(f"滚动后找到{len(doi_elements)}个data-doi元素")
            
            if len(doi_elements) > 0:
                logger.info(f"PLOS {journal_name} 页面找到{len(doi_elements)}个DOI元素")
                processed_count = 0
                filtered_count = 0
                
                for dt_elem in doi_elements:  # 处理所有找到的文章
                    try:
                        data_doi = dt_elem.get('data-doi')
                        if data_doi:
                            processed_count += 1
                            # 使用新的搜索结果页面直接提取方法（与requests方法保持一致）
                            logger.debug(f"PLOS Selenium开始处理DOI: {data_doi}")
                            article_data = self._extract_plos_article_from_search_result(dt_elem, data_doi, journal_name)
                            
                            if article_data:
                                # 服务器端已经按时间范围过滤，直接包含所有返回的文章
                                article_title = article_data.get('title', '')[:50]
                                article_date = article_data.get('date')
                                
                                articles.append(article_data)
                                logger.info(f"PLOS Selenium文章: '{article_title}...', 日期: {article_date}")
                            else:
                                # 这里可能是期刊不匹配被过滤了
                                filtered_count += 1
                                logger.debug(f"PLOS Selenium文章被过滤: DOI={data_doi}")
                                    
                    except Exception as e:
                        logger.error(f"解析PLOS data-doi元素失败: {e}")
                        continue
                
                logger.info(f"PLOS {journal_name} 页面处理完成: 总DOI={len(doi_elements)}, 处理={processed_count}, 过滤={filtered_count}, 有效={len(articles)}")
                
                # 返回结果时需要区分情况：
                # 1. 如果页面没有DOI元素 -> 真正的空页面
                # 2. 如果有DOI元素但都被过滤 -> 页面有内容但不属于当前期刊
                # 在所有情况下都要传递页面DOI总数信息
                if len(articles) == 0 and len(doi_elements) > 0:
                    # 页面有文章但都不属于当前期刊，返回特殊标记（包含DOI总数）
                    return [{'__page_has_content_but_filtered__': True, '__original_doi_count__': len(doi_elements)}]
                elif len(articles) > 0:
                    # 有有效文章时，在第一篇文章中添加DOI总数信息
                    articles[0]['__original_doi_count__'] = len(doi_elements)
            
            # 方法2：如果方法1没找到，尝试查找包含doi.org的链接
            if len(articles) == 0:
                logger.info("方法1未找到结果，尝试查找doi.org链接")
                all_links = soup.find_all('a', href=True)
                doi_links_alt = [link for link in all_links if 'doi.org' in link.get('href', '')]
                logger.info(f"备选方案：找到{len(doi_links_alt)}个包含doi.org的链接")
                
                for link in doi_links_alt:  # 处理所有找到的链接
                    try:
                        doi_url = link.get('href')
                        if 'doi.org' in doi_url:
                            article_data = self._get_plos_article_details(doi_url)
                            if article_data:
                                article_data['journal'] = journal_name
                                articles.append(article_data)
                                logger.info(f"PLOS文章: {article_data.get('title', 'Unknown')[:80]}")
                                
                    except Exception as e:
                        logger.error(f"解析备选DOI链接失败: {e}")
                        continue
            
            # 方法3：如果还是没找到，尝试原始的search-results-doi方式
            if len(articles) == 0:
                logger.info("尝试原始的search-results-doi方式")
                doi_links = soup.find_all('p', class_='search-results-doi')
                logger.info(f"找到{len(doi_links)}个search-results-doi元素")
                
                for doi_elem in doi_links:
                    try:
                        link_elem = doi_elem.find('a', href=True)
                        if link_elem:
                            doi_url = link_elem.get('href')
                            if 'doi.org' in doi_url:
                                article_data = self._get_plos_article_details(doi_url)
                                if article_data:
                                    article_data['journal'] = journal_name
                                    articles.append(article_data)
                                    logger.info(f"PLOS文章: {article_data.get('title', 'Unknown')[:80]}")
                                    
                    except Exception as e:
                        logger.error(f"解析PLOS DOI链接失败: {e}")
                        continue
                    
        except Exception as e:
            logger.error(f"Selenium爬取PLOS失败: {e}")
        
        logger.info(f"Selenium爬取{journal_name}单页完成，获得{len(articles)}篇文章")
        return articles
    
    def _get_plos_article_details(self, doi_url):
        """获取PLOS文章详情"""
        try:
            response = self.session.get(doi_url, timeout=30)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 标题: <h1 id="title" class="title">
                title_elem = soup.find('h1', id='title', class_='title') or soup.find('h1', class_='title')
                title = title_elem.get_text(strip=True) if title_elem else ''
                
                # 获取摘要/Introduction
                abstract = ''
                # 先尝试获取摘要
                abstract_elem = soup.find('div', class_='abstract') or \
                              soup.find('div', id='abstract') or \
                              soup.find('section', class_='abstract')
                
                if abstract_elem:
                    abstract = abstract_elem.get_text(strip=True)
                
                # 如果没有摘要，尝试获取Introduction
                if not abstract:
                    intro_elem = soup.find('div', class_='introduction') or \
                               soup.find('section', class_='introduction')
                    if intro_elem:
                        abstract = intro_elem.get_text(strip=True)[:500] + "..."
                
                # 获取DOI
                doi = doi_url.split('/')[-1] if '/' in doi_url else ''
                
                # 日期: <time class="published">August 20, 2025</time>
                pub_date = datetime.now().date()
                date_elem = soup.find('time', class_='published')
                if date_elem:
                    date_text = date_elem.get_text(strip=True)
                    try:
                        pub_date = dateparser.parse(date_text).date()
                    except:
                        pass
                else:
                    # 备用方案：meta标签
                    meta_date_elem = soup.find('meta', attrs={'name': 'citation_publication_date'})
                    if meta_date_elem:
                        try:
                            pub_date = dateparser.parse(meta_date_elem.get('content')).date()
                        except:
                            pass
                
                # 作者信息
                authors = ''
                author_elems = soup.find_all('meta', attrs={'name': 'citation_author'})
                if author_elems:
                    authors = '; '.join([elem.get('content', '') for elem in author_elems])
                
                return {
                    'title': title,
                    'abstract': abstract,
                    'doi': doi,
                    'url': doi_url,
                    'date': pub_date,
                    'authors': authors
                }
                
        except Exception as e:
            logger.error(f"获取PLOS文章详情失败: {e}")
        
        return None
    
    def _get_plos_article_details_from_page(self, article_url):
        """基于文章页面URL获取PLOS文章详情，根据用户截图优化"""
        try:
            # 使用增强的重试机制
            response = self.get_page_with_retry_plos(article_url)
            if not response:
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 标题: 基于截图中的结构
            title = ''
            title_selectors = [
                'h1#artTitle',  # 截图中看到的ID
                'div.title-authors h1',  # 截图中的结构  
                'div.article-title-etc h1',  # 从截图看到的结构
                'h1.title',
                'h1#title',
                'h1'
            ]
            
            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    logger.debug(f"PLOS标题提取成功，使用选择器: {selector}")
                    break
            
            # 摘要: 基于截图中的结构
            abstract = ''
            abstract_selectors = [
                'div.article-content div#artText p',  # 截图中的抽象内容结构
                'div.abstract-content',
                'section.abstract',
                'div#abstract',
                'div.abstract'
            ]
            
            for selector in abstract_selectors:
                abstract_elem = soup.select_one(selector)
                if abstract_elem:
                    abstract = abstract_elem.get_text(strip=True)
                    break
            
            # 如果没有找到摘要，尝试查找Introduction部分
            if not abstract:
                intro_selectors = [
                    'div.article-content p',
                    'div.article-text p',
                    '.introduction p'
                ]
                for selector in intro_selectors:
                    intro_elems = soup.select(selector)
                    if intro_elems:
                        # 取前几段作为摘要
                        abstract = ' '.join([p.get_text(strip=True) for p in intro_elems[:3]])
                        if len(abstract) > 500:
                            abstract = abstract[:500] + "..."
                        break
            
            # DOI: 从URL中提取
            doi = ''
            if 'id=' in article_url:
                doi = article_url.split('id=')[-1]
            
            # 日期: 基于截图中的结构优化 
            pub_date = None  # 不设置默认日期，留给后续处理
            date_selectors = [
                'li#artPubDate',  # 截图中清楚看到的ID: Published: September 3, 2025
                'ul.date-doi li#artPubDate',  # 完整的层级路径
                'ul.date-doi li',
                'time.published',
                '.pub-date',
                'meta[name="citation_publication_date"]',  # meta标签日期
                'meta[name="DC.date"]'  # Dublin Core日期
            ]
            
            for selector in date_selectors:
                try:
                    if selector.startswith('meta'):
                        date_elem = soup.find('meta', attrs={'name': selector.split('[name="')[1].split('"]')[0]})
                        if date_elem:
                            date_text = date_elem.get('content', '').strip()
                        else:
                            continue
                    else:
                        date_elem = soup.select_one(selector)
                        if date_elem:
                            date_text = date_elem.get_text(strip=True)
                        else:
                            continue
                    
                    # 清理日期文本
                    date_text = date_text.replace('Published:', '').replace('published', '').strip()
                    
                    if date_text:
                        parsed_date = dateparser.parse(date_text)
                        if parsed_date:
                            pub_date = parsed_date.date()
                            logger.debug(f"PLOS日期解析成功，使用选择器: {selector}, 日期: {pub_date}")
                            break
                        else:
                            logger.debug(f"PLOS日期解析失败，选择器: {selector}, 无法解析: {date_text}")
                    
                except Exception as date_error:
                    logger.debug(f"PLOS日期解析异常，选择器: {selector}, 错误: {date_error}")
                    continue
            
            # 如果从详情页面没有找到日期，尝试从摘要或Introduction部分查找
            if not pub_date:
                logger.debug("详情页面未找到日期，尝试从摘要和Introduction查找")
                content_selectors = [
                    'div.article-content div#artText',  # 截图中的文章内容区域
                    'div.abstract-content',
                    'section.abstract',
                    'div#abstract',
                    'div.abstract',
                    'div.article-text',
                    '.introduction'
                ]
                
                for content_selector in content_selectors:
                    try:
                        content_elem = soup.select_one(content_selector)
                        if content_elem:
                            content_text = content_elem.get_text()
                            # 查找日期模式
                            import re
                            date_patterns = [
                                r'Published:\s*([A-Za-z]+ \d{1,2}, \d{4})',
                                r'published\s*([A-Za-z]+ \d{1,2}, \d{4})',
                                r'(\d{4}-\d{2}-\d{2})',
                                r'([A-Za-z]+ \d{1,2}, \d{4})'
                            ]
                            
                            for pattern in date_patterns:
                                match = re.search(pattern, content_text, re.IGNORECASE)
                                if match:
                                    date_text = match.group(1)
                                    try:
                                        parsed_date = dateparser.parse(date_text)
                                        if parsed_date:
                                            pub_date = parsed_date.date()
                                            logger.debug(f"PLOS从内容中找到日期: {pub_date}")
                                            break
                                    except:
                                        continue
                            if pub_date:
                                break
                    except Exception as e:
                        logger.debug(f"从内容查找日期失败: {e}")
                        continue
            
            # 如果仍然没有日期，设置为None而不是默认日期
            if not pub_date:
                logger.warning(f"PLOS文章日期解析完全失败，设置为None: {article_url}")
                pub_date = None
            
            # 作者信息: 基于截图中的结构优化
            authors = ''
            # 方法1: meta标签
            author_elems = soup.find_all('meta', attrs={'name': 'citation_author'})
            if author_elems:
                authors = '; '.join([elem.get('content', '') for elem in author_elems])
                logger.debug(f"PLOS作者信息从meta标签获取: {len(author_elems)}个作者")
            else:
                # 方法2: 基于截图中的页面结构
                author_selectors = [
                    'ul.author-list li a[data-author-id]',  # 截图中清楚显示的结构
                    'li[data-js-tooltip="tooltip_trigger"] a[data-author-id]',  # 更精确的截图结构
                    'div.title-authors ul.author-list li a',  # 从截图看到的层级
                    'div.title-authors .author-list',
                    '.author-names',
                    '.contributors'
                ]
                for selector in author_selectors:
                    if 'a[data-author-id]' in selector:
                        # 处理链接元素
                        author_links = soup.select(selector)
                        if author_links:
                            author_names = [link.get_text(strip=True) for link in author_links if link.get_text(strip=True)]
                            if author_names:
                                authors = ', '.join(author_names)
                                logger.debug(f"PLOS作者信息从链接获取: {selector}, {len(author_names)}个作者")
                                break
                    else:
                        # 处理容器元素
                        author_elem = soup.select_one(selector)
                        if author_elem:
                            authors = author_elem.get_text(strip=True)
                            logger.debug(f"PLOS作者信息从容器获取: {selector}")
                            break
            
            # 验证关键字段
            if not title:
                return None
                
            article_data = {
                'title': title,
                'abstract': abstract if abstract else '摘要未找到',
                'doi': doi,
                'url': article_url,
                'date': pub_date,
                'authors': authors if authors else '作者未找到'
            }
            
            return article_data
            
        except Exception as e:
            logger.error(f"获取PLOS文章详情失败 ({article_url}): {e}")
        
        return None
    
    def _close_selenium_driver(self):
        """关闭Selenium WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("PLOS Selenium WebDriver已关闭")
            except Exception as e:
                logger.error(f"关闭PLOS Selenium WebDriver失败: {e}")
            finally:
                self.driver = None
    
    def close(self):
        """关闭资源"""
        self._close_selenium_driver()
        
        if self.session:
            try:
                self.session.close()
                logger.info("PLOS Requests session已关闭")
            except Exception as e:
                logger.error(f"关闭PLOS requests session失败: {e}")
    
    def _scrape_with_selenium(self, url, journal_name):
        """使用Selenium爬取PLOS期刊"""
        articles = []
        try:
            logger.info(f"Selenium开始访问URL: {url}")
            self.driver.get(url)
            
            # 增加等待时间让JavaScript完全加载
            time.sleep(5)  
            
            # 等待页面完全加载
            WebDriverWait(self.driver, 15).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            
            logger.info(f"Selenium页面加载完成: {journal_name}")
            
            # 使用Selenium解析页面
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # 根据实际PLOS页面结构解析（基于用户截图）
            # 方法1：查找data-doi属性的dt元素
            doi_elements = soup.find_all('dt', attrs={'data-doi': True})
            logger.info(f"找到{len(doi_elements)}个data-doi元素")
            
            if len(doi_elements) > 0:
                for dt_elem in doi_elements:  # 处理所有找到的文章
                    try:
                        data_doi = dt_elem.get('data-doi')
                        if data_doi:
                            # 构建完整的DOI URL
                            doi_url = f"https://doi.org/{data_doi}"
                            
                            # 或者查找dt元素内的链接
                            link_elem = dt_elem.find('a', href=True)
                            if link_elem:
                                article_link = link_elem.get('href')
                                if article_link.startswith('/'):
                                    article_link = f"https://journals.plos.org{article_link}"
                                
                                # 优先使用文章页面链接（基于href构建的URL）
                                article_data = self._get_plos_article_details_from_page(article_link)
                                if not article_data:
                                    # 回退到DOI链接
                                    article_data = self._get_plos_article_details(doi_url)
                                
                                if article_data:
                                    article_data['journal'] = journal_name
                                    articles.append(article_data)
                                    logger.info(f"PLOS文章: {article_data.get('title', 'Unknown')[:80]}")
                                    
                    except Exception as e:
                        logger.error(f"解析PLOS data-doi元素失败: {e}")
                        continue
                    
                    # 移除所有数量限制，处理所有符合时间要求的文章
            
            # 方法2：如果方法1没找到，尝试查找包含doi.org的链接
            if len(articles) == 0:
                logger.info("方法1未找到结果，尝试查找doi.org链接")
                all_links = soup.find_all('a', href=True)
                doi_links_alt = [link for link in all_links if 'doi.org' in link.get('href', '')]
                logger.info(f"备选方案：找到{len(doi_links_alt)}个包含doi.org的链接")
                
                for link in doi_links_alt:  # 处理所有找到的链接
                    try:
                        doi_url = link.get('href')
                        if 'doi.org' in doi_url:
                            article_data = self._get_plos_article_details(doi_url)
                            if article_data:
                                article_data['journal'] = journal_name
                                articles.append(article_data)
                                logger.info(f"PLOS文章: {article_data.get('title', 'Unknown')[:80]}")
                                
                    except Exception as e:
                        logger.error(f"解析备选DOI链接失败: {e}")
                        continue
                    
                    # 移除所有数量限制，处理所有符合时间要求的文章
            
            # 方法3：如果还是没找到，尝试原始的search-results-doi方式
            if len(articles) == 0:
                logger.info("尝试原始的search-results-doi方式")
                doi_links = soup.find_all('p', class_='search-results-doi')
                logger.info(f"找到{len(doi_links)}个search-results-doi元素")
                
                for doi_elem in doi_links:
                    try:
                        link_elem = doi_elem.find('a', href=True)
                        if link_elem:
                            doi_url = link_elem.get('href')
                            if 'doi.org' in doi_url:
                                article_data = self._get_plos_article_details(doi_url)
                                if article_data:
                                    article_data['journal'] = journal_name
                                    articles.append(article_data)
                                    logger.info(f"PLOS文章: {article_data.get('title', 'Unknown')[:80]}")
                                    
                    except Exception as e:
                        logger.error(f"解析PLOS DOI链接失败: {e}")
                        continue
                    
                    # 移除所有数量限制，处理所有符合时间要求的文章
                    
        except Exception as e:
            logger.error(f"Selenium爬取PLOS失败: {e}")
        
        logger.info(f"Selenium爬取{journal_name}完成，获得{len(articles)}篇文章")
        return articles
    
    def _close_selenium_driver(self):
        """关闭Selenium WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("PLOS Selenium WebDriver已关闭")
            except Exception as e:
                logger.error(f"关闭PLOS Selenium WebDriver失败: {e}")
            finally:
                self.driver = None
    
    def close(self):
        """关闭资源"""
        self._close_selenium_driver()
        
        if self.session:
            try:
                self.session.close()
                logger.info("PLOS Requests session已关闭")
            except Exception as e:
                logger.error(f"关闭PLOS requests session失败: {e}")

# 工厂函数
def create_parser(journal_type: str, database=None, paper_agent=None) -> BaseParser:
    """创建指定期刊的解析器实例
    
    Args:
        journal_type: 期刊类型 (nature, science, cell, plos)
        database: 数据库实例
        paper_agent: AI分析代理
        
    Returns:
        BaseParser: 解析器实例
    """
    journal_type = journal_type.lower()
    
    if journal_type == 'nature':
        return NatureParser(database, paper_agent)
    elif journal_type == 'science':
        return ScienceParser(database, paper_agent)
    elif journal_type == 'cell':
        return CellParser(database, paper_agent)
    elif journal_type == 'plos':
        return PLOSParser(database, paper_agent)
    else:
        raise ValueError(f"不支持的期刊类型: {journal_type}")
