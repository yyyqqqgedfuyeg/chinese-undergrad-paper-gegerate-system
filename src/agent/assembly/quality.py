"""Structural cleanup and final checks for assembled documents, without models."""
from copy import deepcopy
from hashlib import sha256
import re
from lxml import etree as E
from .engine import NS, W, text, paragraph_property


def heading_levels(styles):
    records = {s.get('{'+W+'}styleId'): s for s in styles.findall('w:style', NS)}
    def level(p):
        direct=p.find('w:pPr/w:outlineLvl',NS)
        if direct is not None:return int(direct.get('{'+W+'}val'))
        style=p.find('w:pPr/w:pStyle',NS); key=style.get('{'+W+'}val') if style is not None else None
        seen=set()
        while key in records and key not in seen:
            seen.add(key);s=records[key];v=s.find('w:pPr/w:outlineLvl',NS)
            if v is not None:return int(v.get('{'+W+'}val'))
            parent=s.find('w:basedOn',NS);key=parent.get('{'+W+'}val') if parent is not None else None
        return 9
    return level


def meaningful(node):
    return bool(text(node).strip() or node.xpath('.//w:drawing|.//w:pict|.//w:tbl',namespaces=NS))


def check_content(document, styles):
    level=heading_levels(styles);body=document.find('w:body',NS);children=list(body)
    headings=[(i,p,level(p)) for i,p in enumerate(children) if p.tag=='{'+W+'}p' and level(p)<9]
    for i,p,lvl in headings:
        if not text(p).strip():raise ValueError('成稿包含空标题')
        end=next((j for j,_,other in headings if j>i and other<=lvl),len(children))
        content=[n for n in children[i+1:end] if not (n.tag=='{'+W+'}p' and level(n)<9)]
        if not any(meaningful(n) for n in content):
            raise ValueError('标题下没有有效内容：'+text(p))
    entries=document.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="PaperContents"]]/w:sdtContent/w:p',namespaces=NS)
    if entries:
        labels=[''.join(p.xpath('./w:hyperlink//w:t/text()',namespaces=NS)) for p in entries]
        if labels != [text(p) for _,p,lvl in headings if lvl<3]:
            raise ValueError('目录条目与实际有效标题不一致')
        bookmarks=set(document.xpath('.//w:bookmarkStart/@w:name',namespaces=NS))
        for entry in entries:
            target=entry.xpath('./w:hyperlink/@w:anchor',namespaces=NS)
            if not target or target[0] not in bookmarks:
                raise ValueError('目录跳转目标不存在')
    return {'passed':True,'headings':len(headings),'empty_headings':0,'empty_sections':0,
            'checked_toc_entries':len(entries)}


def clean_and_check(document, styles, build_contents=True):
    body=document.find('w:body',NS);level=heading_levels(styles)
    removed=[];removed_sections=[]
    # Only known optional template sections may be silently removed.
    for p in list(body):
        if p.tag!='{'+W+'}p' or re.sub(r'\s','',text(p)) not in {'前言','附录'}:continue
        siblings=list(body);i=siblings.index(p);lvl=level(p)
        end=next((j for j in range(i+1,len(siblings)) if siblings[j].tag=='{'+W+'}p' and level(siblings[j])<=lvl and text(siblings[j]).strip()),len(siblings))
        candidates=siblings[i+1:end]
        if not any(meaningful(n) for n in candidates):
            removed.append(text(p))
            for n in [p,*candidates]:
                if n.tag=='{'+W+'}sectPr':continue
                removed_sections.extend(E.tostring(x) for x in n.xpath('.//w:sectPr',namespaces=NS))
                body.remove(n)
    # Blank template paragraphs must never create entries in the navigation pane.
    for p in document.xpath('.//w:p',namespaces=NS):
        if not meaningful(p) and level(p)<9:paragraph_property(p,'outlineLvl',val=9)
    toc=next((p for p in body if p.tag=='{'+W+'}p' and re.sub(r'\s','',text(p))=='目录'),None)
    start=list(body).index(toc) if toc is not None else 0
    for p in list(body)[start+1:]:
        if p.tag=='{'+W+'}p' and not meaningful(p):
            if toc is None and p.xpath('.//w:fldSimple|.//w:fldChar',namespaces=NS):
                continue
            if p.find('w:pPr/w:sectPr',NS) is None:body.remove(p)
            else:
                paragraph_property(p,'spacing',before=0,after=0,line=20,lineRule='exact')
                paragraph_property(p,'outlineLvl',val=9)
    report=check_content(document,styles)
    report.update(removed_empty_template_sections=removed)
    if toc is not None and build_contents:
        # Discard old cached TOC runs/fields; never ship dotted empty rows.
        children=list(body);begin=children.index(toc)+1
        for p in children[begin:]:
            if p.tag=='{'+W+'}p' and p.find('w:pPr/w:sectPr',NS) is not None:break
            sid=p.xpath('./w:pPr/w:pStyle/@w:val',namespaces=NS)
            is_toc_entry=bool(sid and re.match(r'toc|目录',sid[0],re.I))
            if meaningful(p) and not is_toc_entry:break
            body.remove(p)
        old=body.xpath('./w:sdt[w:sdtPr/w:tag[@w:val="PaperContents"]]',namespaces=NS)
        for item in old:body.remove(item)
        generated=document.xpath('.//w:bookmarkStart[starts-with(@w:name,"PaperHeading")]',namespaces=NS)
        ids={x.get('{'+W+'}id') for x in generated}
        for marker in [*generated,*document.xpath('.//w:bookmarkEnd',namespaces=NS)]:
            if marker.get('{'+W+'}id') in ids:marker.getparent().remove(marker)
        headings=[p for p in body if p.tag=='{'+W+'}p' and level(p)<3 and text(p).strip()]
        if not headings:raise ValueError('目录没有有效标题')
        control=E.Element('{'+W+'}sdt');pr=E.SubElement(control,'{'+W+'}sdtPr')
        E.SubElement(pr,'{'+W+'}tag',{'{'+W+'}val':'PaperContents'})
        content=E.SubElement(control,'{'+W+'}sdtContent')
        next_id=max([int(v) for v in document.xpath('.//w:bookmarkStart/@w:id',namespaces=NS)]+[0])+1
        toc_style=next((s.get('{'+W+'}styleId') for s in styles.findall('w:style',NS) if s.get('{'+W+'}styleId')=='tocEntry'),None)
        for index,heading in enumerate(headings):
            name='PaperHeading'+sha256((str(index)+text(heading)).encode()).hexdigest()[:20]
            mark=E.Element('{'+W+'}bookmarkStart',{'{'+W+'}id':str(next_id),'{'+W+'}name':name})
            heading.insert(1 if heading.find('w:pPr',NS) is not None else 0,mark)
            E.SubElement(heading,'{'+W+'}bookmarkEnd',{'{'+W+'}id':str(next_id)});next_id+=1
            p=E.SubElement(content,'{'+W+'}p')
            if toc_style:paragraph_property(p,'pStyle',val=toc_style)
            paragraph_property(p,'outlineLvl',val=9)
            paragraph_property(p,'spacing',before=0,after=0,line=240,lineRule='auto')
            paragraph_property(p,'snapToGrid',val=0)
            paragraph_property(p,'ind',left=level(heading)*240,firstLine=0)
            paragraph_property(p,'jc',val='left')
            tabs=paragraph_property(p,'tabs')
            for pos in styles.xpath('.//w:tabs/w:tab/@w:pos',namespaces=NS):
                E.SubElement(tabs,'{'+W+'}tab',{'{'+W+'}val':'clear','{'+W+'}pos':pos})
            E.SubElement(tabs,'{'+W+'}tab',{'{'+W+'}val':'right','{'+W+'}pos':'8500','{'+W+'}leader':'none'})
            link=E.SubElement(p,'{'+W+'}hyperlink',{'{'+W+'}anchor':name})
            run=E.SubElement(link,'{'+W+'}r');E.SubElement(run,'{'+W+'}t').text=text(heading)
            run=E.SubElement(p,'{'+W+'}r');E.SubElement(run,'{'+W+'}tab')
            field=E.SubElement(p,'{'+W+'}fldSimple',{'{'+W+'}instr':'PAGEREF '+name+' \\h'})
            run=E.SubElement(field,'{'+W+'}r');E.SubElement(run,'{'+W+'}t').text='—'
        body.insert(list(body).index(toc)+1,control)
        report['toc_entries']=len(headings)
        report['toc_mode']='bookmark_page_fields; refreshed by local finalizer'
    return report,removed_sections
