"""Deterministic, aggregate-only prototype renderer and version-local query cache."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re

from dss.data.bigquery import quoted, table_uri
from dss.spec.layout import box
from dss.spec.validate import catalog


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError('Unsupported aggregate value')


def script_json(value):
    return json.dumps(value, default=json_value, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def dimensions(component):
    fields = list(component.dimensions)
    # Other chart types bind a date for filtering, not for their grouping axis.
    if component.type == 'time_series' and component.date_dimension:
        fields.insert(0, component.date_dimension)
    fields += [f for f in (component.breakdown, component.field) if f]
    return list(dict.fromkeys(fields))


def aggregate_sql(spec, component):
    if component.type in ('text', 'image', 'date_range'):
        return None
    dims = dimensions(component)
    known = {f.name: f for f in spec.datasource.fields}
    bound = dims + [m.field for m in component.metrics]
    if not set(bound) <= known.keys():
        raise ValueError('Unknown aggregate field')
    group = [f'ST_ASGEOJSON(ST_CENTROID({quoted(d)}))' if known[d].type.upper() in ('GEO', 'GEOGRAPHY')
             else quoted(d) for d in dims]
    select = [f'{expression} AS {quoted(d)}' if expression != quoted(d) else expression
              for d, expression in zip(dims, group)]
    for i, metric in enumerate(component.metrics):
        field = quoted(metric.field)
        expression = (f'COUNT(DISTINCT {field})' if metric.agg == 'count_distinct' else
                      f'{ {"none": "ANY_VALUE"}.get(metric.agg, metric.agg.upper())}({field})')
        select.append(f'{expression} AS {quoted("m" + str(i))}')
    if not select:
        return None
    sql = f'SELECT {", ".join(select)} FROM {quoted(table_uri(spec.datasource.table))}'
    if dims:
        sql += ' GROUP BY ' + ', '.join(group)
    # Absent sort: time series by date ascending, others by the first metric descending.
    sort = component.sort
    order = sort.field if sort else None
    aliases = {m.field: 'm' + str(i) for i, m in enumerate(component.metrics)}
    if order and order not in known:
        raise ValueError('Unknown sort field')
    if order and order not in dims and order not in aliases:
        # Valid specs can sort by a datasource field absent from the chart slots.
        agg = known[order].default_agg
        expression = (f'COUNT(DISTINCT {quoted(order)})' if agg == 'count_distinct' else
                      f'{"ANY_VALUE" if agg == "none" else agg.upper()}({quoted(order)})')
    else:
        order = aliases.get(order, order) if order else (dims[0] if component.type == 'time_series' and dims else 'm0' if component.metrics else dims[0])
        expression = quoted(order)
    direction = (sort.order if sort else 'asc' if component.type == 'time_series' else 'desc').upper()
    if direction not in ('ASC', 'DESC'):
        raise ValueError('Invalid sort direction')
    sql += f' ORDER BY {expression} {direction}'
    return sql + (' LIMIT 20' if component.type in ('table', 'pivot_table') else ' LIMIT 50')


def aggregate_data(spec, service, folder):
    """SQL hashes survive layout-only spec revisions inside a build version."""
    folder = Path(folder)
    path = folder / 'aggregate-cache.json'
    cache = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    queries = {}
    ids = {}
    for page in spec.pages:
        for item in page.components:
            sql = aggregate_sql(spec, item)
            if sql:
                key = sha256(sql.encode()).hexdigest()
                queries[key] = sql
                ids[item.id] = key
    missing = {key: sql for key, sql in queries.items() if key not in cache}
    def query(pair):
        key, sql = pair
        return key, service.aggregate(sql)
    with ThreadPoolExecutor(max_workers=8) as pool:
        cache.update(pool.map(query, missing.items()))
    folder.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(cache, default=json_value, allow_nan=False), encoding='utf-8')
    temporary.replace(path)
    return {cid: cache[key] for cid, key in ids.items()}


def image_url(path, folder):
    if not path or folder is None:
        return None
    root = Path(folder).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or target.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
        raise ValueError('Image must be a raster asset inside the version folder')
    if not target.is_file():
        raise ValueError('Image asset is missing')
    mime = 'jpeg' if target.suffix.lower() in ('.jpg', '.jpeg') else target.suffix[1:].lower()
    return f'data:image/{mime};base64,' + base64.b64encode(target.read_bytes()).decode()


def css_value(value):
    # User-authored style values cannot escape their declaration or style tag.
    return re.sub(r'[^\w\s#(),.%+\-]', '', str(value))


def table_option(item, rows, theme):
    """ECharts graphic table; the pivot uses row keys and the second dimension as columns."""
    dims = dimensions(item)
    metrics = [f'm{i}' for i in range(len(item.metrics))]
    headers = dims + [m.field for m in item.metrics]
    values = [[row.get(k) for k in dims + metrics] for row in rows]
    if item.type == 'pivot_table' and len(dims) >= 2:
        columns = list(dict.fromkeys(str(r.get(dims[1], '')) for r in rows))
        row_dims = [dims[0]] + dims[2:]
        keys = list(dict.fromkeys(tuple(str(r.get(d, '')) for d in row_dims) for r in rows))
        lookup = {(tuple(str(r.get(d, '')) for d in row_dims), str(r.get(dims[1], ''))): r for r in rows}
        headers = row_dims + [f'{col} / {m.field}' for col in columns for m in item.metrics]
        values = [list(key) + [lookup.get((key, col), {}).get(metric) for col in columns for metric in metrics] for key in keys]
    return headers, values


def chart_option(item, rows, theme, width):
    base = {'animation': False, 'color': theme.palette or [theme.accent],
            'textStyle': {'fontFamily': theme.font_family, 'color': theme.text},
            'aria': {'enabled': True, 'decal': {'show': True}},
            'tooltip': {'trigger': 'item', 'renderMode': 'richText'}}
    dims = dimensions(item)
    metrics = [f'm{i}' for i in range(len(item.metrics))]
    if item.type in ('table', 'pivot_table'):
        headers, values = table_option(item, rows, theme)
        cell_w = max(85, (width - 32) / max(1, len(headers)))
        graphics = []
        for y, row in enumerate([headers] + values):
            for x, value in enumerate(row):
                graphics.append({'type': 'text', 'x': x * cell_w, 'y': y * 25 + 5,
                    'style': {'text': str(value if value is not None else '—'), 'width': cell_w - 12,
                        'overflow': 'truncate', 'fontSize': 12, 'fontFamily': theme.font_family,
                        'fontWeight': 'bold' if y == 0 else 'normal', 'fill': theme.text}})
        return {**base, 'graphic': graphics}
    if item.type == 'pie':
        return {**base, 'legend': {'type': 'scroll', 'bottom': 0, 'textStyle': {'color': theme.text}},
            'series': [{'type': 'pie', 'radius': ['35%', '65%'], 'center': ['50%', '44%'],
                'label': {'show': True, 'overflow': 'truncate', 'width': 95},
                'data': [{'name': str(r.get(dims[0], '')), 'value': r.get('m0')} for r in rows]}]}
    if item.type == 'geo_map':
        points = []
        for row in rows:
            raw = row.get(dims[0])
            try:
                geo = json.loads(raw) if isinstance(raw, str) else raw
                if geo and geo.get('type') == 'Point':
                    points.append({'name': str(raw), 'value': geo['coordinates'][:2] + [row.get('m0')]})
            except (ValueError, TypeError, AttributeError):
                pass
        visual = {'min': min((r.get('m0') or 0) for r in rows),
            'max': max((r.get('m0') or 0) for r in rows) or 1, 'left': 0, 'bottom': 0,
            'inRange': {'color': [theme.surface, theme.accent]}}
        if points:
            return {**base, 'geo': {'map': 'world', 'roam': False},
                'visualMap': {**visual, 'dimension': 2},
                'series': [{'type': 'scatter', 'coordinateSystem': 'geo', 'symbolSize': 14, 'data': points}]}
        return {**base, 'visualMap': visual,
            'series': [{'type': 'map', 'map': 'world', 'roam': False,
                'data': [{'name': str(r.get(dims[0], '')), 'value': r.get('m0')} for r in rows]}]}
    base.update(grid={'left': 30, 'right': 8, 'top': 24, 'bottom': 18, 'containLabel': True},
        legend={'type': 'scroll', 'textStyle': {'color': theme.text}},
        xAxis={'type': 'category', 'data': [str(r.get(dims[0], '')) for r in rows],
               'axisLabel': {'overflow': 'truncate', 'width': 85}}, yAxis={'type': 'value'})
    if item.type == 'scatter':
        base['xAxis'] = {'type': 'value', 'name': item.metrics[0].field}
        base['yAxis']['name'] = item.metrics[1].field
        base['series'] = [{'type': 'scatter', 'symbolSize': 12,
            'data': [{'name': str(r.get(dims[0], '')), 'value': [r.get('m0'), r.get('m1')]} for r in rows]}]
    else:
        groups = list(dict.fromkeys(str(r.get(item.breakdown, '')) for r in rows)) if item.breakdown else [None]
        axis = list(dict.fromkeys(str(r.get(dims[0], '')) for r in rows))
        base['xAxis']['data'] = axis
        base['series'] = []
        for group in groups:
            subset = {str(r.get(dims[0], '')): r for r in rows if group is None or str(r.get(item.breakdown, '')) == group}
            for i, metric in enumerate(item.metrics):
                series = {'type': 'line' if item.type == 'time_series' else 'bar',
                    'name': metric.field if group is None else f'{group} / {metric.field}',
                    'data': [subset.get(label, {}).get('m' + str(i)) for label in axis]}
                if item.options.get('stacked'):
                    series['stack'] = metric.field
                base['series'].append(series)
    return base


def render(spec, *, layer=None, data=None, folder=None):
    theme = spec.theme
    data = data or {}
    known = catalog()
    charts = []
    parts = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{escape(spec.title)}</title>',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<style>body{margin:0}*{box-sizing:border-box}.item{position:absolute;overflow:hidden;padding:16px}.component{display:flex;flex-direction:column;gap:4px;padding:8px}.label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px;font-weight:600;flex:none}.chart{flex:1;min-height:0}.value{font-size:36px;font-weight:700}.component.scorecard{padding:6px 12px;gap:0}.scorecard .label{font-size:12px;line-height:12px}.scorecard .value{font-size:clamp(16px,calc(var(--box-height) - 28px),36px);line-height:1.1}.empty{margin:auto}.data-summary{overflow:auto;font-size:12px}table{border-collapse:collapse}th,td{text-align:left;padding:6px}select,input{font:inherit;min-height:24px;max-width:100%}.component.text{padding:8px;font-size:14px;line-height:20px}.component.date_range,.component.dropdown{padding:0;flex-direction:row;align-items:center;gap:4px}.date_range label{display:flex;align-items:center;gap:4px;font-size:12px}.date_range input{width:100px}.dropdown select{width:100%}img{width:100%;height:100%;object-fit:contain}.title{font-size:28px;font-weight:700}.subtitle{font-size:18px}.decoration{white-space:pre-wrap}</style></head><body>']
    for page in spec.pages:
        parts.append(f'<div id="dss-canvas" data-page="{page.index}" style="position:relative;width:{spec.canvas.width}px;height:{page.height}px;background:{css_value(theme.background)};color:{css_value(theme.text)};font-family:{css_value(theme.font_family)}">')
        for kind, items in (('decoration', page.decorations), ('component', page.components)):
            for item in items:
                if kind == 'component' and item.type not in known:
                    raise ValueError('Chart type is missing from the catalog')
                b = box(spec.canvas, spec.grid, item.grid, height=page.height)
                label = item.label if kind == 'component' else (item.text or item.kind)
                style = ';'.join(f'{k}:{b[v]}px' for k, v in (('left','x'),('top','y'),('width','w'),('height','h')))
                style += f';border-radius:{theme.radius}px;--box-height:{b["h"]}px'
                if kind == 'component':
                    style += f';background:{css_value(theme.surface)}'
                    if layer == 'decoration':
                        style += ';display:none'
                else:
                    defaults = {'background': theme.accent if item.kind in ('band','divider') else theme.surface if item.kind == 'panel' else 'transparent'}
                    aliases = {'background_color': 'background', 'color': 'color', 'font_size': 'font-size', 'font_weight': 'font-weight', 'border_radius': 'border-radius'}
                    defaults.update({aliases.get(k, k): v for k, v in item.style.items() if k in (*aliases, 'background', 'font-size', 'font-weight', 'border-radius', 'opacity')})
                    style += ''.join(f';{k}:{css_value(v)}' + ('px' if isinstance(v, (int, float)) and k in ('font-size','border-radius') else '') for k, v in defaults.items())
                extra = item.kind if kind == 'decoration' else item.type
                parts.append(f'<div class="item {kind} {extra}" data-cid="{escape(item.id, quote=True)}" data-label="{escape(label, quote=True)}" title="{escape(label, quote=True)}" data-kind="{kind}" style="{escape(style, quote=True)}">')
                if kind == 'decoration':
                    if item.kind == 'logo' and item.style.get('image_path'):
                        url = image_url(item.style['image_path'], folder)
                        parts.append(f'<img src="{url}" alt="{escape(label, quote=True)}">')
                    else:
                        parts.append(escape(item.text or ''))
                else:
                    label_html = escape(label, quote=True)
                    if item.type not in ('text', 'date_range', 'dropdown'):
                        parts.append(f'<div class="label" title="{label_html}">{escape(label)}</div>')
                    rows = data.get(item.id, [])
                    if item.type == 'text':
                        parts.append(f'<div>{escape(item.text or "")}</div>')
                    elif item.type == 'image':
                        url = image_url(item.image_path, folder)
                        parts.append(f'<img src="{url}" alt="{label_html}">' if url else '<div class="empty">No image</div>')
                    elif item.type == 'date_range':
                        parts.append(f'<label>From <input type="date" aria-label="{label_html} from"></label><label>To <input type="date" aria-label="{label_html} to"></label>')
                    elif not rows or (item.type == 'scorecard' and rows[0].get('m0') is None):
                        parts.append('<div class="empty">No data</div>')
                    elif item.type == 'dropdown':
                        parts.append(f'<select aria-label="{label_html}"><option>{escape(label)} — All</option>' + ''.join(f'<option>{escape(str(r.get(item.field, "")))}</option>' for r in rows) + '</select>')
                    elif item.type == 'scorecard':
                        value = rows[0].get('m0')
                        parts.append(f'<div class="value">{escape(format(value, ",.2f") if isinstance(value, (int,float,Decimal)) else str(value))}</div>')
                    elif layer != 'decoration':
                        chart_id = 'chart_' + item.id
                        parts.append(f'<div class="chart" id="{chart_id}" role="img" aria-label="{label_html}"></div>')
                        parts.append('<details class="data-summary"><summary>View data</summary><table><thead><tr>')
                        keys = list(rows[0])
                        headers = {f.name: f.label for f in spec.datasource.fields}
                        headers.update({f'm{i}': f'{headers.get(m.field, m.field)} ({m.agg})' for i, m in enumerate(item.metrics)})
                        parts.append(''.join(f'<th scope="col">{escape(headers.get(k, k))}</th>' for k in keys) + '</tr></thead><tbody>')
                        parts.append(''.join('<tr>' + ''.join(f'<td title="{escape(str(r.get(k, "")), quote=True)}">{escape(str(r.get(k, "")))}</td>' for k in keys) + '</tr>' for r in rows) + '</tbody></table></details>')
                        charts.append({'id': chart_id, 'geo': item.type == 'geo_map', 'option': chart_option(item, rows, theme, b['w'])})
                parts.append('</div>')
        parts.append('</div>')
    if charts:
        parts.append('<script src="https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js"></script><script>')
        parts.append('const charts=' + script_json(charts) + ';')
        parts.append('''(async()=>{try{if(!window.echarts)throw Error('Charts unavailable');
if(charts.some(c=>c.geo)){const response=await fetch('https://cdn.jsdelivr.net/npm/echarts@4.9.0/map/json/world.json');if(!response.ok)throw Error('Map unavailable');echarts.registerMap('world',await response.json());}
for(const c of charts){try{echarts.init(document.getElementById(c.id),null,{renderer:'svg'}).setOption(c.option);}catch(e){document.getElementById(c.id).textContent='Chart unavailable — view data below';}}
}catch(e){for(const c of charts){document.getElementById(c.id).textContent='Chart unavailable — view data below';}}finally{window.dssChartsReady=true;}})();</script>''')
    return ''.join(parts) + '</body></html>'
