"""Insert earlier targets with stale caches to challenge real field updating."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('nr',ROOT/'skills/docx/scripts/notes_references.py');nr=importlib.util.module_from_spec(spec);spec.loader.exec_module(nr)


def mutate(source,output):
    parts=nr.read(source);doc=nr.parse(parts['word/document.xml']);body=doc.find('w:body',nr.NS)
    foot=nr.parse(parts['word/footnotes.xml']);bid=max(int(n.get(nr.q('id'))) for n in doc.findall('.//w:bookmarkStart',nr.NS))+1
    def clone_caption(name,new_name):
        nonlocal bid
        start=next(n for n in doc.findall('.//w:bookmarkStart',nr.NS) if n.get(nr.q('name'))==name)
        p=start.getparent();copy=deepcopy(p)
        copy.find('w:bookmarkStart',nr.NS).set(nr.q('name'),new_name)
        copy.find('w:bookmarkStart',nr.NS).set(nr.q('id'),str(bid));copy.find('w:bookmarkEnd',nr.NS).set(nr.q('id'),str(bid));bid+=1
        for t in copy.findall('w:r/w:t',nr.NS)[-1:]:t.text=' 插入测试条目：用于检验旧目标编号顺延。'
        body.insert(body.index(p),copy)
        return p
    p=clone_caption('Table_TestA','Table_Inserted')
    table=p.getnext();body.insert(body.index(p),deepcopy(table))
    clone_caption('Bib_TestA','Bib_Inserted')
    first=doc.find('.//w:footnoteReference',nr.NS)
    parent=first
    while parent.tag!=nr.q('p'):parent=parent.getparent()
    fid=max(int(n.get(nr.q('id'))) for n in foot)+1
    p=nr.node('p'); pp=nr.node('pPr');pp.append(nr.node('pStyle',val='PaperBody'));p.append(pp)
    p.append(nr.run('插入测试脚注：此条在原有脚注之前。'))
    p.append(nr.node('bookmarkStart',id=bid,name='Note_Inserted'))
    r=nr.run(style='PaperFootnoteReference');r.append(nr.node('footnoteReference',id=fid));p.append(r);p.append(nr.node('bookmarkEnd',id=bid))
    body.insert(body.index(parent),p)
    original=next(n for n in foot if n.get(nr.q('id'))==first.get(nr.q('id')))
    fn=deepcopy(original);fn.set(nr.q('id'),str(fid))
    texts=fn.findall('.//w:t',nr.NS)
    for t in texts:t.text=''
    texts[0].text=' 插入测试脚注正文：原有脚注编号应从1、2变为2、3。';foot.append(fn)
    parts['word/document.xml']=nr.dump(doc);parts['word/footnotes.xml']=nr.dump(foot)
    with ZipFile(output,'w',ZIP_DEFLATED) as z:
        for name,data in parts.items():z.writestr(name,data)
    print(output)


if __name__=='__main__':mutate(sys.argv[1],sys.argv[2])
