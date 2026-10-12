"""Render the final DOCX with refreshed indexes, without rewriting its styles.

Run with /usr/bin/python3 (LibreOffice UNO): render_pdf.py final.docx output_dir
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import re

import uno
from com.sun.star.beans import PropertyValue


def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


def render(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    pipe = "paper_pdf_" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="paper-pdf-") as profile:
        process = subprocess.Popen(["libreoffice", "-env:UserInstallation=" + Path(profile).as_uri(),
            "--headless", "--norestore", "--nodefault", "--nofirststartwizard",
            "--accept=pipe,name=" + pipe + ";urp;StarOffice.ComponentContext"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        doc = desktop = None
        try:
            local = uno.getComponentContext()
            resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
            deadline = time.monotonic() + 40
            while True:
                try:
                    context = resolver.resolve("uno:pipe,name=" + pipe + ";urp;StarOffice.ComponentContext")
                    break
                except Exception:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("LibreOffice did not start")
                    time.sleep(.2)
            desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
            doc = desktop.loadComponentFromURL(source.as_uri(), "_blank", 0,
                (prop("Hidden", True), prop("UpdateDocMode", 3),
                 prop("MacroExecutionMode", uno.getConstantByName("com.sun.star.document.MacroExecMode.NEVER_EXECUTE"))))
            if doc is None:
                raise RuntimeError("Unable to load DOCX")
            indexes = doc.getDocumentIndexes()
            for _ in range(2):
                doc.getTextFields().refresh()
                for i in range(indexes.getCount()):
                    indexes.getByIndex(i).update()
                doc.refresh()
            pdf = output / (source.stem + ".pdf")
            doc.storeToURL(pdf.as_uri(), (prop("FilterName", "writer_pdf_Export"), prop("Overwrite", True)))
            extracted = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                                       capture_output=True, text=True, check=True, timeout=30).stdout
            pages = extracted.split("\f")
            if not pages[-1].strip():
                pages.pop()
            image_listing = subprocess.run(["pdfimages", "-list", str(pdf)],
                                           capture_output=True, text=True, check=True, timeout=30).stdout
            image_pages = {int(line.split()[0]) for line in image_listing.splitlines()[2:]
                           if len(line.split()) > 2 and line.split()[0].isdigit()}
            blank_pages = [i + 1 for i, page in enumerate(pages)
                           if not re.sub(r"[\s\dIVXLCDMivxlcdm]", "", page) and i + 1 not in image_pages]
            if blank_pages:
                raise ValueError("成稿存在空白页：" + str(blank_pages))
            page_numbers = {}
            fields = doc.getTextFields().createEnumeration()
            while fields.hasMoreElements():
                field = fields.nextElement()
                try:
                    name = field.getPropertyValue("SourceName")
                    if name.startswith("PaperHeading"):
                        page_numbers[name] = field.getPresentation(False)
                except Exception:
                    continue
            (output / "page-numbers.json").write_text(json.dumps(page_numbers, ensure_ascii=False, indent=2))
            if hashlib.sha256(source.read_bytes()).hexdigest() != before:
                raise RuntimeError("Source DOCX unexpectedly changed")
            report = {"source": str(source), "source_sha256": before, "pdf": str(pdf),
                      "engine": "LibreOffice UNO", "indexes_refreshed": indexes.getCount(),
                      "pages": len(pages), "blank_pages": blank_pages,
                      "docx_unchanged": True}
            (output / "render-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False))
        finally:
            if doc is not None:
                doc.close(True)
            if desktop is not None:
                desktop.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args()
    render(args.source, args.output)
