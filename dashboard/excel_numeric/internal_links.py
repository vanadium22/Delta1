"""Add native internal navigation omitted by the Artifact authoring API.

Only navigation links are added; values, formulas, styles and data remain from
the builder. Internal locations need no external relationship or macro.
"""
import json
from pathlib import Path
import sys
import zipfile
import xml.etree.ElementTree as ET

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE='http://schemas.openxmlformats.org/package/2006/relationships'

def add_links(path,links):
    path=Path(path)
    with zipfile.ZipFile(path) as source:
        members={i.filename:(i,source.read(i.filename)) for i in source.infolist()}
    book=ET.fromstring(members['xl/workbook.xml'][1])
    rels={r.attrib['Id']:r.attrib['Target'].lstrip('/') for r in ET.fromstring(members['xl/_rels/workbook.xml.rels'][1])}
    for sheet in book.find('{'+NS+'}sheets'):
        chosen=[v for v in links if v['sheet']==sheet.attrib['name']]
        if not chosen:continue
        target=rels[sheet.attrib['{'+REL+'}id']]
        if not target.startswith('xl/'):target='xl/'+target
        info,data=members[target];root=ET.fromstring(data)
        navigation=ET.Element('{'+NS+'}hyperlinks')
        for link in chosen:ET.SubElement(navigation,'{'+NS+'}hyperlink',ref=link['cell'],location="'"+link['target'].replace("'","''")+"'!A1",display=link['label'])
        # ECMA-376 worksheet order: after dataValidations, before print/drawing.
        later={'printOptions','pageMargins','pageSetup','headerFooter','rowBreaks','colBreaks','customProperties','cellWatches','ignoredErrors','smartTags','drawing','legacyDrawing','legacyDrawingHF','picture','oleObjects','controls','webPublishItems','tableParts','extLst'}
        index=next((i for i,e in enumerate(root) if e.tag.rsplit('}',1)[-1] in later),len(root))
        root.insert(index,navigation);members[target]=(info,ET.tostring(root,encoding='utf-8',xml_declaration=True))
    temporary=path.with_suffix(path.suffix+'.links.tmp')
    with zipfile.ZipFile(temporary,'w') as out:
        for info,data in members.values():out.writestr(info,data)
    temporary.replace(path)

if __name__=='__main__':add_links(sys.argv[1],json.loads(Path(sys.argv[2]).read_text(encoding='utf8')))
