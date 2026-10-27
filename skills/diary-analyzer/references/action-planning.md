# 行动规划规则

来源：`backend/services/analysis_pipeline.py` 的 `ACTION_PLANNING_PROMPT`，提取日期 2026-10-27。保留实际代码中的业务规则，输出载体改为 [Markdown 协议](markdown-format.md)。字段名表示转换后的 JSON 栏目；“数组”在稿件中对应列表。分析正文不得带序号，结构标题和列表由协议规定。

本 skill 使用脚本生成的 P1、E1-S1、D-S1 等来源别名。稿件填写别名及连续摘录，转换器生成 source_key。月份输入转换为后端字段 recurrence_month。推荐日程只保存到行动项，是否同步到正式日程由用户在项目内操作。

你负责把一篇日记中的后续计划与 AI 分析得出的可行动建议整理成独立行动项，并为每个行动项生成可编辑的推荐日程。

## 事实边界
1. 只能使用输入的后续计划和可行动建议，不得从其他分析类型、历史日记或长期画像扩展行动。
2. 后续计划和可行动建议只是行动项的来源，不能改写原日记或原分析内容。
3. 行动项必须是用户可以单独安排、单独完成的一件具体事情。

## 原子化规则
1. 一条行动项只能包含一件可独立安排、独立完成的事情。
2. 如果一句话包含两个可以设置不同时间、不同循环规则，或可以分别完成的事项，必须拆成两条行动项。
3. 不拆分同一行动中无法单独完成的必要步骤。
4. 每条行动项只使用一个清晰的主要动作命名，不使用“以及”“并且”等连接两个独立动作。
5. 输出前逐项自检：是否可以拆成两个分别完成的事项；如果可以，先拆分再输出。

## 去重规则
1. 后续计划和可行动建议表达同一事项时合并成一个行动项，并保留全部来源键。
2. 名称相近但完成标准不同的事项不能合并。
3. 分析观点、愿望、抽象目标、情绪和解释不能直接作为行动项。
4. 每个行动项必须返回 source 数组；每项包含 source_key 和来自输入原文的连续摘录 text。

## 推荐日程规则
1. 推荐值必须符合日程字段：全天，或同时提供开始时间和结束时间；结束时间必须晚于开始时间。
2. 不支持跨日。
3. 循环类型只能使用 NONE、DAILY、WEEKLY、MONTHLY_DATE、MONTHLY_NTH_WEEKDAY、YEARLY、WORKDAY、REST_DAY。
4. NONE 不填写循环字段；WEEKLY 必须填写 weekdays；MONTHLY_DATE 必须填写 month_day；MONTHLY_NTH_WEEKDAY 必须填写 nth_week 和 nth_weekday；YEARLY 必须填写 month 和 month_day。
5. recurrence_until 与 recurrence_count 只能二选一。
6. 原文出现“定期”“经常”“坚持”等重复语义时，必须使用非 NONE 循环类型；未给出准确频率时，结合事项性质和上下文推断一个合理、保守且可执行的频率。
7. 即使原文没有重复词，天然需要持续执行的事项也应根据其性质推断循环规则；NONE 只用于一次性事项或不具备持续执行特征的事项。
8. diary_date 用于解释“明天”“下周二”等相对日期；analysis_date 是本次分析日期，推荐日期不得早于 analysis_date；timezone 用于日期边界计算。
9. 信息不足时给出保守、可编辑的推荐，不编造硬性截止要求。
10. 每个行动项只能有一个推荐日程对象。

## 日程字段填写说明
- `interval`：循环间隔，正整数；例如 DAILY + 2 表示每 2 天一次，WEEKLY + 1 表示每周一次。
- `weekdays`：每周重复的星期值数组，使用数字编码：0=周日、1=周一、2=周二、3=周三、4=周四、5=周五、6=周六。仅 WEEKLY 使用，其他类型填 []。
- `month`：每年重复的月份，取值 1-12；仅 YEARLY 使用，例如每年 8 月 4 日填写 month=8、month_day=4。
- `month_day`：月份中的日期，取值 1-31；MONTHLY_DATE 表示每月该日，YEARLY 与 month 配合表示每年该月该日。
- `nth_week`：每月第几个星期，取值 1-5；例如每月第 2 个星期一填写 nth_week=2、nth_weekday=1。
- `nth_weekday`：第几个星期几，使用与 weekdays 相同的 0-6 编码；仅 MONTHLY_NTH_WEEKDAY 使用。
- `recurrence_until`：循环结束日期，格式 YYYY-MM-DD；与 recurrence_count 二选一，没有明确结束日期时填 null。
- `recurrence_count`：最多执行次数，正整数；与 recurrence_until 二选一，没有明确次数时填 null。
- `start_date`：第一次执行日期，格式 YYYY-MM-DD。日记中的“明天”“下周二”等先以 diary_date 推算，再确保不早于 analysis_date。
- `start_time` / `end_time`：非全天日程的开始和结束时间，格式 HH:MM；全天日程必须都填 null。

## 循环类型示例
- 不循环：recurrence_type=NONE，interval=1，weekdays=[]，month=null，month_day=null，nth_week=null，nth_weekday=null，recurrence_until=null，recurrence_count=null。
- “定期涂药”未给出频率时，根据事项性质保守推断为每天：recurrence_type=DAILY，interval=1。
- 每周一和周三：recurrence_type=WEEKLY，interval=1，weekdays=[1,3]。
- 每月 15 日：recurrence_type=MONTHLY_DATE，interval=1，month_day=15。
- 每月第 2 个星期一：recurrence_type=MONTHLY_NTH_WEEKDAY，interval=1，nth_week=2，nth_weekday=1。
- 每年 8 月 4 日：recurrence_type=YEARLY，interval=1，month=8，month_day=4。
- 每 3 天一次：recurrence_type=DAILY，interval=3，其他循环定位字段全部为空。
- 工作日/休息日：recurrence_type=WORKDAY 或 REST_DAY，interval=1，weekdays、month、month_day、nth_week、nth_weekday 全部为空。
