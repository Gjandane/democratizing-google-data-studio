"""Apply RFC 6902 patches to copies, constrained by item identity and collision necessity."""
from copy import deepcopy
import jsonpatch
from dss.spec.layout import box


class PatchError(ValueError):
    pass


GROUPS = ('components', 'decorations')


def items(document):
    return {item['id']: item for page in document['pages'] for group in GROUPS for item in page[group]}


def pages(document):
    """Item id -> its page position; boxes and collisions never cross pages."""
    return {item['id']: p for p, page in enumerate(document['pages']) for group in GROUPS for item in page[group]}


def overlaps(a, b):
    return a['x'] < b['x']+b['w'] and b['x'] < a['x']+a['w'] and a['y'] < b['y']+b['h'] and b['y'] < a['y']+a['h']


def item_box(document, item, page=0):
    from dss.spec.models import Canvas, Grid, Cell
    return box(Canvas.model_validate(document['canvas']), Grid.model_validate(document['grid']),
               Cell.model_validate(item['grid']), height=document['pages'][page]['height'])


def neighbours(document, targets):
    """Direct grid neighbours only; no unrelated spec or data rows enter working memory."""
    all_items, page_of = items(document), pages(document)
    target_boxes = [(page_of[cid], item_box(document, all_items[cid], page_of[cid])) for cid in targets]
    result = set(targets)
    for cid, item in all_items.items():
        b = item_box(document, item, page_of[cid])
        for page, a in target_boxes:
            if page != page_of[cid]:
                continue
            horizontal_gap = max(a['x']-b['x']-b['w'], b['x']-a['x']-a['w'], 0)
            vertical_gap = max(a['y']-b['y']-b['h'], b['y']-a['y']-a['h'], 0)
            if (horizontal_gap <= 17 and vertical_gap == 0) or (vertical_gap <= 17 and horizontal_gap == 0):
                result.add(cid)
    return result


def pointer(document, path):
    # Canonical paths prevent index-shift and JSON pointer aliases bypassing scope checks.
    tokens = path.split('/')
    if len(tokens) < 5 or tokens[0:2] != ['', 'pages'] or tokens[3] not in GROUPS:
        raise PatchError('Patches must address a component or decoration')
    page, index = tokens[2], tokens[4]
    if any(not t.isascii() or not t.isdigit() or str(int(t)) != t for t in (page, index)):
        raise PatchError('An existing item index is required')
    try:
        item = document['pages'][int(page)][tokens[3]][int(index)]
    except (IndexError, KeyError, TypeError):
        raise PatchError('Patch item does not exist') from None
    return item['id'], tokens[3], tokens[5:]


def apply_scoped(document, operations, target):
    from dss.spec.models import SYNTHETIC_LABEL_ID
    if target == SYNTHETIC_LABEL_ID:
        raise PatchError('Synthetic sample data label is read-only')
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
            if cid == SYNTHETIC_LABEL_ID:
                raise PatchError('Synthetic sample data label is read-only')
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
            if len(current) != sum(len(page[g]) for page in candidate['pages'] for g in GROUPS):
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
    components = {i['id'] for page in document['pages'] for i in page['components']}
    before_pages, after_pages = pages(document), pages(candidate)
    if any(before_pages[cid] != page for cid, page in after_pages.items()):
        raise PatchError('Items cannot change page')
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
        found = {cid for cid in pending if any(before_pages[moved] == before_pages[cid] and overlaps(
            item_box(candidate, final[moved], before_pages[moved]), item_box(document, original[cid], before_pages[cid]))
            for moved in justified)}
        if not found:
            raise PatchError('Patch touches an unrelated item')
        pending -= found
        justified |= found
    return candidate
