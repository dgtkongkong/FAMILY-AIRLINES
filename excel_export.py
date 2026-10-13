"""Small dependency-free XLSX writer for the application's read-only exports."""
import datetime as dt
import io, zipfile
from xml.sax.saxutils import escape

def col(n):
    text=''
    while n:
        n,r=divmod(n-1,26);text=chr(65+r)+text
    return text

def workbook(sheets):
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
        overrides=''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(sheets)+1))
        z.writestr('[Content_Types].xml',f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{overrides}</Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_,_) in enumerate(sheets,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml',f'<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font><font><b/><sz val="11"/><color rgb="FF315D50"/><name val="Microsoft YaHei"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFDCECE5"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="4"><xf fontId="0" fillId="0" borderId="0" xfId="0"/><xf fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1"/></xf><xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for i,(name,headers,records) in enumerate(sheets,1):
            rowxml=[]
            for r,values in enumerate([headers]+records,1):
                cells=[]
                for j,value in enumerate(values,1):
                    address=f'{col(j)}{r}';style=1 if r==1 else 0
                    if isinstance(value,dt.date):
                        value=(value-dt.date(1899,12,30)).days;style=2
                    elif isinstance(value,float):style=3
                    if isinstance(value,(int,float)):
                        cells.append(f'<c r="{address}" s="{style}"><v>{value}</v></c>')
                    else:
                        value=''.join(ch for ch in str(value or '') if ord(ch)>=32 or ch in '\n\t')[:32767]
                        cells.append(f'<c r="{address}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>')
                rowxml.append(f'<row r="{r}"'+(' ht="32" customHeight="1"' if r==1 else '')+'>'+''.join(cells)+'</row>')
            end=f'{col(len(headers))}{len(records)+1}'
            z.writestr(f'xl/worksheets/sheet{i}.xml',f'<worksheet xmlns="{ns}"><dimension ref="A1:{end}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="{len(headers)}" width="23" customWidth="1"/></cols><sheetData>'+''.join(rowxml)+f'</sheetData><autoFilter ref="A1:{end}"/></worksheet>')
    return data.getvalue()
