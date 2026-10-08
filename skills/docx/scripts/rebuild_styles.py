"""Replace the entire source style set with visible, applied template styles.

Source formatting is resolved before deleting definitions. Named styles use
representative cleaned paragraphs/runs; matching direct formatting is removed
so editing a named style actually changes its paragraphs. Mixed run formatting
and layout exceptions remain direct. No original style definition is retained.
"""
from copy import deepcopy
import re

from lxml import etree as ET

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
TOGGLES = set('b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint vanish'.split())
P_ORDER = 'pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange'.split()
R_ORDER = 'rStyle rFonts b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint noProof snapToGrid vanish webHidden color spacing w kern position sz szCs highlight u effect bdr shd fitText vertAlign rtl cs em lang eastAsianLayout specVanish oMath rPrChange'.split()
ATTR_MERGE = {'spacing','ind','rFonts','lang'}


def q(name):
    return '{'+W+'}'+name


def value(e, default=None):
    return e.get(q('val'),default) if e is not None else default


def enabled(e):
    return value(e,'1') not in ('0','false','off')


def xml(data):
    return ET.tostring(data,xml_declaration=True,encoding='UTF-8',standalone=True)


def children(pr):
    return {ET.QName(c).localname:deepcopy(c) for c in pr} if pr is not None else {}


def merge(base, extra, style_layer=False):
    result = {k:deepcopy(v) for k,v in base.items()}
    for name,child in extra.items():
        if name in ('pStyle','rStyle','rPr'):
            continue
        if style_layer and name in TOGGLES:
            if enabled(child):
                old = enabled(result[name]) if name in result else False
                node = ET.Element(q(name));node.set(q('val'),'0' if old else '1')
                result[name] = node
            continue
        if name in ATTR_MERGE and name in result:
            node = deepcopy(result[name]);node.attrib.update(child.attrib)
            # An explicit font name overrides an inherited theme font slot.
            if name == 'rFonts':
                for slot in ('ascii','hAnsi','eastAsia','cs'):
                    if child.get(q(slot)) is not None:
                        node.attrib.pop(q(slot+'Theme'),None)
            result[name] = node
        else:
            result[name] = deepcopy(child)
    return result


def properties(tag, mapping):
    root = ET.Element(q(tag))
    orders={'pPr':P_ORDER,'rPr':R_ORDER,'tblPr':'tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize tblW jc tblCellSpacing tblInd tblBorders shd tblLayout tblCellMar tblLook tblCaption tblDescription'.split()}
    order = orders.get(tag,[])
    for name,node in sorted(mapping.items(),key=lambda kv:order.index(kv[0]) if kv[0] in order else len(order)):
        root.append(deepcopy(node))
    return root


def override(mapping, values):
    result = deepcopy(mapping)
    for name,attrs in values.items():
        node = ET.Element(q(name))
        for key,v in attrs.items():node.set(q(key),str(v))
        result[name] = node
    return result


def prune(mapping, baseline):
    """Remove only properties/attributes already supplied by the applied style."""
    result = {}
    for name,node in mapping.items():
        if name not in baseline:
            result[name] = deepcopy(node);continue
        other = baseline[name]
        if name in ATTR_MERGE:
            new = deepcopy(node)
            for key,v in list(new.attrib.items()):
                if other.get(key) == v:new.attrib.pop(key)
            if new.attrib or len(new):result[name] = new
        elif name in TOGGLES:
            if enabled(node) != enabled(other):result[name] = deepcopy(node)
        elif ET.tostring(node,method='c14n',exclusive=True) != ET.tostring(other,method='c14n',exclusive=True):
            result[name] = deepcopy(node)
    # Absence in the old cascade means default/off, not inheritance from a
    # newly introduced style (e.g. cover label must not acquire an underline).
    for name,node in baseline.items():
        if name in mapping:continue
        reset = None
        if name in TOGGLES and enabled(node):reset='0'
        elif name=='u' and value(node) not in ('none',None):reset='none'
        elif name=='color' and value(node) not in ('auto',None):reset='auto'
        elif name in ('spacing','kern','position') and name not in ATTR_MERGE and value(node) not in ('0',None):reset='0'
        if reset is not None:
            result[name]=ET.Element(q(name));result[name].set(q('val'),reset)
    return result


def rebuild(parts, config):
    if config.get('mode') != 'replace_all':
        raise ValueError('style_rebuild.mode must be replace_all')
    from docx.oxml import parse_xml
    old = ET.fromstring(parts['word/styles.xml'])
    by_id = {s.get(q('styleId')):s for s in old.findall('w:style',NS)}
    default_ids = {s.get(q('type')):sid for sid,s in by_id.items() if s.get(q('default'))=='1'}
    default_p = children(old.find('w:docDefaults/w:pPrDefault/w:pPr',NS))
    default_r = children(old.find('w:docDefaults/w:rPrDefault/w:rPr',NS))
    def chain(sid,seen=None):
        seen = set() if seen is None else seen
        if sid not in by_id:return []
        if sid in seen:raise ValueError(f'Cyclic style inheritance: {sid}')
        seen.add(sid);s=by_id[sid]
        return chain(value(s.find('w:basedOn',NS)),seen)+[s]
    def effective(p):
        sid=value(p.find('w:pPr/w:pStyle',NS),default_ids.get('paragraph'))
        pc,rc=deepcopy(default_p),deepcopy(default_r)
        for s in chain(sid):
            pc=merge(pc,children(s.find('w:pPr',NS)))
            rc=merge(rc,children(s.find('w:rPr',NS)),True)
        pc=merge(pc,children(p.find('w:pPr',NS)))
        runs=[]
        for r in p.findall('.//w:r',NS):
            rp=deepcopy(rc)
            for s in chain(value(r.find('w:rPr/w:rStyle',NS))):
                rp=merge(rp,children(s.find('w:rPr',NS)),True)
            rp=merge(rp,children(r.find('w:rPr',NS)))
            runs.append((r,rp))
        return pc,rc,runs
    story_names=[n for n in parts if re.fullmatch(r'word/(document|header[0-9]+|footer[0-9]+)\.xml',n)]
    roots={name:parse_xml(parts[name]) for name in story_names}
    def target(ref):
        name=ref.get('part','word/document.xml');scope=ref.get('scope','body')
        if name not in roots:raise ValueError(f'Unknown style sample part {name}')
        r=roots[name]
        if name=='word/document.xml':
            ps=r.find('w:body',NS).findall('w:p',NS) if scope=='body' else r.findall('.//w:tbl//w:p',NS)
        else:ps=r.findall('.//w:p',NS)
        return name,ps[ref['paragraph']]
    definitions=config.get('styles',[])
    if not definitions:raise ValueError('Named style definitions are required')
    ids=[d['id'] for d in definitions];names=[d['name'] for d in definitions]
    if len(set(ids))!=len(ids) or len(set(names))!=len(names):raise ValueError('Style ids and display names must be unique')
    if set(ids)&set(by_id):raise ValueError('New styles must not reuse source style ids')
    default=config['default_style']
    if default not in ids:raise ValueError('default_style must be defined')
    assigned={}
    for a in config.get('assignments',[]):
        if a['style'] not in ids:raise ValueError('Assignment references undefined style')
        for index in a['paragraphs']:
            name,p=target({**a,'paragraph':index})
            key=(name,p)
            if key in assigned:raise ValueError('Duplicate named-style assignment')
            assigned[key]=a['style']
    # Hold strong references to lxml paragraph proxies for the assignment map.
    all_ps={name:list(r.findall('.//w:p',NS)) for name,r in roots.items()}
    snapshots={(name,p):effective(p) for name,ps in all_ps.items() for p in ps}
    baselines={}
    for d in definitions:
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',d['id']):raise ValueError('Style id must be stable ASCII')
        name,p=target(d['sample'])
        pc,rc,runs=effective(p)
        pc={k:v for k,v in pc.items() if k not in ('sectPr','numPr','pPrChange')}
        run_index=d.get('sample_run')
        if run_index is None:
            chosen=next((rp for r,rp in runs if '{{' in ''.join(r.itertext())),None)
            if chosen is None:chosen=next((rp for r,rp in runs if ''.join(r.itertext()).strip()),rc)
        else:chosen=runs[run_index][1]
        pc=override(pc,d.get('paragraph_properties',{}))
        rc=override(chosen,d.get('run_properties',{}))
        baselines[d['id']]=(pc,rc)
    fresh=ET.Element(q('styles'),nsmap=old.nsmap)
    # Empty defaults; every paragraph explicitly uses a new template style.
    defaults=ET.SubElement(fresh,q('docDefaults'))
    ET.SubElement(ET.SubElement(defaults,q('rPrDefault')),q('rPr'))
    ET.SubElement(ET.SubElement(defaults,q('pPrDefault')),q('pPr'))
    latent=ET.SubElement(fresh,q('latentStyles'))
    for k,v in {'defLockedState':'0','defUIPriority':'99','defSemiHidden':'1','defUnhideWhenUsed':'0','defQFormat':'0','count':'0'}.items():latent.set(q(k),v)
    catalog=[]
    for priority,d in enumerate(definitions,1):
        sid=d['id'];pc,rc=baselines[sid]
        style=ET.SubElement(fresh,q('style'),{q('type'):'paragraph',q('customStyle'):'1',q('styleId'):sid})
        if sid==default:style.set(q('default'),'1')
        ET.SubElement(style,q('name'),{q('val'):d['name']})
        ET.SubElement(style,q('next'),{q('val'):d.get('next',default)})
        ET.SubElement(style,q('uiPriority'),{q('val'):str(priority)})
        ET.SubElement(style,q('qFormat'))
        style.append(properties('pPr',pc));style.append(properties('rPr',rc))
        catalog.append({'id':sid,'name':d['name'],'gallery_visible':True,'sample':d['sample'],'applied_paragraph_count':0,'pPr_xml':ET.tostring(style.find('w:pPr',NS),encoding='unicode'),'rPr_xml':ET.tostring(style.find('w:rPr',NS),encoding='unicode')})
    # New table styles flatten each used source table style and its conditional formatting.
    table_styles={}
    for r in roots.values():
        for tbl in r.findall('.//w:tbl',NS):
            sid=value(tbl.find('w:tblPr/w:tblStyle',NS),default_ids.get('table'))
            if sid not in table_styles:
                new_id='PaperTable'+str(len(table_styles)+1);table_styles[sid]=new_id
                new=ET.SubElement(fresh,q('style'),{q('type'):'table',q('customStyle'):'1',q('styleId'):new_id})
                ET.SubElement(new,q('name'),{q('val'):'论文表格' if len(table_styles)==1 else '论文表格'+str(len(table_styles))})
                ET.SubElement(new,q('uiPriority'),{q('val'):str(len(definitions)+len(table_styles))})
                ET.SubElement(new,q('qFormat'))
                flat={};conditions={}
                for s in chain(sid):
                    for c in s:
                        key=ET.QName(c).localname
                        if key in ('pPr','rPr','tblPr','trPr','tcPr'):
                            flat[key]=merge(flat.get(key,{}),children(c),key=='rPr')
                        elif key=='tblStylePr':conditions[c.get(q('type'))]=deepcopy(c)
                for key in ('pPr','rPr','tblPr','trPr','tcPr'):
                    if key in flat:
                        prop=properties(key,flat[key]);
                        for n in prop.findall('w:tblStyle',NS):prop.remove(n)
                        new.append(prop)
                for c in conditions.values():new.append(c)
            pr=tbl.find('w:tblPr',NS)
            if pr is None:pr=ET.Element(q('tblPr'));tbl.insert(0,pr)
            ref=pr.find('w:tblStyle',NS)
            if ref is None:ref=ET.Element(q('tblStyle'));pr.insert(0,ref)
            ref.set(q('val'),table_styles[sid])
    counts={d['id']:0 for d in definitions}
    for name,ps in all_ps.items():
        for p in ps:
            key=(name,p);sid=assigned.get(key,default);pc,rc,runs=snapshots[key]
            bp,br=baselines[sid]
            # Named styles determine outline semantics; stale heading levels must not override them.
            pc.pop('outlineLvl',None)
            pc=prune(pc,bp)
            # Paragraph mark run defaults must not retain stale source heading typography.
            oldmark=p.find('w:pPr/w:rPr',NS)
            mark=prune(merge(rc,children(oldmark)),br)
            if mark:pc['rPr']=properties('rPr',mark)
            newp=properties('pPr',pc);ref=ET.Element(q('pStyle'));ref.set(q('val'),sid);newp.insert(0,ref)
            oldp=p.find('w:pPr',NS)
            if oldp is not None:p.remove(oldp)
            p.insert(0,newp)
            for r,rp in runs:
                oldr=r.find('w:rPr',NS)
                if oldr is not None:r.remove(oldr)
                rp=prune(rp,br)
                if rp:r.insert(0,properties('rPr',rp))
            counts[sid]+=1
    result=dict(parts);result['word/styles.xml']=xml(fresh)
    for name,r in roots.items():result[name]=xml(r)
    # No old style references may survive anywhere, including numbering parts.
    for name,data in list(result.items()):
        if not name.endswith('.xml') or name=='word/styles.xml':continue
        r=ET.fromstring(data)
        refs=r.xpath('//*[local-name()="pStyle" or local-name()="rStyle" or local-name()="tblStyle" or local-name()="styleLink" or local-name()="numStyleLink"]')
        for ref in refs:
            if ref.get(q('val')) in by_id:
                raise ValueError(f'Unhandled old style reference {ref.get(q("val"))} in {name}')
    for row in catalog:row['applied_paragraph_count']=counts[row['id']]
    if any(c['applied_paragraph_count']==0 for c in catalog):raise ValueError('Every new paragraph style must be applied at least once')
    return result,{'mode':'replace_all','removed_style_count':len(by_id),'removed_style_ids':list(by_id),'new_paragraph_styles':catalog,'new_table_styles':table_styles,'latent_builtin_gallery_hidden':True}
