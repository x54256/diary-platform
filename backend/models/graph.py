"""事件图谱运行、执行审计和具有稳定证据身份的正式结果。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Computed, Date, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector

from database import Base
from services.task_environment import TASK_ENVIRONMENT


def utcnow():
    return datetime.now(timezone.utc)


def identifier(comment):
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                  server_default=text("gen_random_uuid()"), comment=comment)


def timestamp(comment):
    return Column(DateTime(timezone=True), nullable=False, default=utcnow,
                  server_default=text("CURRENT_TIMESTAMP"), comment=comment)


class GraphTask(Base):
    __tablename__ = "graph_tasks"
    __table_args__ = (
        CheckConstraint("entry_type IN ('ANALYSIS','HISTORY')", name="ck_graph_task_entry"),
        CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','SUPERSEDED')", name="ck_graph_task_status"),
        CheckConstraint("date_from <= date_to AND retry_count >= 0", name="ck_graph_task_range"),
        CheckConstraint("(entry_type='ANALYSIS' AND organize_task_id IS NOT NULL) OR (entry_type='HISTORY' AND organize_task_id IS NULL)", name="ck_graph_task_compatibility"),
        CheckConstraint("jsonb_typeof(config_snapshot)='object'", name="ck_graph_task_config"),
        ForeignKeyConstraint(["current_run_id", "id"], ["graph_runs.id", "graph_runs.task_id"],
                             name="fk_graph_task_current_run", use_alter=True, ondelete="RESTRICT"),
        Index("uq_graph_tasks_user_active", "user_id", unique=True,
              postgresql_where=text("status IN ('QUEUED','RUNNING')")),
        Index("ix_graph_tasks_claim", "environment", "status", "available_at", "created_at", "id"),
        Index("ix_graph_tasks_user", "user_id", "created_at", "id"),
    )
    id = identifier("图谱任务唯一标识")
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, comment="所属用户")
    environment = Column(String(32), nullable=False, default=TASK_ENVIRONMENT, comment="任务领取环境")
    entry_type = Column(String(16), nullable=False, comment="分析或历史建图入口")
    organize_task_id = Column(UUID(as_uuid=True), ForeignKey("organize_tasks.id", ondelete="RESTRICT"), unique=True, comment="分析兼容任务标识")
    status = Column(String(16), nullable=False, default="QUEUED", server_default="QUEUED", comment="任务执行状态")
    date_from = Column(Date, nullable=False, comment="起始日记日期")
    date_to = Column(Date, nullable=False, comment="结束日记日期")
    current_run_id = Column(UUID(as_uuid=True), comment="当前日期的运行标识")
    available_at = timestamp("可领取时间")
    lease_until = Column(DateTime(timezone=True), comment="执行租约截止时间")
    run_token = Column(UUID(as_uuid=True), comment="当前执行权令牌")
    retry_count = Column(Integer, nullable=False, default=0, server_default="0", comment="用户恢复次数")
    config_snapshot = Column(JSONB, nullable=False, comment="无认证信息的冻结模型和提示配置")
    error_code = Column(String(64), comment="失败代码")
    error_message = Column(Text, comment="脱敏失败说明")
    created_at = timestamp("创建时间")
    updated_at = timestamp("最后状态更新时间")
    started_at = Column(DateTime(timezone=True), comment="首次执行时间")
    completed_at = Column(DateTime(timezone=True), comment="完成时间")


class GraphRun(Base):
    __tablename__ = "graph_runs"
    __table_args__ = (
        UniqueConstraint("task_id", "diary_id", name="uq_graph_run_task_diary"),
        UniqueConstraint("id", "user_id", name="uq_graph_run_user"),
        UniqueConstraint("id", "task_id", name="uq_graph_run_task"),
        CheckConstraint("status IN ('QUEUED','RUNNING','FAILED','POINTS_READY','PUBLISHED','OBSOLETE','SKIPPED')", name="ck_graph_run_status"),
        CheckConstraint("analysis_mode IS NULL OR analysis_mode IN ('ordinary','feedback')", name="ck_graph_run_mode"),
        CheckConstraint("source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_graph_run_digest"),
        CheckConstraint("(source_snapshot IS NULL) = (source_sha256 IS NULL)", name="ck_graph_run_source"),
        CheckConstraint("source_snapshot IS NULL OR jsonb_typeof(source_snapshot)='object'", name="ck_graph_run_snapshot"),
        CheckConstraint("jsonb_typeof(checkpoint)='object'", name="ck_graph_run_checkpoint"),
        CheckConstraint("status NOT IN ('PUBLISHED','OBSOLETE') OR published_at IS NOT NULL", name="ck_graph_run_published"),
        CheckConstraint("status != 'OBSOLETE' OR obsolete_at IS NOT NULL", name="ck_graph_run_obsolete"),
        CheckConstraint("status != 'SKIPPED' OR skip_reason IN ('ALREADY_PUBLISHED','NOT_ANALYZED')", name="ck_graph_run_skip"),
        Index("uq_graph_runs_current", "user_id", "diary_id", unique=True,
              postgresql_where=text("status='PUBLISHED'")),
        Index("ix_graph_runs_task_date", "task_id", "diary_date", "id"),
        Index("ix_graph_runs_history", "user_id", "diary_date", "id",
              postgresql_where=text("status='PUBLISHED'")),
    )
    id = identifier("单日日记本轮建图标识")
    task_id = Column(UUID(as_uuid=True), ForeignKey("graph_tasks.id", ondelete="RESTRICT"), nullable=False, comment="所属执行任务")
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, comment="所属用户")
    diary_id = Column(UUID(as_uuid=True), ForeignKey("diaries.id", ondelete="RESTRICT"), nullable=False, comment="来源日记")
    diary_date = Column(Date, nullable=False, comment="来源日记日期")
    source_organized_id = Column(UUID(as_uuid=True), ForeignKey("diary_organized.id", ondelete="RESTRICT"), comment="冻结整理记录")
    analysis_run_id = Column(UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="RESTRICT"), comment="本次分析或历史已有分析轮次")
    analysis_mode = Column(String(16), comment="普通或反馈分析分支")
    status = Column(String(16), nullable=False, default="QUEUED", server_default="QUEUED", comment="运行有效与执行状态")
    current_step = Column(String(32), comment="当前执行阶段")
    source_snapshot = Column(JSONB, comment="完整单日来源快照")
    source_sha256 = Column(String(64), comment="规范来源摘要")
    checkpoint = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"), comment="候选结果和恢复游标")
    error_code = Column(String(64), comment="失败代码")
    error_message = Column(Text, comment="脱敏失败说明")
    skip_reason = Column(String(32), comment="历史日期跳过原因")
    created_at = timestamp("创建时间")
    updated_at = timestamp("最后更新时间")
    published_at = Column(DateTime(timezone=True), comment="正式发布时间")
    obsolete_at = Column(DateTime(timezone=True), comment="过时时间")


class GraphModelCall(Base):
    __tablename__ = "graph_model_calls"
    __table_args__ = (
        UniqueConstraint("run_id", "stage", "unit_key", "attempt_no", name="uq_graph_call_attempt"),
        ForeignKeyConstraint(["run_id", "task_id"], ["graph_runs.id", "graph_runs.task_id"], name="fk_graph_call_run", ondelete="RESTRICT"),
        CheckConstraint("attempt_no > 0", name="ck_graph_call_attempt"),
        CheckConstraint("status IN ('STARTED','SUCCEEDED','FAILED','UNKNOWN')", name="ck_graph_call_status"),
        CheckConstraint("jsonb_typeof(request_snapshot)='object' AND jsonb_typeof(validation_errors)='array'", name="ck_graph_call_json"),
        CheckConstraint("(input_tokens IS NULL OR input_tokens>=0) AND (output_tokens IS NULL OR output_tokens>=0) AND (reasoning_tokens IS NULL OR reasoning_tokens>=0)", name="ck_graph_call_usage"),
        Index("ix_graph_calls_task", "task_id", "created_at", "id"),
        Index("ix_graph_calls_unit", "run_id", "stage", "unit_key"),
    )
    id = identifier("实际服务调用标识")
    task_id = Column(UUID(as_uuid=True), ForeignKey("graph_tasks.id", ondelete="RESTRICT"), nullable=False, comment="所属任务")
    run_id = Column(UUID(as_uuid=True), nullable=False, comment="所属日期运行")
    stage = Column(String(32), nullable=False, comment="调用阶段及角色")
    unit_key = Column(Text, nullable=False, comment="稳定事件要点或批次键")
    attempt_no = Column(Integer, nullable=False, comment="实际请求序号")
    status = Column(String(16), nullable=False, comment="实际请求状态")
    request_snapshot = Column(JSONB, nullable=False, comment="脱敏完整请求及预算")
    response_text = Column(Text, comment="原始响应")
    parsed_result = Column(JSONB, comment="解析结果")
    validation_errors = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"), comment="结构检查错误")
    input_tokens = Column(Integer, comment="输入Token")
    output_tokens = Column(Integer, comment="输出Token")
    reasoning_tokens = Column(Integer, comment="推理Token")
    error_code = Column(String(64), comment="失败代码")
    error_message = Column(Text, comment="脱敏失败说明")
    created_at = timestamp("请求创建时间")
    completed_at = Column(DateTime(timezone=True), comment="请求完成时间")


class GraphRunEvent(Base):
    __tablename__ = "graph_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "event_id", "user_id", name="uq_graph_event_user"),
        ForeignKeyConstraint(["run_id", "user_id"], ["graph_runs.id", "graph_runs.user_id"], name="fk_graph_event_run", ondelete="RESTRICT"),
        CheckConstraint("source_order >= 0", name="ck_graph_event_order"),
    )
    run_id = Column(UUID(as_uuid=True), primary_key=True, comment="所属图谱运行")
    event_id = Column(UUID(as_uuid=True), ForeignKey("diary_events.id", ondelete="RESTRICT"), primary_key=True, comment="来源事件身份")
    user_id = Column(UUID(as_uuid=True), nullable=False, comment="所属用户")
    source_order = Column(Integer, nullable=False, comment="来源事件顺序")
    occurred_on = Column(Date, comment="已核验实际发生日期，未知为空")


class GraphEventPoint(Base):
    __tablename__ = "graph_event_points"
    __table_args__ = (
        UniqueConstraint("run_id", "event_id", "no", name="uq_graph_point_no"),
        UniqueConstraint("id", "run_id", "event_id", "user_id", name="uq_graph_point_identity"),
        ForeignKeyConstraint(["run_id", "event_id", "user_id"], ["graph_run_events.run_id", "graph_run_events.event_id", "graph_run_events.user_id"], name="fk_graph_point_event", ondelete="RESTRICT"),
        CheckConstraint("no>0 AND btrim(summary)<>'' AND btrim(detail)<>'' AND btrim(embedding_model)<>''", name="ck_graph_point_content"),
    )
    id = identifier("稳定关系证据要点标识")
    run_id = Column(UUID(as_uuid=True), nullable=False, comment="所属运行")
    event_id = Column(UUID(as_uuid=True), nullable=False, comment="来源事件")
    user_id = Column(UUID(as_uuid=True), nullable=False, comment="所属用户")
    no = Column(Integer, nullable=False, comment="本轮事件内连续序号")
    summary = Column(Text, nullable=False, comment="要点标题")
    detail = Column(Text, nullable=False, comment="忠实详细内容")
    embedding = Column(Vector(1024), nullable=False, comment="完整详细内容的1024维向量")
    embedding_model = Column(Text, nullable=False, comment="冻结向量模型版本标识")
    created_at = timestamp("正式保存时间")


class GraphEventRelation(Base):
    __tablename__ = "graph_event_relations"
    __table_args__ = (
        UniqueConstraint("run_id", "pair_event_low", "pair_event_high", name="uq_graph_relation_pair"),
        UniqueConstraint("id", "user_id", "source_run_id", "source_event_id", "target_run_id", "target_event_id", name="uq_graph_relation_endpoints"),
        ForeignKeyConstraint(["run_id", "user_id"], ["graph_runs.id", "graph_runs.user_id"], name="fk_graph_relation_run", ondelete="RESTRICT"),
        ForeignKeyConstraint(["source_run_id", "source_event_id", "user_id"], ["graph_run_events.run_id", "graph_run_events.event_id", "graph_run_events.user_id"], name="fk_graph_relation_source", ondelete="RESTRICT"),
        ForeignKeyConstraint(["target_run_id", "target_event_id", "user_id"], ["graph_run_events.run_id", "graph_run_events.event_id", "graph_run_events.user_id"], name="fk_graph_relation_target", ondelete="RESTRICT"),
        CheckConstraint("source_event_id<>target_event_id AND (source_run_id=run_id OR target_run_id=run_id)", name="ck_graph_relation_endpoints"),
        CheckConstraint("relation_type IN ('后续事件','引发事件','提及事件') AND certainty IN ('EXPLICIT','SPECULATIVE')", name="ck_graph_relation_type"),
        CheckConstraint("btrim(description)<>'' AND final_source IN ('AGREEMENT','ADJUDICATED','SKILL_AGENT')", name="ck_graph_relation_description"),
        Index("ix_graph_relation_source", "user_id", "source_event_id"),
        Index("ix_graph_relation_target", "user_id", "target_event_id"),
    )
    id = identifier("正式事件关系标识")
    run_id = Column(UUID(as_uuid=True), nullable=False, comment="关系生成运行")
    user_id = Column(UUID(as_uuid=True), nullable=False, comment="所属用户")
    source_run_id = Column(UUID(as_uuid=True), nullable=False, comment="起点运行")
    source_event_id = Column(UUID(as_uuid=True), nullable=False, comment="起点事件")
    target_run_id = Column(UUID(as_uuid=True), nullable=False, comment="终点运行")
    target_event_id = Column(UUID(as_uuid=True), nullable=False, comment="终点事件")
    pair_event_low = Column(UUID(as_uuid=True), Computed("LEAST(source_event_id,target_event_id)", persisted=True), comment="无序事件对较小ID")
    pair_event_high = Column(UUID(as_uuid=True), Computed("GREATEST(source_event_id,target_event_id)", persisted=True), comment="无序事件对较大ID")
    relation_type = Column(String(16), nullable=False, comment="事件关系类型")
    certainty = Column(String(16), nullable=False, comment="原文关系确定程度")
    description = Column(Text, nullable=False, comment="忠实关系描述")
    final_source = Column(String(16), nullable=False, comment="双判一致、分歧裁决或Skill来源核对")
    created_at = timestamp("正式保存时间")


class GraphRelationEvidence(Base):
    __tablename__ = "graph_relation_evidence"
    __table_args__ = (
        ForeignKeyConstraint(["relation_id", "user_id", "source_run_id", "source_event_id", "target_run_id", "target_event_id"], ["graph_event_relations.id", "graph_event_relations.user_id", "graph_event_relations.source_run_id", "graph_event_relations.source_event_id", "graph_event_relations.target_run_id", "graph_event_relations.target_event_id"], name="fk_graph_evidence_relation", ondelete="RESTRICT"),
        ForeignKeyConstraint(["point_id", "point_run_id", "point_event_id", "user_id"], ["graph_event_points.id", "graph_event_points.run_id", "graph_event_points.event_id", "graph_event_points.user_id"], name="fk_graph_evidence_point", ondelete="RESTRICT"),
        CheckConstraint("(side='SOURCE' AND point_run_id=source_run_id AND point_event_id=source_event_id) OR (side='TARGET' AND point_run_id=target_run_id AND point_event_id=target_event_id)", name="ck_graph_evidence_side"),
    )
    relation_id = Column(UUID(as_uuid=True), primary_key=True, comment="所属关系")
    side = Column(String(8), primary_key=True, comment="起点或终点证据")
    point_id = Column(UUID(as_uuid=True), primary_key=True, comment="被引用要点")
    user_id = Column(UUID(as_uuid=True), nullable=False, comment="所属用户")
    source_run_id = Column(UUID(as_uuid=True), nullable=False, comment="关系起点运行")
    source_event_id = Column(UUID(as_uuid=True), nullable=False, comment="关系起点事件")
    target_run_id = Column(UUID(as_uuid=True), nullable=False, comment="关系终点运行")
    target_event_id = Column(UUID(as_uuid=True), nullable=False, comment="关系终点事件")
    point_run_id = Column(UUID(as_uuid=True), nullable=False, comment="要点所属运行")
    point_event_id = Column(UUID(as_uuid=True), nullable=False, comment="要点来源事件")
