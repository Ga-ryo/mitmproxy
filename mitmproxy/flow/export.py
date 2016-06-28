from __future__ import absolute_import, print_function, division

import json
import re
from textwrap import dedent

from six.moves import urllib

import netlib.http


def dictstr(items, indent):
    lines = []
    for k, v in items:
        lines.append(indent + "%s: %s,\n" % (repr(k), repr(v)))
    return "{\n%s}\n" % "".join(lines)


def curl_command(flow):
    data = "curl "

    for k, v in flow.request.headers.fields:
        data += "-H '%s:%s' " % (k, v)

    if flow.request.method != "GET":
        data += "-X %s " % flow.request.method

    full_url = flow.request.scheme + "://" + flow.request.host + flow.request.path
    data += "'%s'" % full_url

    if flow.request.content:
        data += " --data-binary '%s'" % flow.request.content

    return data


def python_code(flow):
    code = dedent("""
        import requests

        url = '{url}'
        {headers}{params}{data}
        response = requests.request(
            method='{method}',
            url=url,{args}
        )

        print(response.text)
    """).strip()

    components = [urllib.parse.quote(c, safe="") for c in flow.request.path_components]
    url = flow.request.scheme + "://" + flow.request.host + "/" + "/".join(components)

    args = ""
    headers = ""
    if flow.request.headers:
        headers += "\nheaders = %s\n" % dictstr(flow.request.headers.fields, "    ")
        args += "\n    headers=headers,"

    params = ""
    if flow.request.query:
        params = "\nparams = %s\n" % dictstr(flow.request.query.collect(), "    ")
        args += "\n    params=params,"

    data = ""
    if flow.request.body:
        json_obj = is_json(flow.request.headers, flow.request.body)
        if json_obj:
            data = "\njson = %s\n" % dictstr(sorted(json_obj.items()), "    ")
            args += "\n    json=json,"
        else:
            data = "\ndata = '''%s'''\n" % flow.request.body
            args += "\n    data=data,"

    code = code.format(
        url=url,
        headers=headers,
        params=params,
        data=data,
        method=flow.request.method,
        args=args,
    )
    return code


def raw_request(flow):
    data = netlib.http.http1.assemble_request(flow.request)
    return data


def is_json(headers, content):
    if headers:
        ct = netlib.http.parse_content_type(headers.get("content-type", ""))
        if ct and "%s/%s" % (ct[0], ct[1]) == "application/json":
            try:
                return json.loads(content)
            except ValueError:
                return False
    return False


def locust_code(flow):
    code = dedent("""
        from locust import HttpLocust, TaskSet, task

        class UserBehavior(TaskSet):
            def on_start(self):
                ''' on_start is called when a Locust start before any task is scheduled '''
                self.{name}()

            @task()
            def {name}(self):
                url = '{url}'
                {headers}{params}{data}
                self.response = self.client.request(
                    method='{method}',
                    url=url,{args}
                )

            ### Additional tasks can go here ###


        class WebsiteUser(HttpLocust):
            task_set = UserBehavior
            min_wait = 1000
            max_wait = 3000
""").strip()

    components = [urllib.parse.quote(c, safe="") for c in flow.request.path_components]
    file_name = "_".join(components)
    name = re.sub('\W|^(?=\d)', '_', file_name)
    url = flow.request.scheme + "://" + flow.request.host + "/" + "/".join(components)
    if name == "" or name is None:
        new_name = "_".join([str(flow.request.host), str(flow.request.timestamp_start)])
        name = re.sub('\W|^(?=\d)', '_', new_name)
    args = ""
    headers = ""
    if flow.request.headers:
        lines = [(k, v) for k, v in flow.request.headers.fields if k.lower() not in ["host", "cookie"]]
        lines = ["            '%s': '%s',\n" % (k, v) for k, v in lines]
        headers += "\n        headers = {\n%s        }\n" % "".join(lines)
        args += "\n            headers=headers,"

    params = ""
    if flow.request.query:
        lines = ["            %s: %s,\n" % (repr(k), repr(v)) for k, v in flow.request.query.collect()]
        params = "\n        params = {\n%s        }\n" % "".join(lines)
        args += "\n            params=params,"

    data = ""
    if flow.request.body:
        data = "\n        data = '''%s'''\n" % flow.request.body
        args += "\n            data=data,"

    code = code.format(
        name=name,
        url=url,
        headers=headers,
        params=params,
        data=data,
        method=flow.request.method,
        args=args,
    )

    host = flow.request.scheme + "://" + flow.request.host
    code = code.replace(host, "' + self.locust.host + '")
    code = code.replace(quote_plus(host), "' + quote_plus(self.locust.host) + '")
    code = code.replace(quote(host), "' + quote(self.locust.host) + '")
    code = code.replace("'' + ", "")

    return code


def locust_task(flow):
    code = locust_code(flow)
    start_task = len(code.split('@task')[0]) - 4
    end_task = -19 - len(code.split('### Additional')[1])
    task_code = code[start_task:end_task]

    return task_code
