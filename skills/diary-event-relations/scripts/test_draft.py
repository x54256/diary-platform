"""稿件是入库内容来源：覆盖人工修改、严格解析和旧包查询。"""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

import draft as d
import storage as s
import workflow as w
import test_workflow
import test_storage


class DraftTest(unittest.TestCase):
    def setUp(self):
        self.fixture=test_storage.StorageTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.folder=self.fixture.folder;self.packet=self.fixture.packet
        self.snapshot=self.packet['snapshot'];self.path=self.folder/'关系结果.md'
        self.content=self.path.read_text()

    def test_all_statuses_roundtrip_with_unicode_quotes_and_fold(self):
        self.assertEqual(self.packet['results'],s.canonical_rows(d.parse_text(self.content,self.snapshot)))
        self.assertIn('<details>',self.content)
        self.assertNotIn('全部事件对处理记录',self.content)
        self.assertNotIn('只读本地结果',self.content)
        # 引文中的 Markdown、竖线和空行均是原文，不当作结构。
        snapshot=deepcopy(self.snapshot);rows=deepcopy(self.packet['results'])
        related=next(r for r in rows if r['relation'])
        rel=related['relation'];quote='包含 | 管道和 Unicode 🐈。\n\n## 原文标题\n> 原文引用'
        e=snapshot['events'][rel['source_event']];e['points'][0]['detail']=quote
        rel['source_evidence'][0]['quote']=quote
        text=d.render_text(snapshot,rows)
        self.assertEqual(s.canonical_rows(rows),s.canonical_rows(d.parse_text(text,snapshot)))
        self.assertEqual(s.canonical_rows(rows),s.canonical_rows(d.parse_text(text.replace('\n>\n','\n> \n'),snapshot)))

    def test_markdown_edits_override_stale_json_and_packet_freezes_text(self):
        old_json=(self.folder/'results.json').read_bytes()
        self.path.write_text(self.content.replace('具体事项出现后续进展。','这项安排已有新的进展。'))
        packet=s.build_packet(self.folder,'isolated')
        self.assertEqual(old_json,(self.folder/'results.json').read_bytes())
        self.assertEqual('这项安排已有新的进展。',next(r['relation']['description']for r in packet['results']if r['relation']))
        self.assertNotEqual(self.packet['results_sha256'],packet['results_sha256'])
        self.assertEqual(self.path.read_text(),packet['draft']['content'])
        s.validate_packet(packet)
        # render 不回写旧缓存，也不覆盖人工格式。
        before=self.path.read_bytes();w.render(self.folder);self.assertEqual(before,self.path.read_bytes())

    def test_unknown_structure_missing_duplicate_pair_and_fake_quote_rejected(self):
        variants=[self.content.replace('类型：后续事件','类型：同主题'),
                  self.content.replace('确定性：明确','确定性：肯定'),
                  self.content.replace('具体经历。','并未出现在要点里的引文。'),
                  self.content.replace('来源：2026-09-09｜同名事件','来源：2026-09-09｜误改标题'),
                  self.content.replace('### 来源证据','### 未知栏目'),
                  self.content+'额外说明，不能被默默忽略。\n',
                  self.content.replace('</details>',''),
                  self.content.replace('（1 对）','（2 对）')]
        for content in variants:
            with self.subTest(content=content[-80:]),self.assertRaises(w.WorkflowError):d.parse_text(content,self.snapshot)
        lines=self.content.splitlines();header=next(i for i,v in enumerate(lines)if v.startswith('## 未决 '))
        end=next(i for i in range(header+1,len(lines))if lines[i]=='<details>')
        partial='\n'.join(lines[:header]+lines[end:])+'\n'
        with self.assertRaises(w.WorkflowError):d.parse_text(partial,self.snapshot)
        self.path.write_text(partial)
        self.assertFalse(w.progress(self.snapshot,w.saved_results(self.folder,self.snapshot),w.read_json(self.folder/'run.json'))['complete'])
        with self.assertRaises(w.WorkflowError):s.build_packet(self.folder,'isolated')
        # 未决标识被替换为另一个已存在事件对，不得接受重复。
        pids=[r['pair_id']for r in self.packet['results']]
        with self.assertRaises(w.WorkflowError):d.parse_text(self.content.replace(pids[1],pids[0]),self.snapshot)

    def test_convert_cli_without_database_and_no_overwrite(self):
        out=self.folder/'转换结果.json'
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0,w.main(['convert',str(self.folder),'--markdown',str(self.path),'--output',str(out)]))
        converted=w.read_json(out)
        self.assertEqual(self.packet['results'],s.canonical_rows(converted['results']))
        before=out.read_bytes()
        from contextlib import redirect_stderr
        with redirect_stderr(io.StringIO()):
            self.assertEqual(1,w.main(['convert',str(self.folder),'--markdown',str(self.path),'--output',str(out)]))
        self.assertEqual(before,out.read_bytes())

    def test_record_markdown_populates_batch_cache_and_renders_primary(self):
        target=w.write_package(self.snapshot,self.fixture.root/'import')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0,w.main(['record',str(target),'--markdown',str(self.path)]))
        self.assertTrue((target/'results.json').exists())
        self.assertFalse((target/'关系结果.md').exists())
        w.render(target)
        self.assertEqual(self.packet['results'],s.canonical_rows(w.saved_results(target,self.snapshot)))

    def test_packet_cannot_diverge_from_embedded_draft(self):
        p=deepcopy(self.packet);p['results'][0]['reason']='只改缓存，不改稿件。'
        p['resolved_results']=s.resolve(p['snapshot'],p['results']);p['results_sha256']=s.result_digest(p['snapshot'],p['resolved_results'])
        p['storage_sha256']=w.digest({k:v for k,v in p.items()if k!='storage_sha256'})
        with self.assertRaises(w.WorkflowError):s.validate_packet(p)

    def test_zero_candidates_and_optional_reason(self):
        fixture=test_workflow.WorkflowTest();fixture.setUp();self.addCleanup(fixture.doCleanups)
        snapshot=fixture.prepare([fixture.a]);text=d.render_text(snapshot,[])
        self.assertEqual([],d.parse_text(text,snapshot))
        rows=deepcopy(self.packet['results'])
        for row in rows:
            if row['relation']:row['reason']=row['relation']['description']
        text=d.render_text(self.snapshot,rows)
        self.assertEqual(s.canonical_rows(rows),s.canonical_rows(d.parse_text(text,self.snapshot)))

    def test_legacy_packet_status_validation_remains_available(self):
        old=deepcopy(self.packet);old['schema_version']=1;old.pop('draft')
        old['results_sha256']=w.digest({'schema_version':1,'source_package_sha256':old['source_package_sha256'],'results':old['resolved_results']})
        old['storage_sha256']=w.digest({k:v for k,v in old.items()if k!='storage_sha256'})
        s.validate_packet(old,current_skill=False)
        with self.assertRaises(w.WorkflowError):s.validate_packet(old)


if __name__=='__main__':unittest.main()
