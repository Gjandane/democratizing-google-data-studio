"""Apply RFC 6902 patches to copies, constrained by item identity and collision necessity."""
from copy import deepcopy
import jsonpatch
from dss.spec.layout import box


class PatchError(ValueError):
    pass


def items(document):
    return {item['id']: item for group in ('components', 'decorations') for item in document['pages'][0][group]}


def overlaps(a, b):
    return a['x'] < b['x']+b['w'] and b['x'] < a['x']+a['w'] and a['y'] < b['y']+b['h'] and b['y'] < a['y']+a['h']


def item_box(document, item):
    from dss.spec.models import Canvas, Grid, Cell
    return box(Canvas.model_validate(document['canvas']), Grid.model_validate(document['grid']),
               Cell.model_validate(item['grid']), height=document['pages'][0]['height'])


def neighbours(document, targets):
    """Direct grid neighbours only; no unrelated spec or data rows enter working memory."""
    all_items = items(document)
    target_boxes = [item_box(document, all_items[cid]) for cid in targets]
    result = set(targets)
    for cid, item in all_items.items():
        b = item_box(document, item)
        for a in target_boxes:
            horizontal_gap = max(a['x']-b['x']-b['w'], b['x']-a['x']-a['w'], 0)
            vertical_gap = max(a['y']-b['y']-b['h'], b['y']-a['y']-a['h'], 0)
            if (horizontal_gap <= 17 and vertical_gap == 0) or (vertical_gap <= 17 and horizontal_gap == 0):
                result.add(cid)
    return result


def pointer(document, path):
    # Canonical paths prevent index-shift and JSON pointer aliases bypassing scope checks.
    tokens = path.split('/')
    if len(tokens) < 5 or tokens[0:3] != ['', 'pages', '0'] or tokens[3] not in ('components', 'decorations'):
        raise PatchError('Patches must address a component or decoration')
    index = tokens[4]
    if not index.isascii() or not index.isdigit() or str(int(index)) != index:
        raise PatchError('An existing item index is required')
    try:
        item = document['pages'][0][tokens[3]][int(index)]
    except (IndexError, KeyError, TypeError):
        raise PatchError('Patch item does not exist') from None
    return item['id'], tokens[3], tokens[5:]


def apply_scoped(document, operations, target):
    original = items(document)
    if target not in original:
        raise PatchError('Comment item does not exist')
    candidate = deepcopy(document)
    touched = set()
    for op in operations:
        for key in ('path', 'from'):
            if key not in op:
                continue
            cid, group, suffix = pointer(candidate, op[key])
            touched.add(cid)
            if cid != target and (group != 'components' or not suffix or suffix[0] != 'grid'):
                raise PatchError('Only necessary neighbour position changes are allowed')
            if suffix and suffix[0] == 'id' and op['op'] != 'test':
                raise PatchError('Item identities cannot change')
            if not suffix and (key == 'from' or op['op'] in ('add', 'copy', 'move')):
                raise PatchError('Cannot insert or reorder spec items')
        try:
            candidate = jsonpatch.apply_patch(candidate, [op], in_place=False)
        except (jsonpatch.JsonPatchException, KeyError, IndexError, TypeError, ValueError):
            raise PatchError('Patch operation could not be applied') from None
        try:
            current = items(candidate)
            if len(current) != sum(len(candidate['pages'][0][g]) for g in ('components','decorations')):
                raise PatchError('Item identities must be unique')
            if not current.keys() <= original.keys() or (original.keys()-current.keys()) - {target}:
                raise PatchError('Item identities cannot change')
            # Replacing one root cannot impersonate another existing id.
            if op['op'] == 'replace' and len(op['path'].split('/')) == 5:
                if pointer(candidate, op['path'])[0] != cid:
                    raise PatchError('Item identities cannot change')
        except (KeyError, TypeError):
            raise PatchError('Patch must preserve item objects and identities') from None
    final = items(candidate)
    others = touched - {target}
    components = {i['id'] for i in document['pages'][0]['components']}
    for cid in others:
        before, after = deepcopy(original[cid]), deepcopy(final[cid])
        for key in ('col', 'row'):
            before['grid'].pop(key, None)
            after['grid'].pop(key, None)
        if before != after:
            raise PatchError('Neighbours may move but cannot be resized or restyled')
    # A moved neighbour is authorized only when the revised target, or a required
    # moved neighbour, would otherwise collide with its original box.
    justified = {target} & components & final.keys()
    pending = set(others)
    while pending:
        found = {cid for cid in pending if any(overlaps(item_box(candidate, final[moved]), item_box(document, original[cid])) for moved in justified)}
        if not found:
            raise PatchError('Patch touches an unrelated item')
        pending -= found
        justified |= found
    return candidate
