import logging

from flask import Flask, Response, request, abort, redirect
from flask_migrate import Migrate

from seedbox import config, models, config_renderer
from seedbox.admin import admin


log = logging.getLogger(__name__)


app = Flask(__name__, template_folder='admin/templates')
app.secret_key = config.secret_key
app.config['SQLALCHEMY_DATABASE_URI'] = config.database_uri
models.db.app = app
models.db.init_app(app)
migrate = Migrate(app, models.db)
admin.init_app(app)


def get_node(node_ip):
    node = models.Node.query.filter_by(ip=node_ip).first()
    if node is None:
        log.error('Node %s is unknown', node_ip)
        abort(403)
    return node


def route(rule, request_name, secure=True, **route_kwargs):
    def decorator(func):
        def wrapped(*args, **kwargs):
            node_ip = request.remote_addr
            log.info('%s request from %s', request_name, node_ip)
            node = get_node(node_ip)

            is_request_secure = request.environ['wsgi.url_scheme'] == 'https'
            if secure and not is_request_secure and not node.cluster.allow_insecure_provision:
                if request.method in ('POST', 'PUT', 'PATCH'):
                    # request body already sent in insecure manner
                    # return error in this case to notify cluster admin
                    abort(400)
                else:
                    return redirect(request.url.replace('http://', 'https://', 1))

            return func(node, *args, **kwargs)

        wrapped.__name__ = func.__name__
        return app.route(rule, **route_kwargs)(wrapped)
    return decorator


@route('/ipxe', 'iPXE boot', secure=False)
def ipxe_boot(node):
    response = config_renderer.ipxe.render(node, request.url_root)
    return Response(response, mimetype='text/plain')


@route('/ignition', 'Ignition config')
def ignition(node):
    response = config_renderer.ignition.render(node, 'indent' in request.args)
    return Response(response, mimetype='application/json')


@route('/credentials/<cred_type>.pem', 'Credentials download')
def credentials(node, cred_type):
    if cred_type == 'ca':
        return Response(node.cluster.ca_credentials.cert, mimetype='text/plain')

    if cred_type == 'node':
        return Response(node.credentials.cert, mimetype='text/plain')

    if cred_type == 'node-key':
        return Response(node.credentials.key, mimetype='text/plain')

    abort(404)


@route('/report', 'Provision report', methods=['POST'])
def report(node):
    if not node.maintenance_mode:
        node.active_config_version = request.args.get('version')
        if node.active_config_version is None:
            abort(400)

        ignition_config = request.get_json()
        if ignition_config is None:
            abort(400)

        node.active_ignition_config = request.data

    node.wipe_root_disk_next_boot = False

    models.db.session.add(node)
    models.db.session.commit()

    return Response('ok', mimetype='application/json')


@app.route('/manifests/<cluster_name>/kube-system-role-binding.yaml')
def k8s_manifest(cluster_name):
    # TODO: not ready for multitenancy
    cluster = models.Cluster.query.filter_by(name=cluster_name).first()
    if cluster is None:
        abort(404)
    return Response(config_renderer.manifests.render_yaml(cluster, 'kube-system-role-binding.yaml'),
                    mimetype='text/x-yaml')


@app.route('/helm/<cluster_name>/k8s-addons.tar.gz')
def k8s_addons_helm_chart(cluster_name):
    # TODO: not ready for multitenancy
    cluster = models.Cluster.query.filter_by(name=cluster_name).first()
    if cluster is None:
        abort(404)
    return Response(config_renderer.charts.render_tgz(cluster, 'k8s-addons'), mimetype='application/tar+gzip')
