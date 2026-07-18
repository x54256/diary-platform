-- 将当前 admin 账号改为普通数据账号，并创建新的 admin 账号。
--
-- 执行前：
-- 1. 将下方 4 个参数替换为实际值。
-- 2. 密码字段必须填入应用 utils.crypto.encrypt_password() 生成的 Fernet 密文，
--    不能填明文，也不能使用 PostgreSQL 的 pgcrypto 加密结果。
-- 3. 执行后立即轮换部署配置中的 SECRET_KEY 并重启后端，使旧 JWT 全部失效。
--    当前 JWT 只包含 username；若不轮换，旧 admin 的令牌会认证为新 admin。
--
-- 本脚本不修改 users.id。因此旧 admin 名下的日记、标签、整理/分析任务、
-- 分析反馈、对话和语音转写数据都继续归属于改名后的账号。

BEGIN;

CREATE TEMP TABLE admin_replacement_result (
    archived_user_id UUID NOT NULL,
    new_admin_user_id UUID NOT NULL
) ON COMMIT PRESERVE ROWS;

DO $$
DECLARE
    source_username TEXT := 'admin';
    archived_username TEXT := 'diary_owner';
    archived_password_encrypted TEXT := '__替换为旧账号的新密码对应的_Fernet_密文__';
    new_admin_password_encrypted TEXT := '__替换为新_admin_密码对应的_Fernet_密文__';
    source_user users%ROWTYPE;
    new_admin_user_id UUID;
BEGIN
    IF source_username <> 'admin' THEN
        RAISE EXCEPTION '源账号必须是 admin，当前值为 %', source_username;
    END IF;

    IF archived_username IN ('', 'admin') THEN
        RAISE EXCEPTION '旧账号的新用户名不能为空且不能为 admin';
    END IF;

    IF archived_password_encrypted LIKE '__%' OR new_admin_password_encrypted LIKE '__%' THEN
        RAISE EXCEPTION '请先替换两个密码密文占位符';
    END IF;

    SELECT *
      INTO source_user
      FROM users
     WHERE username = source_username
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION '未找到源账号：admin';
    END IF;

    IF EXISTS (SELECT 1 FROM users WHERE username = archived_username) THEN
        RAISE EXCEPTION '目标旧账号用户名已存在：%', archived_username;
    END IF;

    -- users.id 保持不变，故该账号名下的所有关联数据保持原归属。
    UPDATE users
       SET username = archived_username,
           password_encrypted = archived_password_encrypted
     WHERE id = source_user.id;

    INSERT INTO users (id, username, password_encrypted, created_at)
    VALUES (gen_random_uuid(), 'admin', new_admin_password_encrypted, NOW());

    SELECT id
      INTO new_admin_user_id
      FROM users
     WHERE username = 'admin';

    INSERT INTO admin_replacement_result (archived_user_id, new_admin_user_id)
    VALUES (source_user.id, new_admin_user_id);
END
$$;

COMMIT;

-- 执行后核验：应各返回 1 条记录；旧账号的日记数量应保持不变。
SELECT u.id, u.username, u.created_at
  FROM users u
  JOIN admin_replacement_result r
    ON u.id IN (r.archived_user_id, r.new_admin_user_id)
 ORDER BY u.username;

SELECT u.username, COUNT(d.id) AS diary_count
  FROM users u
  JOIN admin_replacement_result r
    ON u.id IN (r.archived_user_id, r.new_admin_user_id)
  LEFT JOIN diaries d ON d.user_id = u.id
 GROUP BY u.username
 ORDER BY u.username;
