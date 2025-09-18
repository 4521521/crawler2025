# 学术期刊轻量版爬虫

一个轻量级的学术期刊爬虫系统，支持Nature、Science、Cell、PLOS四个期刊的论文抓取和AI相关性分析，导出为Excel、CSV或JSON格式。

## 快速开始

### 安装依赖
```bash
pip install -r requirements.txt
```

### 基本用法
```bash
# 爬取指定期刊的论文
python main.py -j [期刊名] --start-date [开始日期] --end-date [结束日期] --format [格式]
```

### 参数说明
- `-j, --journal`: 期刊名称 (nature, science, cell, plos)
- `--start-date`: 开始日期 (格式: YYYY-MM-DD)
- `--end-date`: 结束日期 (格式: YYYY-MM-DD)
- `--format`: 导出格式 (excel, csv, json)

### 使用示例
```bash
# 爬取Nature期刊最近3天的论文，导出为Excel
python main.py -j nature --start-date 2025-09-14 --end-date 2025-09-16 --format xlsx

# 爬取Science期刊指定时间段的论文，导出为CSV
python main.py -j science --start-date 2025-09-12 --end-date 2025-09-16 --format csv

# 爬取Cell期刊论文，导出为JSON
python main.py -j cell --start-date 2025-09-15 --end-date 2025-09-16 --format json

# 同样支持指定子刊爬取
# 只爬取Nature期刊的特定子刊
python main.py -j nature --subjournal "Nature" --start-date 2025-09-12 --end-date 2025-09-16
  
# 只爬取特定Cell子刊
python main.py -j cell --subjournal "Cell Host & Microbe" --start-date 2025-09-12 --end-date 2025-09-16 --format xlsx
```

## 执行流程

1. **读取配置**: 从config.yaml读取期刊列表和AI配置
2. **期刊解析**: 根据指定期刊读取子刊列表
3. **论文抓取**: 遍历所有子刊，抓取指定时间范围的论文
4. **AI分析**: 使用大模型判断论文是否与AI相关
5. **分类导出**: 将论文分为"AI相关"和"非AI相关"两个文件导出

## 输出结果

系统会在exports目录下生成文件：
- `exports/excel/`: Excel格式文件
- `exports/csv/`: CSV格式文件  
- `exports/json/`: JSON格式文件

每个期刊会生成两个文件：
- `{期刊}_papers_AI相关_{开始日期}_{结束日期}.{格式}`
- `{期刊}_papers_非AI相关_{开始日期}_{结束日期}.{格式}`

## 执行统计

执行完成后会显示统计信息：
```
期刊         抓取文章      AI相关       非AI相关      子刊成功      状态
--------------------------------------------------------------------------------
NATURE       156          28           128          124/124       成功
--------------------------------------------------------------------------------
总计         156          28           128          --            1/1成功
```

## 配置文件

修改config.yaml可以配置：
- AI分析模型和API配置
- 期刊列表文件路径
- 期刊判断配置文件路径

## 注意事项

- 确保网络连接稳定
- 大时间范围爬取可能需要较长时间
- AI分析需要配置有效的API密钥
- 建议单次爬取时间范围不超过7天