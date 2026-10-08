"""Office-engine evidence helper. Run with /usr/bin/python3 (system UNO).

Starts an isolated LibreOffice process, refreshes actual fields, writes a separate
DOCX and PDF, and records before/after field presentations. Never edits input.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import uno
from com.sun.star.beans import PropertyValue


def prop(name,value):
    p=PropertyValue(); p.Name=name; p.Value=value; return p


def snapshot(doc):
    fields=doc.getTextFields().createEnumeration(); values=[]
    while fields.hasMoreElements():
        f=fields.nextElement()
        values.append({'instruction':f.getPresentation(True),'display':f.getPresentation(False)})
    return values


def refresh(source,out,note_map=None):
    source=Path(source).resolve(); out=Path(out).resolve(); out.mkdir(parents=True,exist_ok=True)
    pipe='docx_refs_'+uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='docx-refs-lo-') as tmp:
        process=subprocess.Popen(['soffice','-env:UserInstallation='+Path(tmp).as_uri(),'--headless','--norestore','--nodefault','--nofirststartwizard','--accept=pipe,name='+pipe+';urp;StarOffice.ComponentContext'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        doc=None; desktop=None
        try:
            local=uno.getComponentContext()
            resolver=local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',local)
            deadline=time.monotonic()+40
            while True:
                try:
                    ctx=resolver.resolve('uno:pipe,name='+pipe+';urp;StarOffice.ComponentContext'); break
                except Exception:
                    if process.poll() is not None or time.monotonic()>deadline: raise RuntimeError('LibreOffice did not start')
                    time.sleep(.2)
            desktop=ctx.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',ctx)
            doc=desktop.loadComponentFromURL(source.as_uri(),'_blank',0,(prop('Hidden',True),prop('UpdateDocMode',3),prop('MacroExecutionMode',4)))
            if doc is None:raise RuntimeError('Unable to load document')
            bridged=[]
            if note_map:
                mapping=json.loads(Path(note_map).read_text())['converted_note_references']
                targets={'#'+row['instruction'].split()[1]:int(row['display'])-1 for row in mapping}
                candidates=[];paragraphs=doc.getText().createEnumeration()
                while paragraphs.hasMoreElements():
                    paragraph=paragraphs.nextElement()
                    if not paragraph.supportsService('com.sun.star.text.Paragraph'):continue
                    portions=paragraph.createEnumeration()
                    while portions.hasMoreElements():
                        portion=portions.nextElement()
                        try:url=portion.getPropertyValue('HyperLinkURL')
                        except Exception:continue
                        if url in targets:candidates.append((portion,url))
                for portion,url in candidates:
                    reference=doc.createInstance('com.sun.star.text.TextField.GetReference')
                    reference.ReferenceFieldSource=uno.getConstantByName('com.sun.star.text.ReferenceFieldSource.FOOTNOTE')
                    reference.ReferenceFieldPart=uno.getConstantByName('com.sun.star.text.ReferenceFieldPart.TEXT')
                    reference.SequenceNumber=doc.getFootnotes().getByIndex(targets[url]).ReferenceId
                    portion.getText().insertTextContent(portion,reference,True)
                    reference.getAnchor().CharEscapement=33
                    bridged.append({'target':url,'note_index':targets[url],'reference_id':reference.SequenceNumber})
                if len(bridged)!=len(mapping):raise RuntimeError('Not every render-only note link was bridged')
            before=snapshot(doc)
            for _ in range(2):
                doc.getTextFields().refresh(); doc.refresh()
            after=snapshot(doc)
            links=[]; paragraphs=doc.getText().createEnumeration()
            while paragraphs.hasMoreElements():
                paragraph=paragraphs.nextElement()
                if not paragraph.supportsService('com.sun.star.text.Paragraph'):continue
                portions=paragraph.createEnumeration()
                while portions.hasMoreElements():
                    portion=portions.nextElement()
                    try:
                        url=portion.getPropertyValue('HyperLinkURL')
                        if url:links.append({'text':portion.getString(),'url':url})
                    except Exception:pass
            bookmarks={name:doc.getBookmarks().getByName(name).getAnchor().getString() for name in doc.getBookmarks().getElementNames()}

            docx=out/(source.stem+'-updated.docx'); pdf=out/(source.stem+'.pdf')
            doc.storeAsURL(docx.as_uri(),(prop('FilterName','Office Open XML Text'),prop('Overwrite',True)))
            doc.storeToURL(pdf.as_uri(),(prop('FilterName','writer_pdf_Export'),prop('Overwrite',True),prop('FilterData',uno.Any('[]com.sun.star.beans.PropertyValue',(prop('ExportBookmarks',True),prop('ExportBookmarksToPDFDestination',True))))))
            result={'engine':'LibreOffice UNO','input':str(source),'docx':str(docx),'pdf':str(pdf),'before':before,'after':after,'hyperlinks':links,'bookmarks':bookmarks,'render_only_native_note_bridges':bridged,'scope':'Text fields refresh + layout; not full TOC reconstruction'}
            (out/'field-refresh.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'docx':str(docx),'pdf':str(pdf),'fields':len(after)},ensure_ascii=False))
        finally:
            if doc is not None:doc.close(True)
            if desktop is not None:desktop.terminate()
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('out');p.add_argument('--note-map');a=p.parse_args();refresh(a.source,a.out,a.note_map)
