"""Independent acceptance: package preservation, styles, real fields and mutation.

Run after a real agent: .venv/bin/python test/verify_notes_references.py RUN_DIR
Includes office rendering; never treats office-roundtrip DOCX as deliverable.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from zipfile import ZipFile
from lxml import etree as E

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('nr',ROOT/'skills/docx/scripts/notes_references.py');nr=importlib.util.module_from_spec(spec);spec.loader.exec_module(nr)
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}';NS={'w':W[1:-1]}


def shell(args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=120)
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    return result.stdout


def text(e):return ''.join(e.xpath('.//w:t/text()',namespaces=NS))


def parts(path):
    with ZipFile(path) as z:return {n:z.read(n) for n in z.namelist() if not n.endswith('/')}


def run(out):
    out=Path(out).resolve();source=ROOT/'test/artifacts/template-skill/run-08/filled-demo.docx'
    checks=[]
    def check(ok,label):checks.append({'passed':bool(ok),'check':label})
    raw=out/'capability-demo.docx';final=out/'capability-refreshed.docx'
    old,new=parts(source),parts(final);d=E.fromstring(new['word/document.xml']);st=E.fromstring(new['word/styles.xml']);foot=E.fromstring(new['word/footnotes.xml'])
    source_doc=E.fromstring(old['word/document.xml']);oldbody=list(source_doc.find('w:body',NS));newbody=list(d.find('w:body',NS))
    c14n=lambda x:E.tostring(x,method='c14n')
    check(all(c14n(a)==c14n(b) for a,b in zip(oldbody[:-1],newbody)) and c14n(oldbody[-1])==c14n(newbody[-1]),'All original body elements and final section properties are unchanged')
    changed={'word/document.xml','word/styles.xml','word/_rels/document.xml.rels','[Content_Types].xml'}
    check(set(new)-set(old)=={'word/footnotes.xml'},'Only native footnote package part added')
    for name,data in old.items():
        if name not in changed:check(new[name]==data,'Preserved package bytes: '+name)
    oldstyles=E.fromstring(old['word/styles.xml']).findall('w:style',NS);newstyles=st.findall('w:style',NS)
    check([c14n(s) for s in oldstyles]==[c14n(s) for s in newstyles[:len(oldstyles)]],'Every original custom style definition retained')
    check(len(newstyles)==len(oldstyles)+2,'Exactly two named footnote styles added')
    styles={s.get(W+'styleId'):s for s in newstyles}
    for sid,name,kind in [('PaperFootnoteText','论文脚注正文','paragraph'),('PaperFootnoteReference','论文脚注标记','character')]:
        s=styles[sid];check(s.get(W+'type')==kind and s.get(W+'customStyle')=='1' and s.find('w:name',NS).get(W+'val')==name and s.find('w:qFormat',NS) is not None,'Visible custom style '+name)
        check(s.find('w:rPr/w:sz',NS).get(W+'val')=='18','9 pt style '+name)
        fonts=s.find('w:rPr/w:rFonts',NS)
        check(fonts.get(W+'eastAsia')=='宋体' and fonts.get(W+'ascii')=='Times New Roman','Stored required font names '+name)
    check(styles['PaperFootnoteText'].find('w:pPr/w:spacing',NS).get(W+'line')=='240','Footnote text has single spacing')
    check(styles['PaperFootnoteReference'].find('w:rPr/w:vertAlign',NS).get(W+'val')=='superscript','Footnote marker style is superscript')
    notes=[n for n in foot if n.get(W+'type') not in ('separator','continuationSeparator')]
    check(len(notes)==2 and len(d.findall('.//w:footnoteReference',NS))==2,'Two native notes; repeats do not create additional notes')
    check(all(n.find('w:p/w:pPr/w:pStyle',NS).get(W+'val')=='PaperFootnoteText' for n in notes),'Both notes actually use the named text style')
    check(all(n.find('.//w:rPr/w:sz',NS) is None for n in notes),'Footnote size remains inherited and editable through style')
    check(all(r.find('w:rPr/w:rStyle',NS).get(W+'val')=='PaperFootnoteReference' for r in d.findall('.//w:r',NS) if r.find('w:footnoteReference',NS) is not None),'Body footnote markers actually use named marker style')
    check(b'footnotes.xml' in new['word/_rels/document.xml.rels'] and b'footnotes+xml' in new['[Content_Types].xml'],'Footnotes relationship and content type are present')
    report=nr.inspect(final);check(report['passed'],'Bookmark/field/note graph is structurally valid')
    expected={'Table_TestA':'表1','Table_TestB':'表2','Note_TestA':'1','Note_TestB':'2','Bib_TestA':'[1]','Bib_TestB':'[2]'}
    def refs(root):
        result=[]
        for f in root.findall('.//w:fldSimple',NS):
            m=re.match(r'\s*(NOTEREF|REF)\s+(\w+)',f.get(W+'instr',''))
            if m and m[2] in expected:result.append((m[1],m[2],text(f)))
        return result
    initial_refs=refs(d)
    check(set(r[1] for r in initial_refs)==set(expected),'All six table/note/bibliography targets are referenced')
    check(all(value==expected[target] for _,target,value in initial_refs),'Every initial displayed reference matches its target')
    check(sum(kind=='NOTEREF' for kind,_,_ in initial_refs)>=2,'Both footnotes have repeated NOTEREF references')
    check(all('\\h' in f.get(W+'instr','') for f in d.findall('.//w:fldSimple',NS) if re.match(r'\s*(NOTEREF|REF)\s',f.get(W+'instr',''))),'Every generated cross-reference requests navigation')
    check(len(d.findall('.//w:hyperlink/w:fldSimple',NS))>=2,'NOTEREF has explicit internal hyperlinks for Linux PDF compatibility')
    source_tables=len(source_doc.findall('.//w:tbl',NS))
    check(len(d.findall('.//w:tbl',NS))==source_tables+2,'Two real data tables added')
    check('表表' not in text(d),'No duplicate table label prefix in body text')
    check('虚构演示文献' in text(d),'Bibliography test entries clearly labelled as fictional')
    starts=d.findall('.//w:bookmarkStart',NS)
    forward=False;flat=list(d.iter())
    for f in d.findall('.//w:fldSimple',NS):
        m=re.match(r'\s*REF\s+(\w+)',f.get(W+'instr',''))
        if m and m[1] in expected:
            target=next(s for s in starts if s.get(W+'name')==m[1])
            if flat.index(f)<flat.index(target):forward=True
    check(forward,'At least one reference precedes its target')
    # Deliberately leave original 1/2 caches stale while inserting earlier targets.
    mutation=out/'mutation-stale.docx';refreshed=out/'mutation-refreshed.docx'
    shell([sys.executable,str(ROOT/'test/prepare_reference_mutation.py'),str(final),str(mutation)])
    shell([sys.executable,str(ROOT/'skills/docx/scripts/notes_references.py'),'refresh',str(mutation),str(refreshed),'--report',str(out/'mutation-refresh.json')])
    stale=E.fromstring(parts(mutation)['word/document.xml']);updated_parts=parts(refreshed);updated=E.fromstring(updated_parts['word/document.xml'])
    check(refs(stale)==initial_refs,'Mutation starts with stale original reference caches')
    new_expected={'Table_TestA':'表2','Table_TestB':'表3','Note_TestA':'2','Note_TestB':'3','Bib_TestA':'[2]','Bib_TestB':'[3]'}
    check(len(refs(updated))==len(initial_refs) and all(v==new_expected[t] for _,t,v in refs(updated)),'All original references renumber 1/2 to 2/3 after earlier insertion')
    check([n.get(W+'id') for n in updated.findall('.//w:footnoteReference',NS)]==['3','1','2'],'Footnote display numbers follow document order, independent of internal IDs')
    check(updated_parts['word/styles.xml']==new['word/styles.xml'],'Number refresh preserves every custom style byte')
    for name,data in parts(mutation).items():
        if name!='word/document.xml':check(updated_parts[name]==data,'Cache refresh preserves package part '+name)
    check(nr.inspect(refreshed)['passed'],'Mutated document retains valid native fields and note graph')
    xsd={}
    for path in (raw,final,mutation,refreshed):
        xsd[path.name]=shell([sys.executable,str(ROOT/'skills/docx/scripts/office/validate.py'),str(path)])
        check('All validations PASSED!' in xsd[path.name],'Full XSD validation '+path.name)
    # Two rendered outputs: the source and the renumbered authored DOCX.
    render={}
    for kind,path in [('base',final),('mutation',refreshed)]:
        dest=out/('render-'+kind)
        dest.mkdir(parents=True,exist_ok=True)
        render_input=dest/(path.stem+'-pdf-input.docx')
        adapter=nr.pdf_input(path,render_input)
        (dest/'pdf-adapter.json').write_text(json.dumps(adapter,ensure_ascii=False,indent=2)+'\n')
        check(len(adapter['converted_note_references'])==2,'PDF input adapts both repeated note references '+kind)
        check('All validations PASSED!' in shell([sys.executable,str(ROOT/'skills/docx/scripts/office/validate.py'),str(render_input)]),'PDF input remains valid DOCX '+kind)
        shell(['/usr/bin/python3',str(ROOT/'skills/docx/scripts/office/render_references.py'),str(render_input),str(dest),'--note-map',str(dest/'pdf-adapter.json')])
        pdf=dest/(render_input.stem+'.pdf')
        xml=shell(['pdftohtml','-xml','-zoom','1','-i','-hidden','-stdout',str(pdf)])
        (dest/'layout.xml').write_text(xml)
        layout=E.fromstring(xml.encode(),E.XMLParser(load_dtd=False,no_network=True));pages=layout.findall('page')
        test_pages=pages[10:];links=[];fontspec={n.get('id'):n for n in layout.findall('.//fontspec')}
        check(len(test_pages)>0,'Test section renders '+kind)
        for page in test_pages:
            for a in page.findall('.//a'):
                links.append({'page':page.get('number'),'destination':a.get('href'),'text':''.join(a.itertext())})
        check(all(re.search(r'#\d+$',a['destination'] or '') for a in links),'PDF references have internal destinations '+kind)
        check(len(links)>=len(initial_refs),'PDF contains navigation links for cross references '+kind)
        note_values={'1','2'} if kind=='base' else {'1','2','3'}
        note_numeric_links=[a for page in test_pages for n in page.findall('text') if int(fontspec[n.get('font')].get('size'))<9 for a in n.findall('.//a') if ''.join(a.itertext()).strip() in note_values]
        check(len(note_numeric_links)>=(4 if kind=='base' else 5),'PDF native and repeated note numbers are clickable '+kind)

        note_prefixes={re.sub(r'\s+','',text(n))[:6] for n in notes}
        footnote_runs=[(page,n) for page in test_pages for n in page.findall('text') if any(prefix in re.sub(r'\s+','',''.join(n.itertext())) for prefix in note_prefixes) and int(fontspec[n.get('font')].get('size'))==9]
        small_text=re.sub(r'\s+','',''.join(''.join(n.itertext()) for page in test_pages for n in page.findall('text') if int(fontspec[n.get('font')].get('size'))==9))
        check(all(re.sub(r'\s+','',text(n)) in small_text for n in notes),'Complete footnote contents render in 9 pt '+kind)
        check(len(footnote_runs)>=2,'Both footnote texts render in 9 pt '+kind)
        check(all(float(n.get('top'))>float(p.get('height'))*.65 for p,n in footnote_runs),'Footnotes render near page bottom '+kind)
        check(all(float(n.get('left'))>=20 and float(n.get('left'))+float(n.get('width'))<=float(p.get('width'))-20 for p in test_pages for n in p.findall('text')),'Test text and tables stay inside page bounds '+kind)
        extracted=shell(['pdftotext','-layout',str(pdf),'-']);(dest/'text.txt').write_text(extracted)
        render[kind]={'page_count':len(pages),'links':links,'footnote_text_runs':len(footnote_runs),'pdf':str(pdf)}
        # Office roundtrip is diagnostic only: preserve the authored deliverable.
        engine_doc=dest/(render_input.stem+'-updated.docx')
        render[kind]['roundtrip_diagnostics']=nr.inspect(engine_doc)['problems']
    result={'passed':all(c['passed'] for c in checks),'checks':checks,'xsd':xsd,'rendering':render,
            'dynamic_update_engine':'Skill OOXML supported number/text fields; LibreOffice for layout/PDF',
            'limitations':['No Microsoft Word UI/runtime validation','Required fonts unavailable; rendering uses substitutes','LibreOffice does not evaluate these NOTEREF fields and rewrites bookmark/style structure; roundtrip DOCX is diagnostic only','TOC and page field evaluation outside this test scope']}
    (out/'references-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':result['passed'],'checks':len(checks),'failed':[c['check'] for c in checks if not c['passed']],'report':str(out/'references-acceptance.json')},ensure_ascii=False))
    return result['passed']


if __name__=='__main__':raise SystemExit(0 if run(sys.argv[1]) else 1)
