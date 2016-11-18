import json
import os
import requests
import glob
import string
import csv

GET_BUGS = True
CHECK_URL = True

MDN_URL = 'https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/%s/%s'
schema_locations = [
    '../firefox/mozilla-central/browser/components/extensions/schemas/',
    '../firefox/mozilla-central/toolkit/components/extensions/schemas/'
]
schema_skip = [
    '../firefox/mozilla-central/browser/components/extensions/schemas/context_menus_internal.json',
#    '../firefox/firefox/toolkit/components/extensions/schemas/notifications.json'
]
usage_file = 'usage.csv'

parsed_schema = {}


def parse_usage():
    res = {}
    with open(usage_file) as csvfile:
        reader = csv.DictReader(csvfile)
        for k, row in enumerate(reader):
            res[row['API']] = k
    return res


def bugs(whiteboard):
    res = requests.get(
        'https://bugzilla.mozilla.org/rest/bug',
        params={
            'product': 'Toolkit',
            'component': ['WebExtensions: Untriaged',
    'WebExtensions: Android', 'WebExtensions: Compatibility',
    'WebExtensions: Developer tools', 'WebExtensions: Experiments', 'WebExtensions: Frontend',
    'WebExtensions: General', 'WebExtensions: Request Handling'],
            'whiteboard': '[%s]' % whiteboard,
            'include_fields': 'summary,status,resolution,id',
            'status': ['NEW', 'ASSIGNED', 'UNCONFIRMED', 'REOPENED']
        }
    )
    return res.json()


status_lookup = {
    "complete": "primary",
    "partial": "info",
    "not yet": "default",
    "unlikely": "default",
    "no": "danger"
}

platform_lookup = {
    "android": "success",
    "desktop": "success"
}


def formatted(data):
    res = ''
    for api, values in sorted(data.items()):
        res += '<div class="api-group" style="display: block">'
        res += '\t<h4 id="%s"><a href="#%s" class="anchor">&sect;</a> %s' % (api, api, api)
        res += '&nbsp;<span class="label label-%s">%s</span>\n' % (status_lookup.get(values['status']), values['status'])
        for platform in values.get('platform', []):
            res += '&nbsp;<span class="label label-%s">%s</span>\n' % (platform_lookup.get(platform), platform)
        res += '</h4>'
        res += '<blockquote>'
        if values['status'] in ['complete', 'partial']:
            res += '\t\t<a href="https://developer.mozilla.org/en-US/Add-ons/WebExtensions/API/%s">Firefox docs</a> &bull;\n' % api
        if 'code' in values:
            res += '\t\t<a href="%s">Firefox code</a> &bull;\n' % values['code']
        res += '\t\t<a href="https://developer.chrome.com/extensions/%s">Chrome docs</a>\n' % api


        pile_of_bugs = None
        if GET_BUGS:
            pile_of_bugs = bugs(api)

        if pile_of_bugs:
            res += '<h5 id="%s-bugs"><a href="#%s-bugs" class="anchor">&sect;</a> %s bugs</h5>\n' % (api, api, len(pile_of_bugs['bugs']))
            res += '<table class="table table-striped">\n'
            for bug in pile_of_bugs['bugs']:
                res += '\t<tr>'
                res += '\t\t<td><a href="https://bugzilla.mozilla.org/show_bug.cgi?id=%s">%s: %s</a></td>\n' % (bug['id'], bug['id'], bug['summary'])
            res += '\t</tr>\n'
            res += '</table>'

        schemas = parsed_schema.get(api, {})
        res = htmlify_schema(res, schemas.get('functions', []), 'functions', api)
        res = htmlify_schema(res, schemas.get('events', []), 'events', api)

        res += '\t</blockquote>\n'
        res += '\t</div>\n'
    return res


def compats(data):
    res = ''
    dates = data['desktop'].items()

    res += '<table class="table table-striped">\n'
    res += '\t<thead><tr><td>Date</td><td>Amount</td></tr></thead>\n'

    for date, amount in reversed(sorted(dates)):
        res += '\t<tr>'
        res += '\t\t<td>%s</td><td>%s%%</td>' % (date, amount)
        res += '\t</tr>'

    res += '</table>'
    return res


def htmlify_schema(res, schema, type_, api):
    if not schema:
        return res

    res += '<h5 id="%s-%s"><a href="#%s-%s" class="anchor">&sect;</a> %s %s</h5>\n' % (api, type_, api, type_, len(schema), type_)
    res += '<table class="table table-striped">\n'
    for key, value in schema.items():
        res += '\t<tr>'
        res += '\t\t<td><span class="label label-%s">%s</span></td>' % (
            'success' if value['supported'] else 'danger',
            'supported' if value['supported'] else 'not supported'
            )

        if value['url']:
            res += '<td><a href="%s">%s</a></td><td></td>' % (value['url'], value['full'])
        else:
            res += '<td>%s</td><td><span class="label label-default">no docs</span></td>' % (value['full'])

        rank = parsed_usage.get(value['usage'], None)
        if rank:
            res += '<td><span class="label label-info"><a id="rank-%s">rank %s</a></span></td>' % (rank, rank)
        else:
            res += '<td></td>'

        res += '</tr>\n'
    res += '</table>\n'
    return res


def process_schemas(directories):
    for directory in directories:
        for fname in glob.glob(directory + '*.json'):
            if fname in schema_skip:
                continue

            lines = open(fname, 'r').readlines()
            # Strip out stupid comments.
            newlines = []
            for line in lines:
                if not line.startswith(('//', '/*', ' *')):
                    newlines.append(line)

            process_json(json.loads('\n'.join(newlines)))


def process_json(data):
    for element in data:
        for k, v in element.items():
            if k == 'namespace' and v != 'manifest':
                if '_internal' in v:
                    continue
                parsed_schema['__current__'] = v

    for element in data:
        for k, v in element.items():
            if k == 'functions':
                for function in v:
                    process_type('functions', function)
            if k == 'events':
                for event in v:
                    process_type('events', event)


def wikify(name):
    return string.capitalize(name[0]) + name[1:]


def check_url(url):
    res = requests.get(url).status_code == 200
    if not res:
        print url, '...failed.'
        return
    return res


def process_type(type_, data):
    namespace = parsed_schema['__current__']
    parsed_schema.setdefault(namespace, {})
    parsed_schema[namespace].setdefault(type_, {})
    full = 'chrome.%s.%s' % (namespace, data['name'])
    mdn = full[:]
    if type_ == 'functions':
        mdn += '()'
    url = MDN_URL % (wikify(namespace), data['name'])
    if CHECK_URL:
        url = url if check_url(url) else None

    parsed_schema[namespace][type_][data['name']] = {
        'usage': full,
        'full': mdn,
        'supported': not(data.get('unsupported')),
        'url': url,
        'permissions': data.get('permissions')
    }


if __name__=='__main__':
    parsed_usage = parse_usage()
    process_schemas(schema_locations)

    data = json.load(open('data.json', 'r'))
    html = open('template.html', 'r').read().encode('utf8')
    data = formatted(data).encode('utf8')
    html = html.format(data=data)
    open('index.html', 'w').write(html)
