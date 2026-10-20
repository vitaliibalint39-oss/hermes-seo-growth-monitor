"""Offline evidence validation, calculations, and reports. No network/model calls."""
import argparse
import ctypes
import datetime as dt
import json
import math
import os
import re
from pathlib import Path
import uuid

# The three published domains are illustrative defaults; configure your own
# in a local config.json (excluded from version control). GA4 IDs are optional.
DEFAULT_SITES = ('ta551.info', 'siteprobelab.com', 'frattina10dream.com')
HOST = re.compile(r'^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$')
SCHEMA = 1



def site_config(path=None):
    """Return validated domain -> property mappings, without credentials."""
    config = read(path) if path else {'sites': {site: {} for site in DEFAULT_SITES}}
    sites = config.get('sites') if isinstance(config, dict) else None
    if not isinstance(sites, dict) or not sites or len(sites) > 30:
        raise ValueError('config.sites must contain 1–30 owned domains')
    result = {}
    for site, data in sites.items():
        if not isinstance(site, str) or not HOST.fullmatch(site) or not isinstance(data, dict):
            raise ValueError('Config sites require lowercase DNS hostnames and object settings')
        prop = data.get('gsc_property', 'sc-domain:' + site)
        validate_property(site, prop)
        ga4 = data.get('ga4_property')
        if ga4 is not None and (not isinstance(ga4, str) or not ga4.isdecimal() or len(ga4)>20):
            raise ValueError('Optional ga4_property must be a numeric string or null')
        result[site] = {'gsc_property': prop, 'ga4_property': ga4}
    return result


def validate_property(site, value):
    from urllib.parse import urlparse
    if not isinstance(value,str):
        raise ValueError('GSC property must be a string')
    if value == 'sc-domain:' + site:
        return
    u = urlparse(value)
    if not (u.scheme in ('http', 'https') and u.hostname in (site, 'www.' + site)
            and not u.username and not u.password and u.port in (None, 80, 443)
            and not u.query and not u.fragment and u.path in ('', '/')):
        raise ValueError('GSC property must belong to selected site')


def read(path):
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError('Evidence exceeds 2 MB; obtain a bounded response')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    os.replace(tmp, path)


def documents():
    if os.name != 'nt':
        raise ValueError('Windows Documents resolution required; use --output for offline tests')
    buf = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) != 0 or not buf.value:
        raise ValueError('Cannot resolve Windows Documents folder')
    return Path(buf.value)


def windows(end):
    result = {}
    for n in (7, 28):
        start = end - dt.timedelta(days=n-1)
        prev_end = start - dt.timedelta(days=1)
        result['current'+str(n)] = {'startDate': str(start), 'endDate': str(end)}
        result['previous'+str(n)] = {'startDate': str(prev_end-dt.timedelta(days=n-1)), 'endDate': str(prev_end)}
    return result


def requests(plan, site):
    prop = plan['sites'][site]['gsc_property']
    result = {}
    for period, dates in plan['windows'].items():
        result['gsc-'+period] = {'tool': 'analytics_query', 'args': {
            'siteUrl': prop, 'engine': 'google', **dates, 'dimensions': [], 'rowLimit': 1}}
        if plan['sites'][site].get('ga4_property'):
            result['ga4-'+period] = {'tool': 'analytics_advanced', 'args': {
                'propertyId': plan['sites'][site]['ga4_property'], 'metricType': 'user_behavior', **dates}}
    for label, dim, period in [('queries','query','current28'), ('pages','page','current28'),
                               ('pages-previous','page','previous28')]:
        result['gsc-'+label] = {'tool': 'analytics_query', 'args': {
            'siteUrl': prop, 'engine': 'google', **plan['windows'][period],
            'dimensions': [dim], 'rowLimit': 25}}
    result['sitemaps-google'] = {'tool': 'sitemaps_list', 'args': {'siteUrl': prop, 'engine': 'google'}}
    result['inspection-google'] = {'tool': 'inspection_inspect', 'args': {
        'siteUrl': prop, 'engine': 'google', 'urls': ['https://'+site+'/']}}
    return result


def init(output=None, end=None, site=None, synthetic=False, config=None):
    cutoff = dt.date.fromisoformat(end) if end else dt.date.today()-dt.timedelta(days=3)
    if cutoff >= dt.date.today():
        raise ValueError('Reporting end must precede today')
    sites = site_config(config)
    if site is not None and site not in sites:
        raise ValueError('Selected site is not configured')
    root = Path(output) if output else documents()/'Hermes-SEO'
    run = root/(dt.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    run.mkdir(parents=True, exist_ok=False)
    plan = {'schema': SCHEMA, 'synthetic': synthetic, 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'windows': windows(cutoff), 'sites': {s: sites[s] for s in ([site] if site else sites)}}
    save(run/'plan.json', plan)
    for s in plan['sites']:
        (run/'evidence'/s).mkdir(parents=True)
        save(run/('requests-'+s+'.json'), requests(plan, s))
    return run


def set_property(run, site, value):
    plan = read(run/'plan.json')
    if site not in plan['sites']:
        raise ValueError('Site not selected')
    validate_property(site, value)
    if any((run/'evidence'/site).iterdir()):
        raise ValueError('Cannot change property after evidence collection')
    plan['sites'][site]['gsc_property'] = value
    save(run/'plan.json', plan)
    save(run/('requests-'+site+'.json'), requests(plan, site))


def capture(run, site, label, source):
    """Wrap a saved tool response without asking an LLM to parse its numbers."""
    plan = read(run/'plan.json')
    if site not in plan['sites']:
        raise ValueError('Unknown site')
    expected = requests(plan,site)
    if label not in expected:
        raise ValueError('Unknown request label')
    response = read(source)
    envelope = {**expected[label], 'retrieved_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'response': response}
    target = run/'evidence'/site/(label+'.json')
    if target.exists():
        raise ValueError('Evidence already exists; use a new run to preserve history')
    save(target,envelope)
    return target


def unwrap(response):
    if isinstance(response, dict) and response.get('isError'):
        raise ValueError('MCP reported an error (details withheld)')
    if isinstance(response, dict) and 'content' in response:
        payloads = []
        for block in response['content']:
            if block.get('type') != 'text':
                continue
            try:
                obj, _ = json.JSONDecoder().raw_decode(block['text'].lstrip())
                payloads.append(obj)
            except (ValueError, KeyError):
                continue
        if len(payloads) != 1:
            raise ValueError('Expected exactly one JSON payload')
        response = payloads[0]
    if isinstance(response, dict) and 'error' in response:
        raise ValueError('Provider error (details withheld)')
    # Some Hermes native tool bridges wrap a scoped response in {"result": ...}.
    # Unwrap only a recognized Google scope, never a generic nested "result"
    # (which may be a legitimate URL Inspection payload).
    if (isinstance(response, dict) and set(response) == {'result'}
            and isinstance(response['result'], dict)
            and 'google' in response['result']):
        response = response['result']
    return response


def evidence(folder, label, expected):
    p = folder/(label+'.json')
    if not p.exists():
        return None, 'Unavailable: no evidence'
    try:
        obj = read(p)
        actual_args = obj.get('args')
        wanted_args = expected['args']
        if expected['tool'] == 'inspection_inspect' and isinstance(actual_args,dict):
            from urllib.parse import urlparse
            urls = actual_args.get('urls',[])
            host = folder.name
            if not isinstance(urls,list) or not 1 <= len(urls) <= 3:
                raise ValueError('Bound inspections to three owned URLs')
            for url in urls:
                parsed = urlparse(url)
                if parsed.scheme != 'https' or parsed.hostname not in (host,'www.'+host) or parsed.username or parsed.password or parsed.port not in (None,443):
                    raise ValueError('Inspection outside owned site')
            wanted_args = {**wanted_args,'urls':urls}
        if obj.get('tool') != expected['tool'] or actual_args != wanted_args:
            raise ValueError('Tool/arguments differ from request plan')
        stamp = dt.datetime.fromisoformat(obj['retrieved_at'].replace('Z','+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('retrieved_at must include timezone')
        value = unwrap(obj['response'])
        if expected['args'].get('engine') == 'google':
            if not isinstance(value, dict) or 'google' not in value:
                raise ValueError('Missing Google response scope')
            value = unwrap(value['google'])
        return value, 'Available'
    except (ValueError, KeyError, TypeError, OSError):
        return None, 'Unavailable: invalid scope, dates, envelope, or provider error'


def number(value, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or value < minimum:
        raise ValueError('Invalid numeric metric')
    return value


def metric(row):
    clicks, impressions = number(row['clicks']), number(row['impressions'])
    if clicks > impressions:
        raise ValueError('Clicks exceed impressions')
    ctr = clicks/impressions if impressions else None
    position = number(row['position']) if impressions and row.get('position') is not None else None
    return {'clicks': clicks, 'impressions': impressions, 'ctr': ctr, 'position': position}


def totals(value):
    if value is None or value == []:
        return None  # no rows is not a measured zero
    if not isinstance(value, list) or len(value) != 1 or value[0].get('keys'):
        raise ValueError('Totals require one ungrouped row')
    return metric(value[0])


def delta(current, previous):
    if current is None or previous is None:
        return None
    return {'absolute': current-previous,
            'percent': (current-previous)/previous*100 if previous else None}


def breakdown_changes(current,previous,key):
    old = {r.get(key):r for r in previous if isinstance(r,dict)}
    changes=[]
    for row in current[:10]:
        try:
            before=old[row[key]]
            changes.append([row[key],fmt(number(row['activeUsers'])-number(before['activeUsers'])),
                            fmt(number(row['sessions'])-number(before['sessions']))])
        except (ValueError,KeyError,TypeError):
            continue
    return changes


def text(value):
    return str(value).replace('|','\\|').replace('\r',' ').replace('\n',' ').replace('<','&lt;').replace('>','&gt;')[:500]


def fmt(value, percent=False):
    if value is None:
        return 'Unavailable'
    return f'{value*100:.2f}%' if percent else f'{value:,.2f}'.rstrip('0').rstrip('.')


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(text(c) for c in row)+' |' for row in rows])+'\n'


def history(run, plan, site=None):
    candidates=[]
    for other in run.parent.iterdir():
        if other == run or not (other/'snapshot.json').is_file():
            continue
        try:
            snap = read(other/'snapshot.json')
            if snap['schema'] == SCHEMA and snap['synthetic'] == plan['synthetic'] and snap['created_at'] < plan['created_at']:
                if site and snap.get('sites',{}).get(site,{}).get('property') != plan['sites'][site]['gsc_property']:
                    continue
                candidates.append(snap)
        except (ValueError, KeyError, OSError):
            continue
    return max(candidates,key=lambda s:s['created_at']) if candidates else None


def optional(folder, name):
    try:
        obj = read(folder/name)
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def render_site(run, plan, site, prior):
    folder = run/'evidence'/site
    expected = requests(plan, site)
    values, status = {}, {}
    for label, req in expected.items():
        values[label], status[label] = evidence(folder, label, req)
    metrics = {}
    for period in plan['windows']:
        label = 'gsc-'+period
        try:
            metrics[period] = totals(values[label])
            if metrics[period] is None and status[label] == 'Available':
                status[label] = 'No rows; completeness and activity unknown'
        except (ValueError, TypeError, KeyError):
            metrics[period] = None
            status[label] = 'Invalid ungrouped metrics'
    marker = 'SYNTHETIC TEST DATA — NOT LIVE SEO RESULTS' if plan['synthetic'] else 'Evidence-backed where available; missing data is unknown'
    lines = [f'# SEO report: {site}', '', marker, '', f"GSC property: {plan['sites'][site]['gsc_property']}",
             f"GA4 property: {plan['sites'][site].get('ga4_property') or 'Not configured'}", '', '## Provider coverage', '',
             'Google: see per-request status. Bing: period performance unavailable in this adapter; rotation confirmation required for any Bing call.',
             'GA4: country/device breakdowns if configured and available. Exact period unique users, total sessions, and traffic sources unavailable with the current tool surface.', '',
             table(['Request', 'Status'], [(k,v) for k,v in status.items()]), '## Search performance', '']
    rows = []
    for period, dates in plan['windows'].items():
        m = metrics[period] or {}
        rows.append([period, dates['startDate']+' — '+dates['endDate'], fmt(m.get('clicks')),
                     fmt(m.get('impressions')), fmt(m.get('ctr'), True), fmt(m.get('position'))])
    lines += [table(['Period','Dates (inclusive)','Clicks','Impressions','CTR','Average position'],rows),
              'GSC web search. Final-data lag may remain. Position is an average for this property/window, not a site-wide rank. Impressions are not visitors.', '', '## Period changes', '']
    for n in (7,28):
        c, p = metrics['current'+str(n)], metrics['previous'+str(n)]
        for key in ('clicks','impressions'):
            change = delta(c.get(key) if c else None, p.get(key) if p else None)
            lines.append(f'- {n}-day {key}: '+ (f"{fmt(change['absolute'])} absolute; {fmt(change['percent'])}% relative (undefined for zero baseline)." if change else 'Unavailable.'))
    lines += ['', '## Query and landing-page samples', '']
    samples = {}
    for label in ('gsc-queries','gsc-pages','gsc-pages-previous'):
        sample = values[label]
        good = []
        if isinstance(sample,list):
            for row in sample[:25]:
                try:
                    if len(row['keys']) != 1:
                        continue
                    good.append({'label': row['keys'][0], **metric(row)})
                except (KeyError, TypeError, ValueError):
                    continue
        samples[label] = good
        if label != 'gsc-pages-previous':
            lines += ['### '+label, '',table(['Query/page','Clicks','Impressions','CTR','Position'],
                [[r['label'],fmt(r['clicks']),fmt(r['impressions']),fmt(r['ctr'],True),fmt(r['position'])] for r in good]) if good else 'Unavailable.', '']
    lines += ['Top 25 samples; may omit private queries and other rows. Do not sum as totals.', '', '## Opportunity screening', '']
    opportunities = []
    for r in samples['gsc-queries']:
        if r['impressions'] >= 100 and r['ctr'] is not None and r['ctr'] < .02:
            opportunities.append('Low-CTR candidate: '+text(r['label'])+' (gsc-queries.json; intent review needed).')
        if r['impressions'] >= 100 and r['position'] is not None and 8 <= r['position'] <= 20:
            opportunities.append('Near-page-one candidate: '+text(r['label'])+' (average position, not guaranteed rank).')
    oldpages = {r['label']:r for r in samples['gsc-pages-previous']}
    for r in samples['gsc-pages']:
        old = oldpages.get(r['label'])
        if old and old['clicks'] >= 10 and r['clicks'] < old['clicks']*.8:
            opportunities.append('Matched-page traffic decline: '+text(r['label'])+'; investigate seasonality and intent before changes.')
    lines += ['- '+v for v in opportunities[:5]] or ['No supported candidates in the available sample; this is not proof of no opportunities.']
    lines += ['', '## GA4 breakdowns', '']
    for period in plan['windows']:
        value = values.get('ga4-'+period)
        lines += ['### '+period, '']
        if not isinstance(value,dict):
            lines += ['Unavailable.', '']; continue
        for dim, key in [('devices','deviceCategory'), ('countries','country')]:
            rows = []
            for r in value.get(dim,[])[:10]:
                try:
                    rows.append([r[key],fmt(number(r['activeUsers'])),fmt(number(r['sessions']))])
                except (ValueError,KeyError,TypeError):
                    continue
            lines += [table([key,'Active users (row)','Sessions (row)'],rows) if rows else 'Breakdown unavailable.', '']
    lines += ['Breakdowns are not unique-user totals. Country output is top ten; all channels, not organic-only.', '', '## Indexing and technical checks', '']
    for n in (7,28):
        current,previous=values.get('ga4-current'+str(n)),values.get('ga4-previous'+str(n))
        if isinstance(current,dict) and isinstance(previous,dict):
            for dim,key in [('devices','deviceCategory'),('countries','country')]:
                changes=breakdown_changes(current.get(dim,[]),previous.get(dim,[]),key)
                if changes:
                    lines += [f'GA4 {n}-day matched {dim} absolute changes (missing rows are unknown):','',
                              table([key,'Active users change (row)','Sessions change (row)'],changes),'']
    sitemap_rows=[]
    if isinstance(values['sitemaps-google'],list):
        for sm in values['sitemaps-google'][:25]:
            if not isinstance(sm,dict): continue
            for content in (sm.get('contents') or [{}])[:5]:
                sitemap_rows.append([sm.get('path','Unknown'),sm.get('lastDownloaded','Unknown'),
                    sm.get('isPending','Unknown'),sm.get('errors','Unknown'),content.get('type','Unknown'),
                    content.get('submitted','Unknown'),content.get('indexed','Unknown')])
    lines += [table(['Sitemap','Last download','Pending','Errors','Type','Submitted','Indexed'],sitemap_rows)
              if sitemap_rows else 'Sitemap counts unavailable; no whole-site indexing conclusion.','']
    inspection = values['inspection-google']
    inspections = inspection if isinstance(inspection,list) else [{'result':inspection}]
    inspection_rows=[]
    for item in inspections[:3]:
        if not isinstance(item,dict): continue
        result = item.get('result') or {}
        state = result.get('inspectionResult',{}).get('indexStatusResult',{})
        if state:
            inspection_rows.append([item.get('url','Requested homepage'),state.get('verdict','Unknown'),
                state.get('coverageState','Unknown'),state.get('robotsTxtState','Unknown'),
                state.get('userCanonical','Unknown'),state.get('googleCanonical','Unknown')])
    lines += [table(['URL','Verdict','Coverage','Robots state','Declared canonical','Google canonical'],inspection_rows)
              if inspection_rows else 'Inspection state unknown.','']
    observations = optional(folder, 'observations.json')
    checks = observations.get('checks',[])[:20]
    valid_checks = [c for c in checks if isinstance(c,dict) and c.get('priority') in ('P0','P1','P2','P3') and c.get('status') in ('confirmed','clear','unknown') and c.get('evidence')]
    valid_checks.sort(key=lambda c:c['priority'])
    lines += [table(['Priority','Status','Observation','Evidence','Proposed action'], [[c['priority'],c['status'],c.get('finding',''),c['evidence'],c.get('action','')] for c in valid_checks]) if valid_checks else 'No validated indexing/robots/canonical observations supplied.',
              'Raw sitemaps/inspection evidence remains in the local evidence directory when collected. Unknown URL != confirmed failure; sitemap indexed count != whole-site index coverage.', '']
    for note in observations.get('coverage',[])[:10]:
        lines.append('- '+text(note))
    pages = [p for p in observations.get('pages',[])[:100] if isinstance(p,dict) and isinstance(p.get('url'),str) and p.get('source')]
    prior_site = (prior or {}).get('sites',{}).get(site)
    if prior_site and prior_site.get('property') != plan['sites'][site]['gsc_property']:
        prior_site = None
    seen = set((prior_site or {}).get('pages',[]))
    new = [p['url'] for p in pages if p['url'] not in seen]
    lines += ['## Historical observation', '',
              f"Previous compatible snapshot: {prior['created_at']}. Overlapping windows are not independent period comparisons." if prior_site else 'No previous compatible snapshot: establishing baseline.',
              f'First-seen URLs in supplied inventory: {len(new)}. First seen is not a publication date.', '']
    if prior_site:
        previous_metric = prior_site.get('metrics',{}).get('current28') or {}
        current_metric = metrics.get('current28') or {}
        change = delta(current_metric.get('clicks'),previous_metric.get('clicks'))
        lines += ['Earlier snapshot current28 window: '+text(prior['windows']['current28'])+'.',
                  'Snapshot click difference (NOT period-over-period): '+(fmt(change['absolute']) if change else 'Unavailable')+'.']
    lines += ['- '+text(u) for u in new[:10]]
    strategy = optional(folder,'strategy.json')
    lines += ['', '## Prioritized recommendations', '']
    recs = strategy.get('recommendations',[])[:5]
    for rec in recs:
        if isinstance(rec,dict):
            lines.append('- '+text(rec.get('priority','P3'))+': '+text(rec.get('action','Unspecified'))+
                         ' — '+text(rec.get('rationale','Hypothesis; validate'))+'; evidence: '+text(rec.get('evidence','Unavailable'))+'; effort: '+text(rec.get('effort','unknown')))
    if not recs:
        lines.append('Awaiting evidence-linked intent review; no unsupported recommendations generated.')
    lines += ['', '## Proposed 14-day content plan', '']
    days = {}
    for item in strategy.get('content_plan',[])[:14]:
        if isinstance(item,dict) and type(item.get('day')) is int and 1 <= item['day'] <= 14 and item['day'] not in days:
            days[item['day']] = item
    rows = []
    for day in range(1,15):
        item = days.get(day,{})
        rows.append([day,item.get('topic','Unplanned: evidence/intent review needed'), item.get('keyword','Unknown'), item.get('intent','Unconfirmed'),item.get('action','No publication'),item.get('evidence','Unavailable')])
    lines += [table(['Day','Topic/task','Keyword','Intent','Proposed action','Evidence'],rows),
              'All recommendations and plans are proposals only. No publication, indexing submission, or website changes.', '']
    (run/(site+'.md')).write_text('\n'.join(lines),encoding='utf-8')
    return {'property': plan['sites'][site]['gsc_property'], 'metrics': metrics,
            'pages': [p['url'] for p in pages], 'status': status, 'opportunities': opportunities[:5],
            'technical_checks':valid_checks}


def render(run):
    plan = read(run/'plan.json')
    if not isinstance(plan,dict) or plan.get('schema') != SCHEMA or not isinstance(plan.get('sites'), dict) or not plan['sites']:
        raise ValueError('Unsupported plan')
    for site, settings in plan['sites'].items():
        if not HOST.fullmatch(site) or not isinstance(settings,dict):
            raise ValueError('Invalid site configuration in plan')
        validate_property(site, settings.get('gsc_property'))
        ga4 = settings.get('ga4_property')
        if ga4 is not None and (not isinstance(ga4,str) or not ga4.isdecimal()):
            raise ValueError('Invalid optional GA4 property in plan')
    expected_windows = windows(dt.date.fromisoformat(plan['windows']['current28']['endDate']))
    if plan['windows'] != expected_windows:
        raise ValueError('Inconsistent comparison windows')
    snap = {k:plan[k] for k in ('schema','synthetic','created_at','windows')}
    snap['sites'] = {site:render_site(run,plan,site,history(run,plan,site)) for site in plan['sites']}
    save(run/'snapshot.json',snap)
    lines = ['# Combined SEO summary', '', 'SYNTHETIC TEST DATA' if plan['synthetic'] else 'Live-evidence report; unavailable is not zero', '']
    for site,result in snap['sites'].items():
        m = result['metrics']['current28'] or {}
        lines += [f'## {site}', '', f"28-day clicks: {fmt(m.get('clicks'))}; impressions: {fmt(m.get('impressions'))}.",
                  f"Requests with available evidence: {sum(s=='Available' for s in result['status'].values())}/{len(result['status'])}.",
                  'Bing period performance and exact GA4 totals/sources unavailable. See site report for scoped breakdowns and technical priorities.',
                  f'[{site} report]({site}.md)', '']
    problems = sorted([(c['priority'],s,c) for s,r in snap['sites'].items()
                       for c in r['technical_checks'] if c['status']=='confirmed'],key=lambda x:(x[0],x[1]))
    lines += ['## Prioritized confirmed technical problems','',
              table(['Priority','Site','Finding','Evidence','Proposed action'],
                    [[p,s,c.get('finding',''),c['evidence'],c.get('action','')] for p,s,c in problems])
              if problems else 'No confirmed technical problems supplied; this does not establish site health.','']
    lines += ['No scheduled jobs or production changes. Check coverage before acting on recommendations.']
    (run/'summary.md').write_text('\n'.join(lines),encoding='utf-8')
    return run/'summary.md'



def check_record(folder, label, request):
    """Classify one on-disk evidence record without modifying it."""
    target = folder/(label+'.json')
    if not target.is_file():
        return 'missing'
    value, state = evidence(folder, label, request)
    if state != 'Available':
        return 'invalid'
    try:
        tool = request['tool']
        if tool == 'analytics_query':
            if not isinstance(value, list):
                raise ValueError('Google analytics must return an array')
            if label in ('gsc-current7', 'gsc-previous7', 'gsc-current28', 'gsc-previous28'):
                totals(value)  # Empty rows are valid evidence, but not measured zero.
            else:
                if len(value) > 25:
                    raise ValueError('Grouped response exceeds approved sample size')
                for row in value:
                    if (not isinstance(row, dict) or not isinstance(row.get('keys'), list)
                            or len(row['keys']) != 1 or not isinstance(row['keys'][0], str)):
                        raise ValueError('Invalid grouped dimension')
                    metric(row)
        elif tool == 'analytics_advanced':
            if not isinstance(value, dict):
                raise ValueError('GA4 response must be an object')
        elif tool == 'sitemaps_list':
            if not isinstance(value, list):
                raise ValueError('Sitemaps response must be an array')
        elif tool == 'inspection_inspect':
            if not isinstance(value, (list, dict)):
                raise ValueError('Inspection response must be an array or object')
        else:
            raise ValueError('Unknown planned tool')
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        return 'invalid'
    return 'completed'


def status(run, site=None):
    """Report resumable progress based on files, not LLM claims."""
    run = Path(run)
    plan = read(run/'plan.json')
    if not isinstance(plan, dict) or plan.get('schema') != SCHEMA:
        raise ValueError('Unsupported plan')
    sites = plan.get('sites')
    if not isinstance(sites, dict) or not sites:
        raise ValueError('No configured sites')
    if site is not None and site not in sites:
        raise ValueError('Unknown site')
    if plan.get('windows') != windows(dt.date.fromisoformat(plan['windows']['current28']['endDate'])):
        raise ValueError('Inconsistent date windows')
    result = {'run': str(run), 'counts': {'planned': 0, 'completed': 0, 'missing': 0, 'invalid': 0}, 'sites': {}}
    for name in ([site] if site else sites):
        records = {'completed': [], 'missing': [], 'invalid': []}
        folder = run/'evidence'/name
        for label, request in requests(plan, name).items():
            state = check_record(folder, label, request)
            records[state].append(label)
            result['counts'][state] += 1
            result['counts']['planned'] += 1
        result['sites'][name] = {'counts': {
            'planned': sum(len(v) for v in records.values()),
            'completed': len(records['completed']),
            'missing': len(records['missing']),
            'invalid': len(records['invalid'])}, **records}
    return result


def next_request(run, site=None, skip_tools=()):
    """Return at most one verified planned operation; never invoke MCP here."""
    run = Path(run)
    state = status(run, site=site)
    plan = read(run/'plan.json')
    excluded = set(skip_tools)
    for name, details in state['sites'].items():
        invalid, missing = set(details['invalid']), set(details['missing'])
        for label, request in requests(plan, name).items():
            if request['tool'] in excluded:
                continue
            if label in invalid:
                return {'state': 'blocked_invalid', 'run': str(run), 'site': name,
                        'label': label, 'evidence': str(run/'evidence'/name/(label+'.json')),
                        'action': 'Review the existing invalid record; never overwrite automatically',
                        'counts': state['counts']}
            if label in missing:
                return {'state': 'pending', 'run': str(run), 'site': name,
                        'label': label, 'tool': 'mcp__seo_traffic__'+request['tool'],
                        'args': request['args'], 'counts': state['counts']}
    complete = state['counts']['missing'] == 0 and state['counts']['invalid'] == 0
    return {'state': 'complete' if complete else 'no_eligible_requests',
            'run': str(run), 'skipped_tools': sorted(excluded), 'counts': state['counts']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('init'); p.add_argument('--output'); p.add_argument('--end')
    p.add_argument('--site'); p.add_argument('--config',type=Path)
    p.add_argument('--synthetic',action='store_true')
    p = sub.add_parser('render'); p.add_argument('--run',required=True,type=Path)
    p = sub.add_parser('property'); p.add_argument('--run',required=True,type=Path)
    p.add_argument('--site',required=True); p.add_argument('--value',required=True)
    p = sub.add_parser('capture'); p.add_argument('--run',required=True,type=Path)
    p.add_argument('--site',required=True); p.add_argument('--label',required=True)
    p.add_argument('--response',required=True,type=Path)
    p = sub.add_parser('status'); p.add_argument('--run',required=True,type=Path)
    p.add_argument('--site')
    p = sub.add_parser('next'); p.add_argument('--run',required=True,type=Path)
    p.add_argument('--site')
    p.add_argument('--skip-tool',action='append',default=[],
                   choices=['analytics_query','analytics_advanced','sitemaps_list','inspection_inspect'])
    args = parser.parse_args()
    try:
        if args.command == 'init':
            print(init(args.output,args.end,args.site,args.synthetic,args.config))
        elif args.command == 'render':
            print(render(args.run))
        elif args.command == 'capture':
            print(capture(args.run,args.site,args.label,args.response))
        elif args.command == 'status':
            print(json.dumps(status(args.run, args.site), indent=2))
        elif args.command == 'next':
            print(json.dumps(next_request(args.run, args.site, args.skip_tool), indent=2))
        else:
            set_property(args.run,args.site,args.value); print('Local request plan updated')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        parser.exit(1, f'Unable to complete offline report operation: {type(exc).__name__}. Check paths, permissions, and input schema.\n')


if __name__ == '__main__':
    main()
