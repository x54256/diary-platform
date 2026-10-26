import json
from pathlib import Path
from collections import Counter
R=Path(__file__).resolve().parent;s=json.loads((R/'预检.json').read_text());total=Counter()
for d in s['days']:total.update(d['counts'])
rows=[]
for d in s['days']:
 c=d['counts'];db=d.get('database_target')or{};rows.append('| '+' | '.join([d['date'],str(c.get('RELATED',0)),str(c.get('NO_RELATION',0)),str(c.get('UNRESOLVED',0)),db.get('status','未知'),d.get('local_reason','通过'),f"[完整稿](<{d['draft']}>)"])+' |')
text=f'''# 9月、10月关系稿入库预检

范围：9月20份、10月15份当前稿，共35份、2287对判断；{total['RELATED']}条关系、{total['NO_RELATION']}对无关系、{total['UNRESOLVED']}对未决。仅选择最新明确索引中的当前版本，旧草稿与修订前文件不重复导入。

本轮状态：**尚未写入数据库；有效入库包0份**。本地解析全部通过，但官方 `prepare-storage` 所调用的 `build_packet/load_package` 在skill指纹检查处全部拒绝。已只读查询正式数据库，没有执行迁移、发布、改稿或模型调用。

## 已完成的检查

- 核对9月修订索引及9月30日和十月跨月补处理索引，冻结35份当前稿的路径和SHA-256。
- 逐份从Markdown解析完整判断，未退回旧JSON。
- 实际调用现有入库包构造器；35份均返回“Skill 或脚本已变化，请新建运行，不复用旧结果”。没有篡改指纹或绕过校验。
- 数据库已有SKILL_AGENT结构支持，无需本次再执行schema迁移。
- 目标运行33份为POINTS_READY，2份为PUBLISHED；历史依赖状态清单保存在预检JSON。若完成版本兼容处理，应按日期发布以满足依赖。

## 需要处理的两类兼容性

1. **运行版本**：当前skill指纹为 `{s['current_skill_sha256']}`，35份来源均为较早版本。skill要求规则或脚本变化后新建运行。当前默认召回参数又已变更，不能只替换来源指纹，也不能把重新召回后未经判断的新对自动填成无关系。若重建并改变实际关系稿，需要重新展示变动稿件。
2. **已发布旧版**：9月9日库内旧版归档21对、0条关系，当前稿6条关系；9月10日库内旧版归档24对、3条关系，当前稿5条关系。两者都不是同一来源包，现有保存器会拒绝覆盖其他已发布结果。未修改已有边、checkpoint或发布状态。

## 当前待入库稿件

| 日期 | 关系 | 无关系 | 未决 | 数据库目标状态 | 本地入库预检 | 当前完整稿 |
| --- | ---: | ---: | ---: | --- | --- | --- |
{chr(10).join(rows)}

## 执行边界

本次用户已经授权把两个月当前关系稿入库，无需再次索取同一写入授权；但现有skill没有旧版发布覆盖能力。若选择替换旧发布，需要明确该处理方式并提供可保留原归档的版本迁移实现。若选择保留旧发布，应将两篇与当前稿差异明确列为保留旧版，不能称35份当前稿全部入库。

未决判断可以归档、不建边，不是本次阻塞原因。7、8月缺少正式要点的范围外日记不在本次补提取范围。本报告只描述实际35份主稿，不把旧稿总览里的清单外关系自动并入当前包。

[预检原始记录](<{R/'预检.json'}>)
'''
(R/'入库预检与阻塞清单.md').write_text(text)
print(dict(total));print(str(R/'入库预检与阻塞清单.md'))
