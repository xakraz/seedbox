import os
import json
from jinja2 import Environment, FileSystemLoader

import config
import models

jinja = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')), autoescape=False)


def render(node, url_root, indent=False):
    template_context = {
        'node': node,
        'cluster': node.cluster,
        'url_root': url_root,
        'config': config,
    }

    def get_unit(name, enable=False, dropins=None):
        if dropins:
            return {
                'name': name,
                'enable': enable,
                'dropins': [{
                    'name': dropin,
                    'contents': jinja.get_template('dropins/' + name + '/' + dropin).render(template_context),
                } for dropin in dropins],
            }
        else:
            return {
                'name': name,
                'enable': enable,
                'contents': jinja.get_template('units/' + name).render(template_context),
            }

    units = [
        get_unit('provision-report.service', enable=True),
        get_unit('credentials@.service'),
        get_unit('credentials-all.service'),
    ]

    if node.is_etcd_server:
        etcd_version = node.cluster.etcd_version
        if etcd_version == 2:
            unit_name = 'etcd2.service'
        elif etcd_version == 3:
            unit_name = 'etcd-member.service'
        else:
            raise Exception('Unknown etcd version', etcd_version)
        units.append(get_unit(unit_name, enable=True, dropins=['40-etcd-cluster.conf']))
        units.append(get_unit('locksmithd.service', dropins=['40-etcd-lock.conf']))

    ssh_keys = [user.ssh_key for user in node.cluster.users.filter(models.User.ssh_key != '')]

    cfg = {
        'ignition': {
            'version': '2.0.0',
            'config': {},
        },
        'storage': {},
        'networkd': {},
        'passwd': {
            'users': [{
                'name': 'core',
                'ssh_authorized_keys': ssh_keys,
            }],
        },
        'systemd': {
            'units': units,
        },
    }

    if indent:
        return json.dumps(cfg, indent=2)
    else:
        return json.dumps(cfg, separators=(',', ':'))