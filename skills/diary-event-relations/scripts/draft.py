"""可编辑关系稿的严格 Markdown 协议；不猜配身份、不忽略未知内容。"""
import hashlib
from pathlib import Path
import re

from workflow import check_rows, require

FORMAT_VERSION=1
HEADER=re.compile(r'## (关系|未决|无关系) ([1-9][0-9]*)$')
IDENTITY=re.compile(r'<!-- pair_id: (P-[a-f0-9]+)(?:; source_event: (E[0-9]+); target_event: (E[0-9]+))? -->$')


def text_sha(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()


def label(snapshot,alias):
    e=snapshot['events'][alias]
    require('\n'not in e['title']and '\r'not in e['title'],'事件标题含换行，不能生成结构化关系稿')
    return e['diary_date']+'｜'+e['title']


def render_text(snapshot,rows):
    check_rows(snapshot,{'package_sha256':snapshot['package_sha256'],'results':rows})
    require(len(rows)==len(snapshot['pairs']),'全部事件对完成后才能生成完整关系稿')
    pairs={p['pair_id']:p for p in snapshot['pairs']}
    lines=[f"# {snapshot['diary_date']} 事件关系",'',f"<!-- relations_format: {FORMAT_VERSION}; package_sha256: {snapshot['package_sha256']} -->",'']
    for status,kind in (('RELATED','关系'),('UNRESOLVED','未决'),('NO_RELATION','无关系')):
        group=[r for r in rows if r['status']==status]
        if status=='NO_RELATION'and group:lines+=['<details>',f'<summary>无关系判断（{len(group)} 对）</summary>','']
        for i,row in enumerate(group,1):
            lines += [f'## {kind} {i}','']
            if status=='RELATED':
                rel=row['relation']
                lines += [f"<!-- pair_id: {row['pair_id']}; source_event: {rel['source_event']}; target_event: {rel['target_event']} -->",'',
                          '来源：'+label(snapshot,rel['source_event']),'目标：'+label(snapshot,rel['target_event']),
                          '类型：'+rel['relation_type'],'确定性：'+{'EXPLICIT':'明确','SPECULATIVE':'推测'}[rel['certainty']],
                          '', '### 关系说明','',rel['description'],'']
                if row['reason']!=rel['description']:lines+=['### 判断依据','',row['reason'],'']
                for side,name in (('source','来源'),('target','目标')):
                    lines+=['### '+name+'证据','']
                    for proof in rel[side+'_evidence']:
                        lines+=['#### 要点 '+str(proof['point_no']),'']
                        lines += ['> '+line if line else '>' for line in proof['quote'].split('\n')]+['']
            else:
                p=pairs[row['pair_id']]
                lines += [f"<!-- pair_id: {row['pair_id']} -->",'', '事件甲：'+label(snapshot,p['event_a']),
                          '事件乙：'+label(snapshot,p['event_b']),'','### 判断依据','',row['reason'],'']
        if status=='NO_RELATION'and group:lines+=['</details>','']
    return '\n'.join(lines)+'\n'


class Reader:
    def __init__(self,lines):self.lines=lines;self.pos=0
    def blank(self):
        while self.pos<len(self.lines)and not self.lines[self.pos].strip():self.pos+=1
    def take(self):
        self.blank();require(self.pos<len(self.lines),'关系稿结构未完成')
        value=self.lines[self.pos];self.pos+=1;return value
    def exact(self,value):require(self.take()==value,'关系稿缺少或改动了结构字段：'+value)
    def field(self,prefix):
        value=self.take();require(value.startswith(prefix),'关系稿字段错误：'+prefix)
        value=value[len(prefix):];require(value.strip(),'关系稿字段不能为空');return value
    def prose(self):
        self.blank();start=self.pos
        while self.pos<len(self.lines)and not self.lines[self.pos].startswith('#'):
            line=self.lines[self.pos]
            require(not any(x in line for x in ('<!--','-->','```','<details','</details','<summary','</summary')),'关系稿包含未知注释或结构')
            self.pos+=1
        result='\n'.join(self.lines[start:self.pos]).strip()
        require(result,'关系说明或判断依据不能为空');return result
    def evidence(self):
        proofs=[]
        while True:
            self.blank()
            if self.pos==len(self.lines)or not self.lines[self.pos].startswith('#### '):break
            match=re.fullmatch(r'#### 要点 ([1-9][0-9]*)',self.take());require(match,'证据标题必须为 #### 要点 N')
            self.blank();quotes=[]
            while self.pos<len(self.lines)and (self.lines[self.pos]=='>'or self.lines[self.pos].startswith('> ')):
                quotes.append(self.lines[self.pos][2:]);self.pos+=1
            require(quotes,'证据引用每一行须以 > 空格 开始')
            proofs.append({'point_no':int(match[1]),'quote':'\n'.join(quotes)})
        require(proofs,'双方证据不能为空');return proofs


def parse_text(text,snapshot,*,complete=True):
    require(isinstance(text,str),'关系稿必须为文本')
    reader=Reader(text.splitlines());reader.exact(f"# {snapshot['diary_date']} 事件关系")
    reader.exact(f"<!-- relations_format: {FORMAT_VERSION}; package_sha256: {snapshot['package_sha256']} -->")
    pairs={p['pair_id']:p for p in snapshot['pairs']};rows=[];fold=False;closed=False;fold_count=None
    counters={'关系':0,'未决':0,'无关系':0}
    while True:
        reader.blank()
        if reader.pos==len(reader.lines):break
        token=reader.take()
        if token=='<details>':
            require(not fold and not closed,'无关系折叠区重复');fold=True
            match=re.fullmatch(r'<summary>无关系判断（([1-9][0-9]*) 对）</summary>',reader.take())
            require(match,'无关系折叠区标题非法');fold_count=int(match[1]);continue
        if token=='</details>':
            require(fold and not closed,'无关系折叠区闭合错误');closed=True;fold=False;continue
        require(not closed,'无关系折叠区后不能附加其他内容')
        match=HEADER.fullmatch(token);require(match,'关系稿包含未知标题或正文：'+token[:60])
        kind=match[1];counters[kind]+=1
        require(int(match[2])==counters[kind],'同类关系稿条目须从 1 连续编号')
        require((kind=='无关系')==fold,'无关系须位于折叠区，关系及未决须位于正文')
        identity=IDENTITY.fullmatch(reader.take());require(identity,'缺少合法事件对及方向标识')
        pid,a,b=identity.groups();require(pid in pairs,'事件对不属于本次来源')
        row={'pair_id':pid,'status':{'关系':'RELATED','未决':'UNRESOLVED','无关系':'NO_RELATION'}[kind],'relation':None}
        if kind=='关系':
            require(a in snapshot['events']and b in snapshot['events'],'关系端点标识不存在')
            reader.exact('来源：'+label(snapshot,a));reader.exact('目标：'+label(snapshot,b))
            typ=reader.field('类型：');certainty=reader.field('确定性：')
            require(certainty in ('明确','推测'),'确定性只接受明确或推测')
            reader.exact('### 关系说明');description=reader.prose();reason=description
            reader.blank()
            if reader.pos<len(reader.lines)and reader.lines[reader.pos]=='### 判断依据':
                reader.exact('### 判断依据');reason=reader.prose()
            reader.exact('### 来源证据');source=reader.evidence()
            reader.exact('### 目标证据');target=reader.evidence()
            row.update(reason=reason,relation={'source_event':a,'target_event':b,'relation_type':typ,'certainty':{'明确':'EXPLICIT','推测':'SPECULATIVE'}[certainty],
                'description':description,'source_evidence':source,'target_evidence':target})
        else:
            require(a is None and b is None,'无关系或未决不能带关系方向')
            p=pairs[pid]
            reader.exact('事件甲：'+label(snapshot,p['event_a']));reader.exact('事件乙：'+label(snapshot,p['event_b']))
            reader.exact('### 判断依据')
            # 正文读取到下条标题或折叠区结束，不能吞掉结构标记。
            reader.blank();start=reader.pos
            while reader.pos<len(reader.lines)and not reader.lines[reader.pos].startswith('## ')and reader.lines[reader.pos]not in ('<details>','</details>'):
                reader.pos+=1
            reason=Reader(reader.lines[start:reader.pos]);row['reason']=reason.prose();reason.blank()
            require(reason.pos==len(reason.lines),'判断依据中含未知标题')
        rows.append(row)
    require(not fold,'无关系折叠区未闭合')
    if fold_count is not None:require(closed and counters['无关系']==fold_count,'无关系数量与折叠标题不符')
    check_rows(snapshot,{'package_sha256':snapshot['package_sha256'],'results':rows})
    if complete:require({r['pair_id']for r in rows}==set(pairs),'关系稿必须完整覆盖全部候选；删除关系不代表无关系，请显式更改状态')
    byid={r['pair_id']:r for r in rows}
    return [byid[p['pair_id']]for p in snapshot['pairs']if p['pair_id']in byid]


def read_draft(path,snapshot,*,complete=True):
    try:text=Path(path).read_bytes().decode('utf-8')
    except (OSError,UnicodeError):
        from workflow import WorkflowError
        raise WorkflowError('无法读取 UTF-8 关系稿')from None
    return text,parse_text(text,snapshot,complete=complete)
