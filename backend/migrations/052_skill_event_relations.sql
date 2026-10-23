-- 为 Skill 来源增加明确代码；不修改已有关系或要点。
ALTER TABLE graph_event_relations DROP CONSTRAINT ck_graph_relation_description;
ALTER TABLE graph_event_relations ADD CONSTRAINT ck_graph_relation_description
CHECK (btrim(description)<>'' AND final_source IN ('AGREEMENT','ADJUDICATED','SKILL_AGENT'));
COMMENT ON COLUMN graph_event_relations.final_source IS '双判一致、分歧裁决或Skill来源核对';
