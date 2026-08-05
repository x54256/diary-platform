-- 034: 领域枚举更新为新五码 + 清空旧数据 + 插入样例数据
-- 用户已确认破坏性修改，不保留历史回顾数据。

BEGIN;
SET CONSTRAINTS ALL DEFERRED;

-- ── 1. 清空全部回顾数据 ─────────────────────────────────────────
UPDATE reviews SET current_version_id = NULL;
DELETE FROM review_source_set_items;
DELETE FROM review_sources;
DELETE FROM reviews;
DELETE FROM review_tasks;
DELETE FROM review_source_sets;

-- ── 2. 更新 review_actions CHECK 约束为新五领域码 ──────────────────
ALTER TABLE review_actions DROP CONSTRAINT IF EXISTS ck_review_actions_domain;
ALTER TABLE review_actions ADD CONSTRAINT ck_review_actions_domain
  CHECK (primary_domain IN (
    'WORK_OUTPUT','PERSONAL_GROWTH','HEALTH_WELLBEING','RELATIONSHIPS','LIFE_AFFAIRS'
  ));

-- ── 3. 插入样例数据 ──────────────────────────────────────────────

-- 3a. 来源集合
INSERT INTO review_source_sets (id, user_id, status, input_snapshot, created_at)
SELECT
  'a0000000-0000-0000-0000-000000000001',
  u.id, 'READY', '{}', '2026-08-03 10:00:00'
FROM users u LIMIT 1;

-- 3b. 周回顾
INSERT INTO reviews (id, user_id, review_type, period_start, period_end, is_unread, created_at, updated_at)
SELECT
  'b0000000-0000-0000-0000-000000000001',
  u.id, 'WEEK', '2026-07-27', '2026-08-02', false, '2026-08-03 10:00:00', '2026-08-03 10:00:00'
FROM users u LIMIT 1;

-- 3c. 回顾版本（含新结构 event_document + 分析 document）
INSERT INTO review_versions (
  id, review_id, user_id, version_no, version_type, base_version_id, source_set_id,
  event_document, analysis_document, summary,
  analysis_stale, superseded_at_creation, missing_periods, created_at
)
SELECT
  'c0000000-0000-0000-0000-000000000001',
  'b0000000-0000-0000-0000-000000000001',
  u.id, 1, 'GENERATED', NULL, 'a0000000-0000-0000-0000-000000000001',
  -- event_document：统一 threads 结构 + 新五领域码
  '{
    "domains": [
      {
        "domain_code": "WORK_OUTPUT",
        "core_focus": [{"focus_key": "focus-1", "label": "需求评审方案推进", "thread_keys": ["thread-1"], "source_ids": []}],
        "event_threads": [
          {
            "thread_key": "thread-1",
            "title": "需求评审方案推进",
            "primary_domain": "WORK_OUTPUT",
            "related_domains": [],
            "span_type": "CROSS_DAY",
            "narrative": "周一和前端对齐了初版方案，周三评审时被指出性能隐患，周四重新压测后确认需要调整缓存策略，截至周末方案仍在修改中。",
            "narrative_node_keys": ["node-1", "node-2", "node-3"],
            "continuity_status": "NEW",
            "current_status": "BLOCKED",
            "previous_thread_key": null,
            "prior_context_source_ids": [],
            "nodes": [
              {"node_key": "node-1", "source_date": "2026-07-28", "change_type": "CURRENT_STATE", "fact": "和前端对齐了初版方案，确定了主要交互流程。", "source_ids": [], "quotes": ["今天和前端同事开了个会，把初版方案的交互流程过了一遍，基本确定了主要页面的布局。"]},
              {"node_key": "node-2", "source_date": "2026-07-30", "change_type": "CURRENT_STATE", "fact": "方案评审时被指出存在性能隐患，需要重新评估缓存策略。", "source_ids": [], "quotes": ["下午评审会的时候，老王指出缓存方案可能有性能瓶颈，让我重新评估一下。"]},
              {"node_key": "node-3", "source_date": "2026-07-31", "change_type": "CURRENT_STATE", "fact": "完成压测，确认需要调整缓存策略，开始修改方案。", "source_ids": [], "quotes": ["重新做了压测，QPS 确实掉得很厉害，确认需要调整缓存策略，开始改方案。"]}
            ],
            "links": []
          },
          {
            "thread_key": "thread-2",
            "title": "项目故障排查",
            "primary_domain": "WORK_OUTPUT",
            "related_domains": [],
            "span_type": "SINGLE_DAY",
            "narrative": "周二晚上排查并修复了线上告警，定位为缓存失效导致的数据不一致。",
            "narrative_node_keys": ["node-4"],
            "continuity_status": "NEW",
            "current_status": "COMPLETED",
            "previous_thread_key": null,
            "prior_context_source_ids": [],
            "nodes": [
              {"node_key": "node-4", "source_date": "2026-07-29", "change_type": "CURRENT_STATE", "fact": "晚上排查并修复了线上告警，定位为缓存失效导致的数据不一致。", "source_ids": [], "quotes": ["晚上收到告警，排查了两个小时，最后发现是缓存失效导致的数据不一致问题。"]}
            ],
            "links": []
          }
        ]
      },
      {
        "domain_code": "PERSONAL_GROWTH",
        "core_focus": [{"focus_key": "focus-2", "label": "英语网课学习", "thread_keys": ["thread-3"], "source_ids": []}],
        "event_threads": [
          {
            "thread_key": "thread-3",
            "title": "英语网课学习",
            "primary_domain": "PERSONAL_GROWTH",
            "related_domains": [],
            "span_type": "CROSS_DAY",
            "narrative": "本周完成了三个单元的学习，周五的口语练习已标记完成。",
            "narrative_node_keys": ["node-5", "node-6"],
            "continuity_status": "NEW",
            "current_status": "IN_PROGRESS",
            "previous_thread_key": null,
            "prior_context_source_ids": [],
            "nodes": [
              {"node_key": "node-5", "source_date": "2026-07-28", "change_type": "CURRENT_STATE", "fact": "完成了英语网课第七单元的学习，主要是阅读理解练习。", "source_ids": [], "quotes": ["今天把英语网课第七单元学完了，主要是阅读理解方面的内容。"]},
              {"node_key": "node-6", "source_date": "2026-08-01", "change_type": "CURRENT_STATE", "fact": "完成了口语练习，已标记完成。", "source_ids": [], "quotes": ["周五的口语练习终于做完了，感觉自己的表达流畅了一些。"]}
            ],
            "links": []
          }
        ]
      },
      {
        "domain_code": "HEALTH_WELLBEING",
        "core_focus": [{"focus_key": "focus-3", "label": "健身运动", "thread_keys": ["thread-4"], "source_ids": []}],
        "event_threads": [
          {
            "thread_key": "thread-4",
            "title": "健身运动",
            "primary_domain": "HEALTH_WELLBEING",
            "related_domains": [],
            "span_type": "CROSS_DAY",
            "narrative": "本周去了三次健身房，周三和周六做了力量训练，周五跑了五公里。",
            "narrative_node_keys": ["node-7", "node-8", "node-9"],
            "continuity_status": "NEW",
            "current_status": "IN_PROGRESS",
            "previous_thread_key": null,
            "prior_context_source_ids": [],
            "nodes": [
              {"node_key": "node-7", "source_date": "2026-07-29", "change_type": "CURRENT_STATE", "fact": "健身房力量训练，上肢为主。", "source_ids": [], "quotes": ["今天去健身房做了力量训练，主要练的上肢。"]},
              {"node_key": "node-8", "source_date": "2026-07-31", "change_type": "CURRENT_STATE", "fact": "户外跑了五公里，配速 6 分半。", "source_ids": [], "quotes": ["傍晚出去跑了五公里，配速大概 6 分半，感觉还不错。"]},
              {"node_key": "node-9", "source_date": "2026-08-01", "change_type": "CURRENT_STATE", "fact": "健身房力量训练，下肢为主。", "source_ids": [], "quotes": ["今天练的下肢，深蹲和硬拉都加了一点重量。"]}
            ],
            "links": []
          }
        ]
      },
      {
        "domain_code": "RELATIONSHIPS",
        "core_focus": [{"focus_key": "focus-4", "label": "周末朋友聚餐", "thread_keys": ["thread-5"], "source_ids": []}],
        "event_threads": [
          {
            "thread_key": "thread-5",
            "title": "周末朋友聚餐",
            "primary_domain": "RELATIONSHIPS",
            "related_domains": [],
            "span_type": "SINGLE_DAY",
            "narrative": "周六晚上和大学同学聚餐，聊了近况和工作。",
            "narrative_node_keys": ["node-10"],
            "continuity_status": "NEW",
            "current_status": "COMPLETED",
            "previous_thread_key": null,
            "prior_context_source_ids": [],
            "nodes": [
              {"node_key": "node-10", "source_date": "2026-08-01", "change_type": "CURRENT_STATE", "fact": "晚上和大学同学聚餐，聊了近况和工作。", "source_ids": [], "quotes": ["晚上和小李他们聚餐，好久不见了，聊了聊近况和工作上的事。"]}
            ],
            "links": []
          }
        ]
      },
      {
        "domain_code": "LIFE_AFFAIRS",
        "core_focus": [{"focus_key": "focus-5", "label": "家电清洗", "thread_keys": ["thread-6"], "source_ids": []}],
        "event_threads": [
          {
            "thread_key": "thread-6",
            "title": "家电清洗",
            "primary_domain": "LIFE_AFFAIRS",
            "related_domains": [],
            "span_type": "SINGLE_DAY",
            "narrative": "周日上午预约了空调清洗服务，下午完成。",
            "narrative_node_keys": ["node-11"],
            "continuity_status": "NEW",
            "current_status": "COMPLETED",
            "previous_thread_key": null,
            "prior_context_source_ids": [],
            "nodes": [
              {"node_key": "node-11", "source_date": "2026-08-02", "change_type": "CURRENT_STATE", "fact": "上午预约了空调清洗服务，下午师傅上门完成。", "source_ids": [], "quotes": ["上午在平台上约了空调清洗，下午师傅过来搞定了，弄完之后凉快多了。"]}
            ],
            "links": []
          }
        ]
      }
    ]
  }',
  -- analysis_document（空结构，后续分析环节生成）
  '{"domains": []}',
  '需求评审方案推进、英语网课学习、健身运动',
  false, false, '[]', '2026-08-03 10:00:00'
FROM users u LIMIT 1;

-- 3d. 回写 reviews.current_version_id
UPDATE reviews
SET current_version_id = 'c0000000-0000-0000-0000-000000000001'
WHERE id = 'b0000000-0000-0000-0000-000000000001';

-- 3e. 已完成的任务记录
INSERT INTO review_tasks (
  id, review_id, user_id, trigger_type, generation_mode, status, current_step,
  freeze_attempts, event_attempts, analysis_attempts,
  source_set_id, source_snapshot_ready, available_at,
  result_version_id, completed_at, created_at, updated_at
)
SELECT
  'd0000000-0000-0000-0000-000000000001',
  'b0000000-0000-0000-0000-000000000001',
  u.id, 'AUTO', 'FULL', 'SUCCEEDED', 'PERSIST_VERSION',
  1, 1, 1,
  'a0000000-0000-0000-0000-000000000001', true, '2026-08-03 09:55:00',
  'c0000000-0000-0000-0000-000000000001', '2026-08-03 10:00:00', '2026-08-03 09:55:00', '2026-08-03 10:00:00'
FROM users u LIMIT 1;

-- 3f. 月回顾样例（展示不同类型）
INSERT INTO reviews (id, user_id, review_type, period_start, period_end, is_unread, created_at, updated_at)
SELECT
  'b0000000-0000-0000-0000-000000000002',
  u.id, 'MONTH', '2026-07-01', '2026-07-31', true, '2026-08-02 10:00:00', '2026-08-02 10:00:00'
FROM users u LIMIT 1;

INSERT INTO review_versions (
  id, review_id, user_id, version_no, version_type, base_version_id, source_set_id,
  event_document, analysis_document, summary,
  analysis_stale, superseded_at_creation, missing_periods, created_at
)
SELECT
  'c0000000-0000-0000-0000-000000000002',
  'b0000000-0000-0000-0000-000000000002',
  u.id, 1, 'GENERATED', NULL, 'a0000000-0000-0000-0000-000000000001',
  '{
    "domains": [
      {
        "domain_code": "WORK_OUTPUT",
        "core_focus": [{"focus_key": "focus-m1", "label": "项目交付", "thread_keys": ["thread-m1"], "source_ids": []}],
        "event_threads": [
          {
            "thread_key": "thread-m1",
            "title": "Q3 项目交付",
            "primary_domain": "WORK_OUTPUT",
            "related_domains": [],
            "span_type": "CROSS_DAY",
            "narrative": "7 月上旬完成了需求评审，中旬进入开发阶段，月底完成了第一轮内测并修复了主要缺陷。",
            "narrative_node_keys": ["node-m1", "node-m2"],
            "continuity_status": "NEW",
            "current_status": "IN_PROGRESS",
            "previous_thread_key": null,
            "prior_context_source_ids": [],
            "nodes": [
              {"node_key": "node-m1", "source_date": "2026-07-10", "change_type": "CURRENT_STATE", "fact": "完成需求评审，确认了核心功能范围。", "source_ids": [], "quotes": ["今天把 Q3 项目的需求评审做完了，核心功能范围基本确定。"]},
              {"node_key": "node-m2", "source_date": "2026-07-28", "change_type": "CURRENT_STATE", "fact": "完成第一轮内测，修复了 12 个主要缺陷。", "source_ids": [], "quotes": ["第一轮内测总算结束了，一共发现了 12 个主要缺陷，这周都修复完了。"]}
            ],
            "links": []
          }
        ]
      },
      {
        "domain_code": "PERSONAL_GROWTH",
        "core_focus": [{"focus_key": "focus-m2", "label": "读书", "thread_keys": ["thread-m2"], "source_ids": []}],
        "event_threads": [
          {
            "thread_key": "thread-m2",
            "title": "《思考快与慢》阅读",
            "primary_domain": "PERSONAL_GROWTH",
            "related_domains": [],
            "span_type": "CROSS_DAY",
            "narrative": "本月读完了前三章，对锚定效应和可得性偏误有了更深入的理解。",
            "narrative_node_keys": ["node-m3"],
            "continuity_status": "NEW",
            "current_status": "IN_PROGRESS",
            "previous_thread_key": null,
            "prior_context_source_ids": [],
            "nodes": [
              {"node_key": "node-m3", "source_date": "2026-07-20", "change_type": "CURRENT_STATE", "fact": "读完第三章，整理了锚定效应的笔记。", "source_ids": [], "quotes": ["今天把《思考快与慢》第三章读完了，锚定效应这个概念挺有意思的，整理了一些笔记。"]}
            ],
            "links": []
          }
        ]
      }
    ]
  }',
  '{"domains": []}',
  'Q3 项目交付推进、阅读学习',
  false, false, '[]', '2026-08-02 10:00:00'
FROM users u LIMIT 1;

UPDATE reviews
SET current_version_id = 'c0000000-0000-0000-0000-000000000002'
WHERE id = 'b0000000-0000-0000-0000-000000000002';

INSERT INTO review_tasks (
  id, review_id, user_id, trigger_type, generation_mode, status, current_step,
  freeze_attempts, event_attempts, analysis_attempts,
  source_set_id, source_snapshot_ready, available_at,
  result_version_id, completed_at, created_at, updated_at
)
SELECT
  'd0000000-0000-0000-0000-000000000002',
  'b0000000-0000-0000-0000-000000000002',
  u.id, 'AUTO', 'FULL', 'SUCCEEDED', 'PERSIST_VERSION',
  1, 1, 1,
  'a0000000-0000-0000-0000-000000000001', true, '2026-08-02 09:55:00',
  'c0000000-0000-0000-0000-000000000002', '2026-08-02 10:00:00', '2026-08-02 09:55:00', '2026-08-02 10:00:00'
FROM users u LIMIT 1;

COMMIT;
