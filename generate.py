import json
import os
import requests


def bugs(whiteboard):
    res = requests.get(
        'https://bugzilla.mozilla.org/rest/bug',
        params={
            'product': 'Toolkit',
            'component': 'WebExtensions',
            'whiteboard': '[%s]' % whiteboard,
            'include_fields': 'summary,status,resolution,id',
            'status': ['NEW', 'ASSIGNED', 'UNCONFIRMED', 'REOPENED']
        }
    )
    return res.json()


status_lookup = {
    "complete": "success",
    "partial": "warning",
    "no": "default",
    "unlikely": "default"
}


def formatted(data):
    res = ''
    for api, values in sorted(data.items()):
        res += '\t<h4 id="%s"><a href="#%s">&sect;</a> %s' % (api, api, api)
        res += '&nbsp;<span class="label label-%s">%s</span></h4>\n' % (status_lookup.get(values['status']), values['status'])
        res += '<blockquote>'
        if values['status'] in ['complete', 'partial']:
            res += '\t\t<a href="https://developer.mozilla.org/en-US/Add-ons/WebExtensions/API/%s">Firefox docs</a> &bull;\n' % api
        if 'code' in values:
            res += '\t\t<a href="%s">Firefox code</a> &bull;\n' % values['code']
        res += '\t\t<a href="https://developer.chrome.com/extensions/%s">Chrome docs</a>\n' % api

        pile_of_bugs = bugs(api)
        if pile_of_bugs:
            res += '\t\t<dl>\n'
            res += '\t\t\t<dt>%s bugs</dt>\n' % len(pile_of_bugs['bugs'])
            for bug in pile_of_bugs['bugs']:
                res += '\t\t\t<dd><a href="https://bugzilla.mozilla.org/show_bug.cgi?id=%s">%s: %s</a></dd>\n' % (bug['id'], bug['id'], bug['summary'])
            res += '\t\t</dl>\n'

        res += '\t</blockquote>\n'
    return res


data = json.load(open('data.json', 'r'))
html = open('template.html', 'r').read().encode('utf8')
data = formatted(data).encode('utf8')
html = html.format(data=data)
open('index.html', 'w').write(html)
