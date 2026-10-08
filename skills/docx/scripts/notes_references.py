#!/usr/bin/env python3
"""Add styled native footnotes, sequence captions and bookmark cross-references.

apply SOURCE PLAN OUTPUT [--report REPORT]; inspect DOCX
Blocks are appended before the final sectPr, or before one exact body paragraph.
Existing package parts are preserved unless explicitly edited. Field caches are
initial display values; an office engine must update fields after later edits.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as E

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/package/2006/relationships'
C = 'http://schemas.openxmlformats.org/package/2006/content-types'
NS = {'w': W}
SPACE = '{http://www.w3.org/XML/1998/namespace}space'


def q(n): return '{'+W+'}'+n


def node(n, **attrs):
    return E.Element(q(n), {q(k): str(v) for k,v in attrs.items()})


def read(path):
    with ZipFile(path) as z:
        if z.testzip(): raise ValueError('Corrupt package')
        return {n:z.read(n) for n in z.namelist() if not n.endswith('/')}


def parse(data):
    return E.fromstring(data, E.XMLParser(resolve_entities=False, no_network=True))


def dump(root): return E.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)


def run(text=None, style=None, superscript=False):
    r = node('r')
    if style or superscript:
        rp = node('rPr'); r.append(rp)
        if style: rp.append(node('rStyle', val=style))
        if superscript: rp.append(node('vertAlign', val='superscript'))
    if text is not None:
        t = node('t'); t.text = str(text); t.set(SPACE, 'preserve'); r.append(t)
    return r


def field(instruction, cached, superscript=False):
    f = node('fldSimple', instr=' '+instruction+' ')
    f.append(run(cached, superscript=superscript))
    return f


def inspect(path):
    parts = read(path); doc = parse(parts['word/document.xml'])
    styles = parse(parts['word/styles.xml'])
    starts = doc.findall('.//w:bookmarkStart', NS)
    ends = doc.findall('.//w:bookmarkEnd', NS)
    names = [n.get(q('name')) for n in starts]
    ids = [n.get(q('id')) for n in starts]
    fields = [n.get(q('instr')).strip() for n in doc.findall('.//w:fldSimple',NS)]
    fields += [''.join(n.itertext()).strip() for n in doc.findall('.//w:instrText',NS)]
    refs = []
    for f in fields:
        m = re.match(r'(NOTEREF|REF|PAGEREF)\s+(\w+)(?:\s|$)', f, re.I)
        if m: refs.append({'kind':m[1].upper(),'target':m[2], 'instruction':f})
    foot = parse(parts['word/footnotes.xml']) if 'word/footnotes.xml' in parts else node('footnotes')
    notes = {n.get(q('id')):n for n in foot.findall('w:footnote',NS) if n.get(q('type')) not in ('separator','continuationSeparator','continuationNotice')}
    markers = [n.get(q('id')) for n in doc.findall('.//w:footnoteReference',NS)]
    problems = []
    if len(names)!=len(set(names)) or len(ids)!=len(set(ids)): problems.append('Duplicate bookmark names/IDs')
    if Counter(ids)!=Counter(n.get(q('id')) for n in ends): problems.append('Unpaired bookmarks')
    for ref in refs:
        if ref['target'] not in names: problems.append('Missing bookmark: '+ref['target'])
        elif ref['kind']=='NOTEREF':
            start = next(n for n in starts if n.get(q('name'))==ref['target'])
            # This helper anchors notes around exactly the native marker in one paragraph.
            enclosed = []
            for sibling in start.itersiblings():
                if sibling.tag==q('bookmarkEnd') and sibling.get(q('id'))==start.get(q('id')): break
                enclosed += sibling.findall('.//w:footnoteReference',NS)
            if len(enclosed)!=1: problems.append('NOTEREF target must enclose one native footnote marker')
    if any(i not in notes for i in markers): problems.append('Dangling footnote marker')
    if notes:
        rels=parse(parts['word/_rels/document.xml.rels'])
        links=[r for r in rels if r.get('Type','').endswith('/footnotes')]
        if len(links)!=1 or links[0].get('Target')!='footnotes.xml' or links[0].get('TargetMode')=='External': problems.append('Invalid footnotes relationship')
        types=parse(parts['[Content_Types].xml'])
        if not any(n.get('PartName')=='/word/footnotes.xml' and n.get('ContentType')=='application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml' for n in types): problems.append('Missing footnotes content type')

    if Counter(markers)!=Counter(notes.keys()): problems.append('Orphan or multiply inserted native footnote; repeat with NOTEREF')
    defined={n.get(q('styleId')) for n in styles.findall('w:style',NS)}
    for root in (doc,foot):
        for tag in ('pStyle','rStyle','tblStyle'):
            if any(n.get(q('val')) not in defined for n in root.findall('.//w:'+tag,NS)): problems.append('Dangling '+tag)
    note_styles=[]
    for s in styles.findall('w:style',NS):
        if s.get(q('styleId')) in ('PaperFootnoteText','PaperFootnoteReference'):
            note_styles.append({'id':s.get(q('styleId')), 'xml':E.tostring(s,encoding='unicode')})
    return {'passed':not problems, 'problems':problems,'footnote_count':len(notes),'footnote_marker_ids':markers,
            'bookmarks':names,'fields':fields,'references':refs,'footnote_styles':note_styles}


def apply(source, plan, output):
    if Path(source).resolve()==Path(output).resolve(): raise ValueError('Output must differ from source')
    if plan.get('source_sha256') != hashlib.sha256(Path(source).read_bytes()).hexdigest():
        raise ValueError('Plan requires matching source_sha256')
    parts=read(source); doc=parse(parts['word/document.xml']); styles=parse(parts['word/styles.xml'])
    body=doc.find('w:body',NS)
    defined={s.get(q('styleId')) for s in styles.findall('w:style',NS)}
    config=plan['footnote_style']
    # Fixed IDs make styles easy to find; existing definitions require an explicit different workflow.
    if {'PaperFootnoteText','PaperFootnoteReference'} & defined: raise ValueError('Footnote style IDs already exist')
    for sid,name,kind in [('PaperFootnoteText','论文脚注正文','paragraph'),('PaperFootnoteReference','论文脚注标记','character')]:
        s=node('style', type=kind, customStyle='1', styleId=sid)
        s.append(node('name',val=name)); s.append(node('uiPriority',val='40')); s.append(node('qFormat'))
        if kind=='paragraph':
            pp=node('pPr'); pp.append(node('snapToGrid',val='0'))
            pp.append(node('spacing',before='0',after='0',line=config.get('line',240),lineRule='auto')); s.append(pp)
        rp=node('rPr'); rp.append(node('rFonts',ascii=config['latin_font'],hAnsi=config['latin_font'],eastAsia=config['east_asia_font'],cs=config['latin_font']))
        size=config['size_pt'] if kind=='paragraph' else config.get('marker_size_pt',config['size_pt'])
        if size<=0 or size*2!=int(size*2): raise ValueError('Size must be positive half-points')
        rp.append(node('sz',val=int(size*2))); rp.append(node('szCs',val=int(size*2)))
        if kind=='character': rp.append(node('vertAlign',val='superscript'))
        s.append(rp); styles.append(s)
    defined.update(('PaperFootnoteText','PaperFootnoteReference'))
    foot=parse(parts['word/footnotes.xml']) if 'word/footnotes.xml' in parts else E.Element(q('footnotes'),nsmap={'w':W})
    if 'word/footnotes.xml' not in parts:
        for fid,kind,tag in [(-1,'separator','separator'),(0,'continuationSeparator','continuationSeparator')]:
            fn=node('footnote',id=fid,type=kind); p=node('p'); r=run(); r.append(node(tag)); p.append(r); fn.append(p); foot.append(fn)
    settings=parse(parts['word/settings.xml'])
    for root in (doc,settings):
        for props in root.findall('.//w:footnotePr',NS):
            for tag,expected in [('numFmt','decimal'),('numRestart','continuous'),('numStart','1')]:
                value=props.find('w:'+tag,NS)
                if value is not None and value.get(q('val'))!=expected:
                    raise ValueError('Initial caches require decimal continuous footnote numbering starting at 1')
    note_number=len(doc.findall('.//w:footnoteReference',NS))
    next_note=max([0]+[int(n.get(q('id'))) for n in foot])+1
    next_bm=max([-1]+[int(n.get(q('id'))) for n in doc.findall('.//w:bookmarkStart',NS)])+1
    names={n.get(q('name')) for n in doc.findall('.//w:bookmarkStart',NS)}
    targets={}; seq_counts=Counter()
    existing_fields=' '.join(n.get(q('instr'),'') for n in doc.findall('.//w:fldSimple',NS))+' '+' '.join(doc.xpath('//w:instrText/text()',namespaces=NS))
    # Register targets in document order so forward references receive correct initial caches.
    for block in plan['blocks']:
        items=block.get('inlines',[]) if block['type']=='paragraph' else [block] if block['type']=='caption' else []
        for item in items:
            if isinstance(item,str) or not any(k in item for k in ('footnote','bookmark')): continue
            name=item.get('bookmark') or item['footnote']['bookmark']
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',name) or name in names: raise ValueError('Invalid/duplicate bookmark '+name)
            names.add(name)
            if 'footnote' in item:
                note_number+=1
                targets[name]={'kind':'note','id':next_note,'cached':str(note_number)}; next_note+=1
            else:
                seq=item['sequence']
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',seq): raise ValueError('Invalid sequence identifier')
                if re.search(r'\bSEQ\s+'+re.escape(seq)+r'(?:\s|$)',existing_fields,re.I): raise ValueError('Existing sequence requires engine-based numbering; choose a new sequence for this insertion')
                seq_counts[seq]+=1
                targets[name]={'kind':'caption','prefix':item.get('prefix',''),'number':seq_counts[seq],'cached':item.get('prefix','')+str(seq_counts[seq])+item.get('suffix','')}
    def bookmark(p,name,children):
        nonlocal next_bm
        p.append(node('bookmarkStart',id=next_bm,name=name)); p.extend(children); p.append(node('bookmarkEnd',id=next_bm)); next_bm+=1
    def paragraph(style):
        if style not in defined: raise ValueError('Unknown paragraph style '+style)
        p=node('p'); pp=node('pPr'); pp.append(node('pStyle',val=style)); p.append(pp); return p
    added=[]
    for block in plan['blocks']:
        typ=block['type']
        if typ=='paragraph':
            p=paragraph(block.get('style','PaperBody'))
            if block.get('page_break_before'): p.find('w:pPr',NS).append(node('pageBreakBefore'))
            for inline_index,item in enumerate(block['inlines']):
                if isinstance(item,str): p.append(run(item)); continue
                if 'footnote' in item:
                    spec=item['footnote']; name=spec['bookmark']; target=targets[name]
                    r=run(style='PaperFootnoteReference'); r.append(node('footnoteReference',id=target['id'])); bookmark(p,name,[r])
                    fn=node('footnote',id=target['id']); fp=paragraph('PaperFootnoteText')
                    fr=run(style='PaperFootnoteReference'); fr.append(node('footnoteRef')); fp.extend([fr,run(' '+spec['text'])]); fn.append(fp); foot.append(fn)
                elif 'ref' in item:

                    if item['ref'] not in targets: raise ValueError('Unknown reference '+item['ref'])
                    target=targets[item['ref']]
                    prefix=target.get('prefix','')
                    preceding=block['inlines'][inline_index-1] if inline_index else None
                    if prefix and isinstance(preceding,str) and preceding.rstrip().endswith(prefix):
                        raise ValueError('Reference already includes prefix '+prefix+'; remove duplicate preceding label')
                    kind='NOTEREF' if target['kind']=='note' else 'REF'
                    instruction=kind+' '+item['ref']+' \\h'+(' \\f' if kind=='NOTEREF' and item.get('superscript') else '')
                    ref_field=field(instruction,target['cached'],item.get('superscript',False))
                    if kind=='NOTEREF':
                        link=node('hyperlink',anchor=item['ref'],history='1');link.append(ref_field);p.append(link)
                    else:p.append(ref_field)
                else: raise ValueError('Unknown inline')
            added.append(p)
        elif typ=='caption':
            p=paragraph(block['style']); target=targets[block['bookmark']]
            bookmark(p,block['bookmark'],[run(block.get('prefix','')),field('SEQ '+block['sequence']+' \\* ARABIC',str(target['number'])),run(block.get('suffix',''))])
            p.append(run(' '+block['text'])); added.append(p)
        elif typ=='table':
            rows=block['rows']; cols=len(rows[0])
            if not cols or any(len(row)!=cols for row in rows): raise ValueError('Table rows must be rectangular')
            widths=block.get('column_widths',[2400]*cols)
            if len(widths)!=cols or any(w<=0 for w in widths): raise ValueError('Invalid column widths')
            tbl=node('tbl'); tp=node('tblPr')
            if block.get('style'):
                if block['style'] not in defined: raise ValueError('Unknown table style')
                tp.append(node('tblStyle',val=block['style']))
            tp.append(node('tblW',w=sum(widths),type='dxa')); tbl.append(tp); grid=node('tblGrid')
            for width in widths: grid.append(node('gridCol',w=width))
            tbl.append(grid)
            for row in rows:
                tr=node('tr')
                for i,value in enumerate(row):
                    tc=node('tc'); tcp=node('tcPr'); tcp.append(node('tcW',w=widths[i],type='dxa')); tc.append(tcp)
                    p=paragraph(block.get('text_style','PaperBody')); p.append(run(value)); tc.append(p); tr.append(tc)
                tbl.append(tr)
            added.append(tbl)
        else: raise ValueError('Unknown block type '+typ)
    anchor=body.find('w:sectPr',NS)
    if plan.get('insert_before'):
        matches=[p for p in body.findall('w:p',NS) if ''.join(p.xpath('.//w:t/text()',namespaces=NS))==plan['insert_before']]
        if len(matches)!=1: raise ValueError('insert_before must match exactly one body paragraph')
        anchor=matches[0]
    pos=body.index(anchor) if anchor is not None else len(body)
    for child in added: body.insert(pos,child); pos+=1
    rels=parse(parts['word/_rels/document.xml.rels']); reltype='http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes'
    existing=[r for r in rels if r.get('Type')==reltype]
    if existing and (len(existing)!=1 or existing[0].get('Target')!='footnotes.xml'): raise ValueError('Unsupported existing footnotes relationship')
    if not existing:
        ids={r.get('Id') for r in rels}; n=1
        while 'rId'+str(n) in ids:n+=1
        E.SubElement(rels,'{'+R+'}Relationship',Id='rId'+str(n),Type=reltype,Target='footnotes.xml')
    types=parse(parts['[Content_Types].xml']); path='/word/footnotes.xml'
    if not any(n.get('PartName')==path for n in types):
        E.SubElement(types,'{'+C+'}Override',PartName=path,ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml')
    for name,root in [('word/document.xml',doc),('word/styles.xml',styles),('word/footnotes.xml',foot),('word/_rels/document.xml.rels',rels),('[Content_Types].xml',types)]: parts[name]=dump(root)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,'w',ZIP_DEFLATED) as z:
        for name,data in parts.items():z.writestr(name,data)
    report=inspect(output)
    report.update(source_sha256=plan['source_sha256'],added_blocks=len(added),field_cache_status='Initial values only; update with an office engine after edits')
    if not report['passed']: raise ValueError(report['problems'])
    return report


def refresh(source, output):
    """Refresh supported number/text caches while retaining native fields/styles.

    This deliberately does not calculate page numbers. It supports the helper's
    simple decimal SEQ, REF and NOTEREF fields only. Complex fields stay intact.
    """
    if Path(source).resolve()==Path(output).resolve(): raise ValueError('Output must differ from source')
    report=inspect(source)
    if not report['passed']: raise ValueError(report['problems'])
    parts=read(source);doc=parse(parts['word/document.xml']);settings=parse(parts['word/settings.xml'])
    for root in (doc,settings):
        for props in root.findall('.//w:footnotePr',NS):
            for tag,expected in [('numFmt','decimal'),('numRestart','continuous'),('numStart','1')]:
                n=props.find('w:'+tag,NS)
                if n is not None and n.get(q('val'))!=expected: raise ValueError('Unsupported footnote numbering mode')
    marker_ids=[n.get(q('id')) for n in doc.findall('.//w:footnoteReference',NS)]
    note_numbers={fid:str(i+1) for i,fid in enumerate(marker_ids)}
    simple=doc.findall('.//w:fldSimple',NS)
    changed=[]; counts=Counter()
    def set_cache(f,value):
        text_nodes=f.findall('.//w:t',NS)
        if not text_nodes: raise ValueError('Field has no cached text run')
        previous=''.join(n.text or '' for n in text_nodes)
        if previous!=value:
            text_nodes[0].text=value;text_nodes[0].set(SPACE,'preserve')
            for n in text_nodes[1:]:n.text=''
            changed.append({'instruction':f.get(q('instr')).strip(),'before':previous,'after':value})
    for f in simple:
        instr=f.get(q('instr'),'').strip()
        if instr.upper().startswith('SEQ '):
            m=re.fullmatch(r'SEQ\s+([A-Za-z][A-Za-z0-9_]*)\s+\\\*\s+ARABIC',instr,re.I)
            if not m: raise ValueError('Unsupported SEQ switches: '+instr)
            counts[m[1]]+=1;set_cache(f,str(counts[m[1]]))
    for iteration in range(8):
        active={};bookmarks={};note_targets={}
        for e in doc.iter():
            if e.tag==q('bookmarkStart'):active[e.get(q('id'))]={'name':e.get(q('name')),'text':[],'notes':[]}
            elif e.tag==q('bookmarkEnd'):
                target=active.pop(e.get(q('id')))
                bookmarks[target['name']]=''.join(target['text'])
                if len(target['notes'])==1:note_targets[target['name']]=note_numbers[target['notes'][0]]
            elif e.tag==q('t'):
                for target in active.values():target['text'].append(e.text or '')
            elif e.tag==q('footnoteReference'):
                fid=e.get(q('id'))
                for target in active.values():target['text'].append(note_numbers[fid]);target['notes'].append(fid)
        before_count=len(changed)
        for f in simple:
            instr=f.get(q('instr'),'').strip()
            if not re.match(r'(NOTEREF|REF)\s',instr,re.I):continue
            m=re.fullmatch(r'(NOTEREF|REF)\s+(\w+)(?:\s+\\h)?(?:\s+\\f)?',instr,re.I)
            if not m or (m[1].upper()=='REF' and '\\f' in instr):raise ValueError('Unsupported reference switches: '+instr)
            targets=note_targets if m[1].upper()=='NOTEREF' else bookmarks
            if m[2] not in targets: raise ValueError('Missing/invalid reference target '+m[2])
            set_cache(f,targets[m[2]])
        if len(changed)==before_count:break
    else:raise ValueError('Reference caches did not converge')
    parts['word/document.xml']=dump(doc)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,'w',ZIP_DEFLATED) as z:
        for name,data in parts.items():z.writestr(name,data)
    result=inspect(output);result.update(cache_updates=changed,engine='OOXML supported number/text fields',scope='Simple decimal SEQ/REF/NOTEREF; no pagination or complex field evaluation')
    return result


def pdf_input(source, output):
    """Make a disposable PDF input: unevaluated NOTEREF -> cached hyperlink.

    Keep the authored DOCX for editing. A PDF is static, so this compatibility
    translation retains correct display/navigation without requiring an office
    engine to understand NOTEREF. All reference caches must already be current.
    """
    if Path(source).resolve()==Path(output).resolve(): raise ValueError('Output must differ from source')
    check=inspect(source)
    if not check['passed']:raise ValueError(check['problems'])
    parts=read(source);doc=parse(parts['word/document.xml']);converted=[]
    for f in list(doc.findall('.//w:fldSimple',NS)):
        instr=f.get(q('instr'),'').strip();m=re.fullmatch(r'NOTEREF\s+(\w+)\s+\\h(?:\s+\\f)?',instr,re.I)
        if not m:continue
        link=node('hyperlink',anchor=m[1],history='1')
        for child in list(f):link.append(child)
        parent=f.getparent()
        if parent.tag==q('hyperlink'):
            # The authored outer hyperlink contains exactly this field.
            grand=parent.getparent();index=grand.index(parent);grand.remove(parent);grand.insert(index,link)
        else:
            index=parent.index(f);parent.remove(f);parent.insert(index,link)
        converted.append({'instruction':instr,'display':''.join(link.xpath('.//w:t/text()',namespaces=NS))})
    # LibreOffice collapses bookmarks covering only a native footnote marker.
    # In the disposable render copy, anchor the target on adjacent body text without the marker.
    # The UNO render bridge uses actual footnotes for final PDF navigation.
    converted_names={re.match(r'NOTEREF\s+(\w+)',r['instruction'],re.I)[1] for r in converted}
    expanded=[]
    for start in doc.findall('.//w:bookmarkStart',NS):
        if start.get(q('name')) not in converted_names:continue
        parent=start.getparent();end=next(e for e in parent if e.tag==q('bookmarkEnd') and e.get(q('id'))==start.get(q('id')))
        preceding=next((e for e in reversed(list(parent)[:parent.index(start)]) if e.findall('.//w:t',NS)),None)
        if preceding is not None:
            parent.remove(start);parent.insert(parent.index(preceding),start)
            parent.remove(end);parent.insert(parent.index(preceding)+1,end)
        else:
            following=next((e for e in list(parent)[parent.index(end)+1:] if e.findall('.//w:t',NS)),None)
            if following is None:raise ValueError('PDF footnote destination needs adjacent body text')
            parent.remove(start);parent.insert(parent.index(following),start)
            parent.remove(end);parent.insert(parent.index(following)+1,end)
        expanded.append(start.get(q('name')))
    parts['word/document.xml']=dump(doc)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,'w',ZIP_DEFLATED) as z:
        for name,data in parts.items():z.writestr(name,data)
    return {'passed':True,'render_destinations_on_adjacent_text':expanded,'converted_note_references':converted,'purpose':'Disposable PDF render input only; authored DOCX retains native NOTEREF fields','source':str(source),'output':str(output)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('apply'); a.add_argument('source'); a.add_argument('plan'); a.add_argument('output'); a.add_argument('--report')
    a=sub.add_parser('inspect'); a.add_argument('source')
    a=sub.add_parser('refresh'); a.add_argument('source'); a.add_argument('output'); a.add_argument('--report')
    args=p.parse_args()
    if args.cmd=='apply':report=apply(args.source,json.loads(Path(args.plan).read_text()),args.output)
    elif args.cmd=='refresh':report=refresh(args.source,args.output)
    elif args.cmd=='pdf-input':report=pdf_input(args.source,args.output)
    else:report=inspect(args.source)
    if getattr(args,'report',None): Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report['passed'] else 1)
