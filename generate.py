import hashlib
import json
import os
import requests
import glob
import string
import csv

from jinja2 import Environment, FileSystemLoader

GET_BUGS = True
CHECK_URL = True

MDN_URL = 'https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/%s/%s'
schema_locations = [
    '../firefox/head-for-scripts/browser/components/extensions/schemas/',
    '../firefox/head-for-scripts/toolkit/components/extensions/schemas/'
]
schema_skip = [
    '../firefox/head-for-scripts/browser/components/extensions/schemas/context_menus_internal.json',
#    '../firefox/firefox/toolkit/components/extensions/schemas/notifications.json'
]
usage_file = 'usage.csv'

parsed_schema = {}
parsed_manifest = {'permissions': [], 'keys': []}

amo_server = os.getenv('AMO_SERVER', 'https://addons.mozilla.org')

# Try to give some reasons why not.
reason_types = {
    'deprecated':[
        'chrome.extension.sendMessage',
        'chrome.extension.onRequest',
        'chrome.extension.onRequestExternal',
        'chrome.extension.onMessage',
        'chrome.extension.sendRequest',
        'chrome.app.getDetails',
        'chrome.tabs.getAllInWindow',
        'chrome.tabs.sendRequest',
        'chrome.extension.connect',
        'chrome.extension.onConnect'
    ],
    'low_usage': [],
    'no_equivalent': [
        'chrome.tabs.getSelected',
        'chrome.tabs.onHighlightChanged',
        'chrome.tabs.onSelectionChanged',
        'chrome.sessions.getDevices',
        'chrome.identity.getAuthToken',
        'chrome.identity.getAccounts',
        'chrome.identity.getProfileUserInfo',
        'chrome.identity.removeCachedAuthToken',
        'chrome.identity.onSignInChanged',
        'chrome.runtime.restart',
        'chrome.extension.setUpdateUrlData',
        'chrome.downloads.setShelfEnabled',
        # See bug 1320518.
        'chrome.runtime.getPackageDirectoryEntry',
    ],
    'internal': [
        'chrome.browserAction.openPopup',
        # See bug 1316297.
        'chrome.bookmarks.import',
        'chrome.bookmarks.export',
    ]
}

reasons = {}
for reason_type, api_list in reason_types.items():
    for api in api_list:
        reasons.setdefault(api, [])
        reasons[api].append(reason_type)


fixups = {
    'testpilot@labs.mozilla.com': 'Test Pilot (old one)',
    '{20a82645-c095-46ed-80e3-08825760534b}': 'Microsoft .NET framework assistant',
}


def parse_usage():
    res = {}
    with open(usage_file) as csvfile:
        reader = csv.DictReader(csvfile)
        for k, row in enumerate(reader):
            res[row['API']] = k
    return res


def process_amo(addon, result, compat):
    try:
        name = result['name']['en-US']
    except KeyError:
        name = result['slug']
    return {
        'name': name,
        'url': result['url'],
        'guid': result['guid'],
        'status': compat['e10s'] == 'compatible-webextension',
        'id': result['id'],
        'users': addon.get('users', 0)
    }


def url_hash(url):
    hsh = hashlib.md5()
    hsh.update(url)
    return hsh.hexdigest()


def set_cache(url, result):
    filename = os.path.join('cache', url_hash(url) + '.json')
    json.dump(result, open(filename, 'w'))


def get_cache(url):
    filename = os.path.join('cache', url_hash(url) + '.json')
    if os.path.exists(filename):
        print 'Using cache:', filename
        return json.load(open(filename, 'r'))


def get_from_amo(addon):
    guid = addon['guid']
    addon_url = amo_server + '/api/v3/addons/addon/{}/'.format(guid)
    addon_data = get_cache(addon_url)

    compat_url = amo_server + '/api/v3/addons/addon/{}/feature_compatibility/'.format(guid)
    compat_data = get_cache(compat_url)
    if addon_data and compat_data:
        return process_amo(addon, addon_data, compat_data)

    data = []
    for url in (addon_url, compat_url):
        print 'Fetching', url
        res = requests.get(url)
        if res.status_code != 200:
            return {
                'name': fixups.get(
                    guid, '{} error fetching data from AMO'.format(res.status_code)),
                'url': '',
                'guid': guid,
                'status': 'error',
                'id': 0
            }

        res.raise_for_status()
        res_json = res.json()
        set_cache(url, res_json)
        data.append(res_json)

    return process_amo(addon, *data)


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
        last_key = None
        for k, v in element.items():
            if k == 'namespace' and v != 'manifest':
                if '_internal' in v:
                    continue
                parsed_schema['__current__'] = v
            if k == 'types':
                process_manifest_types(v)

    for element in data:
        for k, v in element.items():
            if k == 'functions':
                for function in v:
                    process_type('functions', function)
            if k == 'events':
                for event in v:
                    process_type('events', event)


def process_manifest_types(types):
    extends = ['Permission', 'WebExtensionManifest']
    for item in types:
        for k, v in item.items():
            if k == '$extend':
                if v == 'Permission':
                    process_permission(types)
                    return
                elif v == 'WebExtensionManifest':
                    process_manifest(types)
                    return
            if k == 'id' and v == 'WebExtensionManifest':
                process_manifest([item])


def process_manifest(types):
    for manifest in types:
        if 'properties' in manifest:
            for key in manifest['properties'].keys():
                parsed_manifest['keys'].append(key)
        elif 'choices' in manifest:
            for choices in manifest['choices']:
                for enum in choices.get('enum', []):
                    parsed_manifest['permissions'].append(enum)


def process_permission(types):
    for permission in types:
        for item in permission['choices']:
            if 'enum' in item:
                for enum in item['enum']:
                    parsed_manifest['permissions'].append(enum)
            elif 'pattern' in item:
                parsed_manifest['permissions'].append(item['pattern'])


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
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('jinja-template.html')

    amo = json.load(open('addons.json', 'r'))
    amo = [get_from_amo(addon) for addon in amo]

    overall = json.load(open('addons-overview.json', 'r'))
    overall['total'] = sum(overall.values())

    apis = json.load(open('data.json', 'r'))
    apis = sorted(apis.items())

    parsed_usage = parse_usage()
    process_schemas(schema_locations)

    for api, data in apis:
        # Add in bugs.
        if GET_BUGS:
            data['bugs'] = bugs(api)['bugs']
        else:
            data['bugs'] = []

        # Add in schema.
        data['schema'] = parsed_schema.get(api, {})

        # Add in reason into the schema.
        for method in ['functions', 'events']:
            for api_name in data['schema'].get(method, []):
                data['schema'][method][api_name]['reasons'] = reasons.get(
                    data['schema'][method][api_name]['usage'], [])
                data['schema'][method][api_name]['rank'] = parsed_usage.get(
                    data['schema'][method][api_name]['usage'], [])

    data = {
        'apis': apis,
        'addons': amo,
        'overall': overall,
        'status_lookup': status_lookup,
        'parsed_manifest': parsed_manifest
    }

    html = template.render(data)
    open('index.html', 'w').write(html.encode('utf-8'))
