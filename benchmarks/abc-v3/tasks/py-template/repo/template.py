import re


def render(template, context):
    def sub(m):
        return str(context[m.group(1).strip()])
    return re.sub(r"\{\{(.*?)\}\}", sub, template)
