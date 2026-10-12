import json
import pytest
from lxml import etree as E
from agent.assembly.engine import NS, W, parse, xml, archive_bytes, package
from agent.assembly.quality import check_content, clean_and_check
from agent.assembly.finalize import finalize


def document(body):
    return parse(f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'.encode())


def styles():
    return parse(f'<w:styles xmlns:w="{W}"><w:style w:styleId="h1"><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style><w:style w:styleId="h2"><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style><w:style w:styleId="tocEntry"><w:pPr><w:tabs><w:tab w:val="right" w:pos="8390" w:leader="dot"/></w:tabs></w:pPr></w:style></w:styles>'.encode())


def p(value, style=None):
    return '<w:p>'+('<w:pPr><w:pStyle w:val="'+style+'"/></w:pPr>' if style else '')+'<w:r><w:t>'+value+'</w:t></w:r></w:p>'


def test_empty_heading_and_empty_section_rejected():
    with pytest.raises(ValueError,match='空标题'):
        check_content(document(p('', 'h1')),styles())
    with pytest.raises(ValueError,match='没有有效内容'):
        check_content(document(p('系统设计','h1')),styles())
    assert check_content(document(p('系统设计','h1')+p('用户模块','h2')+p('用户管理设计正文')),styles())['passed']


def test_optional_empty_sections_and_navigation_cleanup():
    doc=document(p('目录')+p('前 言','h1')+'<w:p><w:pPr><w:sectPr/></w:pPr></w:p>'+p('正文','h1')+p('实际内容')+p('附 录','h1')+p('','h2')+'<w:sectPr/>')
    report,removed=clean_and_check(doc,styles())
    assert report['removed_empty_template_sections']==['前 言','附 录']
    assert len(removed)==1
    assert report['toc_entries']==1
    assert len(doc.xpath('.//w:sectPr',namespaces=NS))==1
    assert doc.xpath('.//w:sdtContent//w:tab[@w:val="clear" and @w:pos="8390"]',namespaces=NS)
    assert not doc.xpath('.//w:sdtContent//w:tab[@w:leader="dot"]',namespaces=NS)
    assert check_content(doc,styles())['empty_headings']==0


def test_finalize_requires_all_real_pages_and_preserves_styles(tmp_path):
    doc=document(p('目录')+p('正文','h1')+p('实际内容'))
    clean_and_check(doc,styles())
    source=tmp_path/'source.docx'; output=tmp_path/'ready.docx';mapping=tmp_path/'pages.json'
    source.write_bytes(archive_bytes({'word/document.xml':xml(doc),'word/styles.xml':xml(styles())}))
    mapping.write_text('{}')
    with pytest.raises(ValueError,match='缺少实际页码'):finalize(source,mapping,output)
    field=doc.xpath('.//w:fldSimple',namespaces=NS)[0];name=field.get('{'+W+'}instr').split()[1]
    mapping.write_text(json.dumps({name:'7'}))
    report=finalize(source,mapping,output)
    assert report['toc_page_cache_complete']
    assert package(source)['word/styles.xml']==package(output)['word/styles.xml']
    assert parse(package(output)['word/document.xml']).xpath('.//w:fldSimple/w:r/w:t/text()',namespaces=NS)==['7']
