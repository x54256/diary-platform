-- 第一层事件图谱迁移：用户已备份，停止旧应用写入后执行。

CREATE EXTENSION IF NOT EXISTS vector;

DELETE FROM model_step_settings WHERE step_key IN ('knowledge_event_extract','knowledge_event_review','knowledge_matter_assign','knowledge_matter_overview');

DELETE FROM model_settings WHERE setting_key='knowledge';

DROP TABLE IF EXISTS knowledge_event_reviews;

DROP TABLE IF EXISTS knowledge_atomic_events;

DROP TABLE IF EXISTS knowledge_deposits;

DROP TABLE IF EXISTS knowledge_tasks;

DROP TABLE IF EXISTS knowledge_matters;

ALTER TABLE diary_events ADD COLUMN is_in_graph BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN diary_events.is_in_graph IS '当前事件是否具有有效已发布图谱';

CREATE UNIQUE INDEX uq_analysis_runs_task ON analysis_runs(task_id) WHERE task_id IS NOT NULL;

CREATE TABLE graph_tasks (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	user_id UUID NOT NULL,
	environment VARCHAR(32) NOT NULL,
	entry_type VARCHAR(16) NOT NULL,
	organize_task_id UUID,
	status VARCHAR(16) DEFAULT 'QUEUED' NOT NULL,
	date_from DATE NOT NULL,
	date_to DATE NOT NULL,
	current_run_id UUID,
	available_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	lease_until TIMESTAMP WITH TIME ZONE,
	run_token UUID,
	retry_count INTEGER DEFAULT '0' NOT NULL,
	config_snapshot JSONB NOT NULL,
	error_code VARCHAR(64),
	error_message TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT ck_graph_task_entry CHECK (entry_type IN ('ANALYSIS','HISTORY')),
	CONSTRAINT ck_graph_task_status CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','SUPERSEDED')),
	CONSTRAINT ck_graph_task_range CHECK (date_from <= date_to AND retry_count >= 0),
	CONSTRAINT ck_graph_task_compatibility CHECK ((entry_type='ANALYSIS' AND organize_task_id IS NOT NULL) OR (entry_type='HISTORY' AND organize_task_id IS NULL)),
	CONSTRAINT ck_graph_task_config CHECK (jsonb_typeof(config_snapshot)='object'),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT,
	UNIQUE (organize_task_id),
	FOREIGN KEY(organize_task_id) REFERENCES organize_tasks (id) ON DELETE RESTRICT
);

CREATE INDEX ix_graph_tasks_claim ON graph_tasks (environment, status, available_at, created_at, id);
CREATE INDEX ix_graph_tasks_user ON graph_tasks (user_id, created_at, id);
CREATE UNIQUE INDEX uq_graph_tasks_user_active ON graph_tasks (user_id) WHERE status IN ('QUEUED','RUNNING');
COMMENT ON COLUMN graph_tasks.id IS '图谱任务唯一标识';
COMMENT ON COLUMN graph_tasks.user_id IS '所属用户';
COMMENT ON COLUMN graph_tasks.environment IS '任务领取环境';
COMMENT ON COLUMN graph_tasks.entry_type IS '分析或历史建图入口';
COMMENT ON COLUMN graph_tasks.organize_task_id IS '分析兼容任务标识';
COMMENT ON COLUMN graph_tasks.status IS '任务执行状态';
COMMENT ON COLUMN graph_tasks.date_from IS '起始日记日期';
COMMENT ON COLUMN graph_tasks.date_to IS '结束日记日期';
COMMENT ON COLUMN graph_tasks.current_run_id IS '当前日期的运行标识';
COMMENT ON COLUMN graph_tasks.available_at IS '可领取时间';
COMMENT ON COLUMN graph_tasks.lease_until IS '执行租约截止时间';
COMMENT ON COLUMN graph_tasks.run_token IS '当前执行权令牌';
COMMENT ON COLUMN graph_tasks.retry_count IS '用户恢复次数';
COMMENT ON COLUMN graph_tasks.config_snapshot IS '无认证信息的冻结模型和提示配置';
COMMENT ON COLUMN graph_tasks.error_code IS '失败代码';
COMMENT ON COLUMN graph_tasks.error_message IS '脱敏失败说明';
COMMENT ON COLUMN graph_tasks.created_at IS '创建时间';
COMMENT ON COLUMN graph_tasks.updated_at IS '最后状态更新时间';
COMMENT ON COLUMN graph_tasks.started_at IS '首次执行时间';
COMMENT ON COLUMN graph_tasks.completed_at IS '完成时间';

CREATE TABLE graph_runs (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	task_id UUID NOT NULL,
	user_id UUID NOT NULL,
	diary_id UUID NOT NULL,
	diary_date DATE NOT NULL,
	source_organized_id UUID,
	analysis_run_id UUID,
	analysis_mode VARCHAR(16),
	status VARCHAR(16) DEFAULT 'QUEUED' NOT NULL,
	current_step VARCHAR(32),
	source_snapshot JSONB,
	source_sha256 VARCHAR(64),
	checkpoint JSONB DEFAULT '{}'::jsonb NOT NULL,
	error_code VARCHAR(64),
	error_message TEXT,
	skip_reason VARCHAR(32),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE,
	obsolete_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_graph_run_task_diary UNIQUE (task_id, diary_id),
	CONSTRAINT uq_graph_run_user UNIQUE (id, user_id),
	CONSTRAINT uq_graph_run_task UNIQUE (id, task_id),
	CONSTRAINT ck_graph_run_status CHECK (status IN ('QUEUED','RUNNING','FAILED','PUBLISHED','OBSOLETE','SKIPPED')),
	CONSTRAINT ck_graph_run_mode CHECK (analysis_mode IS NULL OR analysis_mode IN ('ordinary','feedback')),
	CONSTRAINT ck_graph_run_digest CHECK (source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_graph_run_source CHECK ((source_snapshot IS NULL) = (source_sha256 IS NULL)),
	CONSTRAINT ck_graph_run_snapshot CHECK (source_snapshot IS NULL OR jsonb_typeof(source_snapshot)='object'),
	CONSTRAINT ck_graph_run_checkpoint CHECK (jsonb_typeof(checkpoint)='object'),
	CONSTRAINT ck_graph_run_published CHECK (status NOT IN ('PUBLISHED','OBSOLETE') OR published_at IS NOT NULL),
	CONSTRAINT ck_graph_run_obsolete CHECK (status != 'OBSOLETE' OR obsolete_at IS NOT NULL),
	CONSTRAINT ck_graph_run_skip CHECK (status != 'SKIPPED' OR skip_reason IN ('ALREADY_PUBLISHED','NOT_ANALYZED')),
	FOREIGN KEY(task_id) REFERENCES graph_tasks (id) ON DELETE RESTRICT,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT,
	FOREIGN KEY(diary_id) REFERENCES diaries (id) ON DELETE RESTRICT,
	FOREIGN KEY(source_organized_id) REFERENCES diary_organized (id) ON DELETE RESTRICT,
	FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs (id) ON DELETE RESTRICT
);

CREATE INDEX ix_graph_runs_history ON graph_runs (user_id, diary_date, id) WHERE status='PUBLISHED';
CREATE INDEX ix_graph_runs_task_date ON graph_runs (task_id, diary_date, id);
CREATE UNIQUE INDEX uq_graph_runs_current ON graph_runs (user_id, diary_id) WHERE status='PUBLISHED';
COMMENT ON COLUMN graph_runs.id IS '单日日记本轮建图标识';
COMMENT ON COLUMN graph_runs.task_id IS '所属执行任务';
COMMENT ON COLUMN graph_runs.user_id IS '所属用户';
COMMENT ON COLUMN graph_runs.diary_id IS '来源日记';
COMMENT ON COLUMN graph_runs.diary_date IS '来源日记日期';
COMMENT ON COLUMN graph_runs.source_organized_id IS '冻结整理记录';
COMMENT ON COLUMN graph_runs.analysis_run_id IS '本次分析或历史已有分析轮次';
COMMENT ON COLUMN graph_runs.analysis_mode IS '普通或反馈分析分支';
COMMENT ON COLUMN graph_runs.status IS '运行有效与执行状态';
COMMENT ON COLUMN graph_runs.current_step IS '当前执行阶段';
COMMENT ON COLUMN graph_runs.source_snapshot IS '完整单日来源快照';
COMMENT ON COLUMN graph_runs.source_sha256 IS '规范来源摘要';
COMMENT ON COLUMN graph_runs.checkpoint IS '候选结果和恢复游标';
COMMENT ON COLUMN graph_runs.error_code IS '失败代码';
COMMENT ON COLUMN graph_runs.error_message IS '脱敏失败说明';
COMMENT ON COLUMN graph_runs.skip_reason IS '历史日期跳过原因';
COMMENT ON COLUMN graph_runs.created_at IS '创建时间';
COMMENT ON COLUMN graph_runs.updated_at IS '最后更新时间';
COMMENT ON COLUMN graph_runs.published_at IS '正式发布时间';
COMMENT ON COLUMN graph_runs.obsolete_at IS '过时时间';

CREATE TABLE graph_model_calls (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	task_id UUID NOT NULL,
	run_id UUID NOT NULL,
	stage VARCHAR(32) NOT NULL,
	unit_key TEXT NOT NULL,
	attempt_no INTEGER NOT NULL,
	status VARCHAR(16) NOT NULL,
	request_snapshot JSONB NOT NULL,
	response_text TEXT,
	parsed_result JSONB,
	validation_errors JSONB DEFAULT '[]'::jsonb NOT NULL,
	input_tokens INTEGER,
	output_tokens INTEGER,
	reasoning_tokens INTEGER,
	error_code VARCHAR(64),
	error_message TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_graph_call_attempt UNIQUE (run_id, stage, unit_key, attempt_no),
	CONSTRAINT fk_graph_call_run FOREIGN KEY(run_id, task_id) REFERENCES graph_runs (id, task_id) ON DELETE RESTRICT,
	CONSTRAINT ck_graph_call_attempt CHECK (attempt_no > 0),
	CONSTRAINT ck_graph_call_status CHECK (status IN ('STARTED','SUCCEEDED','FAILED','UNKNOWN')),
	CONSTRAINT ck_graph_call_json CHECK (jsonb_typeof(request_snapshot)='object' AND jsonb_typeof(validation_errors)='array'),
	CONSTRAINT ck_graph_call_usage CHECK ((input_tokens IS NULL OR input_tokens>=0) AND (output_tokens IS NULL OR output_tokens>=0) AND (reasoning_tokens IS NULL OR reasoning_tokens>=0)),
	FOREIGN KEY(task_id) REFERENCES graph_tasks (id) ON DELETE RESTRICT
);

CREATE INDEX ix_graph_calls_task ON graph_model_calls (task_id, created_at, id);
CREATE INDEX ix_graph_calls_unit ON graph_model_calls (run_id, stage, unit_key);
COMMENT ON COLUMN graph_model_calls.id IS '实际服务调用标识';
COMMENT ON COLUMN graph_model_calls.task_id IS '所属任务';
COMMENT ON COLUMN graph_model_calls.run_id IS '所属日期运行';
COMMENT ON COLUMN graph_model_calls.stage IS '调用阶段及角色';
COMMENT ON COLUMN graph_model_calls.unit_key IS '稳定事件要点或批次键';
COMMENT ON COLUMN graph_model_calls.attempt_no IS '实际请求序号';
COMMENT ON COLUMN graph_model_calls.status IS '实际请求状态';
COMMENT ON COLUMN graph_model_calls.request_snapshot IS '脱敏完整请求及预算';
COMMENT ON COLUMN graph_model_calls.response_text IS '原始响应';
COMMENT ON COLUMN graph_model_calls.parsed_result IS '解析结果';
COMMENT ON COLUMN graph_model_calls.validation_errors IS '结构检查错误';
COMMENT ON COLUMN graph_model_calls.input_tokens IS '输入Token';
COMMENT ON COLUMN graph_model_calls.output_tokens IS '输出Token';
COMMENT ON COLUMN graph_model_calls.reasoning_tokens IS '推理Token';
COMMENT ON COLUMN graph_model_calls.error_code IS '失败代码';
COMMENT ON COLUMN graph_model_calls.error_message IS '脱敏失败说明';
COMMENT ON COLUMN graph_model_calls.created_at IS '请求创建时间';
COMMENT ON COLUMN graph_model_calls.completed_at IS '请求完成时间';

CREATE TABLE graph_run_events (
	run_id UUID NOT NULL,
	event_id UUID NOT NULL,
	user_id UUID NOT NULL,
	source_order INTEGER NOT NULL,
	occurred_on DATE,
	PRIMARY KEY (run_id, event_id),
	CONSTRAINT uq_graph_event_user UNIQUE (run_id, event_id, user_id),
	CONSTRAINT fk_graph_event_run FOREIGN KEY(run_id, user_id) REFERENCES graph_runs (id, user_id) ON DELETE RESTRICT,
	CONSTRAINT ck_graph_event_order CHECK (source_order >= 0),
	FOREIGN KEY(event_id) REFERENCES diary_events (id) ON DELETE RESTRICT
);

COMMENT ON COLUMN graph_run_events.run_id IS '所属图谱运行';
COMMENT ON COLUMN graph_run_events.event_id IS '来源事件身份';
COMMENT ON COLUMN graph_run_events.user_id IS '所属用户';
COMMENT ON COLUMN graph_run_events.source_order IS '来源事件顺序';
COMMENT ON COLUMN graph_run_events.occurred_on IS '已核验实际发生日期，未知为空';

CREATE TABLE graph_event_points (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	run_id UUID NOT NULL,
	event_id UUID NOT NULL,
	user_id UUID NOT NULL,
	no INTEGER NOT NULL,
	summary TEXT NOT NULL,
	detail TEXT NOT NULL,
	embedding VECTOR(1024) NOT NULL,
	embedding_model TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_graph_point_no UNIQUE (run_id, event_id, no),
	CONSTRAINT uq_graph_point_identity UNIQUE (id, run_id, event_id, user_id),
	CONSTRAINT fk_graph_point_event FOREIGN KEY(run_id, event_id, user_id) REFERENCES graph_run_events (run_id, event_id, user_id) ON DELETE RESTRICT,
	CONSTRAINT ck_graph_point_content CHECK (no>0 AND btrim(summary)<>'' AND btrim(detail)<>'' AND btrim(embedding_model)<>'')
);

COMMENT ON COLUMN graph_event_points.id IS '稳定关系证据要点标识';
COMMENT ON COLUMN graph_event_points.run_id IS '所属运行';
COMMENT ON COLUMN graph_event_points.event_id IS '来源事件';
COMMENT ON COLUMN graph_event_points.user_id IS '所属用户';
COMMENT ON COLUMN graph_event_points.no IS '本轮事件内连续序号';
COMMENT ON COLUMN graph_event_points.summary IS '要点标题';
COMMENT ON COLUMN graph_event_points.detail IS '忠实详细内容';
COMMENT ON COLUMN graph_event_points.embedding IS '完整详细内容的1024维向量';
COMMENT ON COLUMN graph_event_points.embedding_model IS '冻结向量模型版本标识';
COMMENT ON COLUMN graph_event_points.created_at IS '正式保存时间';

CREATE TABLE graph_event_relations (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	run_id UUID NOT NULL,
	user_id UUID NOT NULL,
	source_run_id UUID NOT NULL,
	source_event_id UUID NOT NULL,
	target_run_id UUID NOT NULL,
	target_event_id UUID NOT NULL,
	pair_event_low UUID GENERATED ALWAYS AS (LEAST(source_event_id,target_event_id)) STORED,
	pair_event_high UUID GENERATED ALWAYS AS (GREATEST(source_event_id,target_event_id)) STORED,
	relation_type VARCHAR(16) NOT NULL,
	certainty VARCHAR(16) NOT NULL,
	description TEXT NOT NULL,
	final_source VARCHAR(16) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_graph_relation_pair UNIQUE (run_id, pair_event_low, pair_event_high),
	CONSTRAINT uq_graph_relation_endpoints UNIQUE (id, user_id, source_run_id, source_event_id, target_run_id, target_event_id),
	CONSTRAINT fk_graph_relation_run FOREIGN KEY(run_id, user_id) REFERENCES graph_runs (id, user_id) ON DELETE RESTRICT,
	CONSTRAINT fk_graph_relation_source FOREIGN KEY(source_run_id, source_event_id, user_id) REFERENCES graph_run_events (run_id, event_id, user_id) ON DELETE RESTRICT,
	CONSTRAINT fk_graph_relation_target FOREIGN KEY(target_run_id, target_event_id, user_id) REFERENCES graph_run_events (run_id, event_id, user_id) ON DELETE RESTRICT,
	CONSTRAINT ck_graph_relation_endpoints CHECK (source_event_id<>target_event_id AND (source_run_id=run_id OR target_run_id=run_id)),
	CONSTRAINT ck_graph_relation_type CHECK (relation_type IN ('后续事件','引发事件','提及事件') AND certainty IN ('EXPLICIT','SPECULATIVE')),
	CONSTRAINT ck_graph_relation_description CHECK (btrim(description)<>'' AND final_source IN ('AGREEMENT','ADJUDICATED'))
);

CREATE INDEX ix_graph_relation_source ON graph_event_relations (user_id, source_event_id);
CREATE INDEX ix_graph_relation_target ON graph_event_relations (user_id, target_event_id);
COMMENT ON COLUMN graph_event_relations.id IS '正式事件关系标识';
COMMENT ON COLUMN graph_event_relations.run_id IS '关系生成运行';
COMMENT ON COLUMN graph_event_relations.user_id IS '所属用户';
COMMENT ON COLUMN graph_event_relations.source_run_id IS '起点运行';
COMMENT ON COLUMN graph_event_relations.source_event_id IS '起点事件';
COMMENT ON COLUMN graph_event_relations.target_run_id IS '终点运行';
COMMENT ON COLUMN graph_event_relations.target_event_id IS '终点事件';
COMMENT ON COLUMN graph_event_relations.pair_event_low IS '无序事件对较小ID';
COMMENT ON COLUMN graph_event_relations.pair_event_high IS '无序事件对较大ID';
COMMENT ON COLUMN graph_event_relations.relation_type IS '事件关系类型';
COMMENT ON COLUMN graph_event_relations.certainty IS '原文关系确定程度';
COMMENT ON COLUMN graph_event_relations.description IS '忠实关系描述';
COMMENT ON COLUMN graph_event_relations.final_source IS '双判一致或分歧裁决';
COMMENT ON COLUMN graph_event_relations.created_at IS '正式保存时间';

CREATE TABLE graph_relation_evidence (
	relation_id UUID NOT NULL,
	side VARCHAR(8) NOT NULL,
	point_id UUID NOT NULL,
	user_id UUID NOT NULL,
	source_run_id UUID NOT NULL,
	source_event_id UUID NOT NULL,
	target_run_id UUID NOT NULL,
	target_event_id UUID NOT NULL,
	point_run_id UUID NOT NULL,
	point_event_id UUID NOT NULL,
	PRIMARY KEY (relation_id, side, point_id),
	CONSTRAINT fk_graph_evidence_relation FOREIGN KEY(relation_id, user_id, source_run_id, source_event_id, target_run_id, target_event_id) REFERENCES graph_event_relations (id, user_id, source_run_id, source_event_id, target_run_id, target_event_id) ON DELETE RESTRICT,
	CONSTRAINT fk_graph_evidence_point FOREIGN KEY(point_id, point_run_id, point_event_id, user_id) REFERENCES graph_event_points (id, run_id, event_id, user_id) ON DELETE RESTRICT,
	CONSTRAINT ck_graph_evidence_side CHECK ((side='SOURCE' AND point_run_id=source_run_id AND point_event_id=source_event_id) OR (side='TARGET' AND point_run_id=target_run_id AND point_event_id=target_event_id))
);

COMMENT ON COLUMN graph_relation_evidence.relation_id IS '所属关系';
COMMENT ON COLUMN graph_relation_evidence.side IS '起点或终点证据';
COMMENT ON COLUMN graph_relation_evidence.point_id IS '被引用要点';
COMMENT ON COLUMN graph_relation_evidence.user_id IS '所属用户';
COMMENT ON COLUMN graph_relation_evidence.source_run_id IS '关系起点运行';
COMMENT ON COLUMN graph_relation_evidence.source_event_id IS '关系起点事件';
COMMENT ON COLUMN graph_relation_evidence.target_run_id IS '关系终点运行';
COMMENT ON COLUMN graph_relation_evidence.target_event_id IS '关系终点事件';
COMMENT ON COLUMN graph_relation_evidence.point_run_id IS '要点所属运行';
COMMENT ON COLUMN graph_relation_evidence.point_event_id IS '要点来源事件';

ALTER TABLE graph_tasks ADD CONSTRAINT fk_graph_task_current_run FOREIGN KEY(current_run_id, id) REFERENCES graph_runs (id, task_id) ON DELETE RESTRICT;
