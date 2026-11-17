"""Run from cirv-app. Removes GRFC period from exports without editing the template."""
from pathlib import Path
import ast
import re
import shutil
from datetime import datetime

HELPER = r'''
def _remove_grfc_period_from_export(payload):
    """Physically delete All Data column N, adjusting workbook references."""
    from openpyxl.formula.tokenizer import Tokenizer
    from openpyxl.utils.cell import column_index_from_string
    import copy

    with zipfile.ZipFile(BytesIO(payload)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    book = ET.fromstring(parts['xl/workbook.xml'])
    rels = ET.fromstring(parts['xl/_rels/workbook.xml.rels'])
    sheets = list(book.find(f'{{{NS}}}sheets'))
    targets = {r.get('Id'): r.get('Target') for r in rels}

    def resolve(base, target):
        return target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(base), target))

    paths = {s.get('name'): resolve('xl/workbook.xml', targets[s.get(f'{{{REL}}}id')]) for s in sheets}
    main_path = paths[SHEET]
    trees = {name: ET.fromstring(parts[path]) for name, path in paths.items()}
    removed = 14

    def endpoint(value):
        match = re.fullmatch(r'(\$?)([A-Z]{1,3})(\$?\d+)?', value)
        if not match:
            return None
        return match, column_index_from_string(match.group(2))

    def move_ref(value, allow_deleted=False):
        """A1 and column ranges; ranges shrink, single deleted refs fail closed."""
        ends = value.split(':')
        parsed = [endpoint(e) for e in ends]
        if not all(parsed) or len(ends) > 2:
            return value
        numbers = [p[1] for p in parsed]
        if len(numbers) == 1 and numbers[0] == removed:
            if allow_deleted:
                return None
            raise ValueError('A formula still references the deleted GRFC period cell: ' + value)
        if len(numbers) == 2 and numbers[0] == numbers[1] == removed:
            if allow_deleted:
                return None
            raise ValueError('A formula references only the deleted GRFC period column: ' + value)
        result = []
        for index, (match, number) in enumerate(parsed):
            if number > removed:
                number -= 1
            elif number == removed and len(numbers) == 2:
                number = removed if index == 0 else removed - 1
            result.append(match.group(1) + get_column_letter(number) + (match.group(3) or ''))
        return ':'.join(result)

    def formula(value, local_sheet=None):
        if not value:
            return value
        has_equal = value.startswith('=')
        tokenizer = Tokenizer(value if has_equal else '=' + value)
        for token in tokenizer.items:
            if token.type != 'OPERAND' or token.subtype != 'RANGE':
                continue
            text = token.value
            if '!' in text:
                qualifier, reference = text.rsplit('!', 1)
                sheet_name = qualifier.strip("'").replace("''", "'")
                if sheet_name != SHEET:
                    continue
                token.value = qualifier + '!' + move_ref(reference)
            elif local_sheet == SHEET:
                token.value = move_ref(text)
        output = ''.join(token.value for token in tokenizer.items)
        return ('=' if has_equal else '') + output

    # Formulas across all worksheets, including shared/array formula ranges.
    for name, tree in trees.items():
        for node in tree.iter():
            tag = ET.QName(node).localname
            if tag in ('f', 'formula', 'formula1', 'formula2') and node.text:
                node.text = formula(node.text, name)
        if name != SHEET:
            continue
        sd = tree.find(f'{{{NS}}}sheetData')
        for row in sd:
            row.attrib.pop('spans', None)
            for cell in list(row):
                coordinate = cell.get('r')
                if not coordinate:
                    continue
                updated = move_ref(coordinate, True)
                if updated is None:
                    row.remove(cell)
                else:
                    cell.set('r', updated)
        # All local cell/range metadata: merges, filters, validation, conditional
        # formatting, selections, dimensions, array/shared formula ranges, links.
        for node in list(tree.iter()):
            if ET.QName(node).localname == 'c':
                continue
            for attribute in ('ref', 'sqref', 'activeCell', 'topLeftCell'):
                if attribute not in node.attrib:
                    continue
                updated = [move_ref(v, True) for v in node.get(attribute).split()]
                updated = [v for v in updated if v]
                if updated:
                    node.set(attribute, ' '.join(updated))
                elif node.getparent() is not None:
                    node.getparent().remove(node)
            if ET.QName(node).localname == 'sqref' and node.text:
                node.text = ' '.join(v for v in (move_ref(x, True) for x in node.text.split()) if v)
        cols = tree.find(f'{{{NS}}}cols')
        if cols is not None:
            for col in list(cols):
                lo, hi = int(col.get('min')), int(col.get('max'))
                if lo == hi == removed:
                    cols.remove(col)
                    continue
                if lo > removed:
                    lo -= 1
                if hi >= removed:
                    hi -= 1
                col.set('min', str(lo)); col.set('max', str(hi))
        for parent in tree.iter():
            if ET.QName(parent).localname in ('mergeCells', 'dataValidations'):
                parent.set('count', str(len(parent)))

    # Defined names and print areas, respecting sheet-local names.
    for node in book.findall(f'.//{{{NS}}}definedName'):
        local = node.get('localSheetId')
        local_name = sheets[int(local)].get('name') if local is not None else None
        node.text = formula(node.text, local_name)

    # Table ranges and structured table columns belonging to All Data.
    rel_path = posixpath.join(posixpath.dirname(main_path), '_rels', posixpath.basename(main_path) + '.rels')
    related = ET.fromstring(parts[rel_path]) if rel_path in parts else []
    for relation in related:
        target = resolve(main_path, relation.get('Target'))
        kind = relation.get('Type', '').rsplit('/', 1)[-1]
        if target not in parts:
            continue
        if kind == 'table':
            table = ET.fromstring(parts[target]); old_range = table.get('ref')
            start = endpoint(old_range.split(':')[0])[1]
            columns = table.find(f'{{{NS}}}tableColumns')
            if columns is not None and start <= removed < start + len(columns):
                deleted_column = list(columns)[removed-start]
                label = deleted_column.get('name', '')
                # Do not silently leave broken structured references.
                if any('[' + label + ']' in (f.text or '') for t in trees.values() for f in t.findall(f'.//{{{NS}}}f')):
                    raise ValueError('A structured formula references the deleted period column.')
                columns.remove(deleted_column); columns.set('count', str(len(columns)))
            for node in table.iter():
                if node.get('ref'):
                    node.set('ref', move_ref(node.get('ref')))
                if ET.QName(node).localname.endswith('Formula') and node.text:
                    node.text = formula(node.text, SHEET)
            parts[target] = ET.tostring(table, encoding='utf-8', xml_declaration=True)
        elif kind == 'drawing':
            drawing = ET.fromstring(parts[target])
            for node in drawing.iter():
                if ET.QName(node).localname == 'col' and node.text and int(node.text) >= removed:
                    node.text = str(int(node.text)-1)
            parts[target] = ET.tostring(drawing, encoding='utf-8', xml_declaration=True)
        elif kind in ('comments', 'threadedComment'):
            comments = ET.fromstring(parts[target])
            for node in list(comments.iter()):
                if node.get('ref'):
                    updated = move_ref(node.get('ref'), True)
                    if updated:node.set('ref', updated)
                    elif node.getparent() is not None:node.getparent().remove(node)
            parts[target] = ET.tostring(comments, encoding='utf-8', xml_declaration=True)

    # Chart series formulas refer to All Data using sheet-qualified addresses.
    for name in list(parts):
        if name.startswith('xl/charts/') and name.endswith('.xml'):
            tree = ET.fromstring(parts[name])
            for node in tree.iter():
                if ET.QName(node).localname == 'f' and node.text:
                    node.text = formula(node.text)
            parts[name] = ET.tostring(tree, encoding='utf-8', xml_declaration=True)

    for name, tree in trees.items():
        parts[paths[name]] = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
    # Drop the old calculation chain, which contains pre-deletion coordinates.
    parts.pop('xl/calcChain.xml', None)
    for node in list(rels):
        if node.get('Type', '').endswith('/calcChain'):
            rels.remove(node)
    types = ET.fromstring(parts['[Content_Types].xml'])
    for node in list(types):
        if node.get('PartName') == '/xl/calcChain.xml':types.remove(node)
    parts['xl/workbook.xml'] = ET.tostring(book, encoding='utf-8', xml_declaration=True)
    parts['xl/_rels/workbook.xml.rels'] = ET.tostring(rels, encoding='utf-8', xml_declaration=True)
    parts['[Content_Types].xml'] = ET.tostring(types, encoding='utf-8', xml_declaration=True)
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():archive.writestr(name, content)
    return output.getvalue()

'''


def main():
    path=Path('cirv_all_data_app.py')
    original=path.read_text(encoding='utf-8-sig')
    tree=ast.parse(original)
    export=next((n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='export_xlsx'),None)
    if export is None:raise RuntimeError('export_xlsx() not found. Nothing changed.')
    updated=original
    if '_remove_grfc_period_from_export' not in original:
        lines=original.splitlines(keepends=True)
        start=sum(len(l) for l in lines[:export.lineno-1])
        updated=original[:start]+HELPER+original[start:]
    tree=ast.parse(updated)
    export=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='export_xlsx')
    returns=[n for n in ast.walk(export) if isinstance(n,ast.Return)]
    if len(returns)!=1:raise RuntimeError('Unexpected export return structure. Nothing changed.')
    ret=returns[0]
    if ast.unparse(ret.value)=='out.getvalue()':
        lines=updated.splitlines(keepends=True)
        start=sum(len(l) for l in lines[:ret.lineno-1])+ret.col_offset
        end=sum(len(l) for l in lines[:ret.end_lineno-1])+ret.end_col_offset
        updated=updated[:start]+'return _remove_grfc_period_from_export(out.getvalue())'+updated[end:]
    elif '_remove_grfc_period_from_export' not in ast.unparse(ret.value):
        raise RuntimeError('Unexpected export return expression. Nothing changed.')
    # Remove from web/CSV without changing internal calculation indices.
    updated,count=re.subn(r'^VISIBLE\s*=.*$', 'VISIBLE=[c for c in range(1,29) if c not in (3,9,14)]',updated,flags=re.M)
    if count!=1:raise RuntimeError('VISIBLE configuration not found. Nothing changed.')
    updated='\n'.join(line for line in updated.splitlines() if not ('st.info(' in line and 'GRFC time period' in line))+'\n'
    updated=updated.replace('GRFC period remains blank when collector does not supply it.', 'GRFC time-period column removed from exported All Data.')
    compile(updated,str(path),'exec')
    # Dry-run the exact export transformation on the reference workbook BEFORE modifying app code.
    ns={'__file__':str(path.resolve()),'__name__':'cirv_patch_check'}
    safe=ast.parse(updated)
    safe.body=[n for n in safe.body if not isinstance(n,ast.If)]
    exec(compile(safe,str(path),'exec'),ns)
    ref=ns['reference'](Path.cwd())
    payload=ns['_remove_grfc_period_from_export'](ref.read_bytes())
    from openpyxl import load_workbook
    from io import BytesIO
    before=load_workbook(ref,data_only=True)
    after=load_workbook(BytesIO(payload),data_only=True)
    name=ns['SHEET']
    assert after[name]['N3'].value==before[name]['O3'].value,'Column shift check failed'
    assert after[name]['AA5'].value==before[name]['AB5'].value,'CIRV cached value changed'
    formulas=load_workbook(BytesIO(payload),data_only=False)
    assert "!AA:AA" in formulas['CIRV Scores']['B2'].value,'Cross-sheet CIRV reference not shifted'
    backup=path.with_name(path.name+'.before_delete_grfc_period_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.bak')
    shutil.copy2(path,backup)
    path.write_text(updated,encoding='utf-8')
    print('SUCCESS: GRFC period physically deleted from exported All Data; app/CSV exclude it.')
    print('Original template and app calculation indices unchanged. Backup:',backup.name)

if __name__=='__main__':main()
