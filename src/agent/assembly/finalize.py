"""Populate directory page caches from an actual local layout, preserving styles."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from .engine import package, parse, xml, archive_bytes, NS, W
from .quality import check_content


def apply_page_cache(parts, cache):
    parts=dict(parts)
    document=parse(parts['word/document.xml'])
    fields=document.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="PaperContents"]]//w:fldSimple',namespaces=NS)
    if not fields:raise ValueError('No generated directory found')
    for field in fields:
        name=field.get('{'+W+'}instr').split()[1]
        value=cache.get(name)
        if not isinstance(value,str) or not re.fullmatch(r'[0-9IVXLCDMivxlcdm]+',value.strip()):
            raise ValueError('目录缺少实际页码：'+name+' '+repr(value))
        field.find('w:r/w:t',NS).text=value.strip()
        field.attrib.pop('{'+W+'}dirty',None)
    parts['word/document.xml']=xml(document)
    return parts, len(fields)


def finalize(source, page_map, output):
    source, output = Path(source), Path(output)
    original=package(source)
    parts, count=apply_page_cache(original,json.loads(Path(page_map).read_text()))
    document=parse(parts['word/document.xml'])
    report=check_content(document,parse(parts['word/styles.xml']))
    report.update(toc_entries=count,toc_page_cache_complete=True,model_api_calls=0,
        source_sha256=sha256(source.read_bytes()).hexdigest(),page_map=str(Path(page_map).resolve()),
        styles_preserved=all(parts[k]==v for k,v in original.items() if k!='word/document.xml'))
    data=archive_bytes(parts);output.write_bytes(data)
    report['output_sha256']=sha256(data).hexdigest()
    output.with_suffix('.finalization.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source');parser.add_argument('page_map');parser.add_argument('output')
    args=parser.parse_args();print(json.dumps(finalize(args.source,args.page_map,args.output),ensure_ascii=False))
