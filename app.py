"""
quebec_gisoo package
app module
REST API application for city GIS cleaning components.

Project Designer and Developer: Alireza Adli
alireza.adli@mail.concordia.ca
alireza.adli4@gmail.com
www.demianadli.com
"""

import logging
import secrets
from time import perf_counter

from flask import Flask, g, request
from flask_smorest import Api
from werkzeug.exceptions import HTTPException

try:
    from quebec_gisoo.logging_setup import configure_service_logging
    from quebec_gisoo.resources.gis_components import (
        blp as gis_components_blueprint,
    )
except ModuleNotFoundError:
    from src.quebec_gisoo.logging_setup import configure_service_logging
    from src.quebec_gisoo.resources.gis_components import (
        blp as gis_components_blueprint,
    )

from sabu_chassis.logging.context import get_request_id, set_request_id


configure_service_logging('quebec_gisoo-api')
logger = logging.getLogger(__name__)

app = Flask(__name__)

app.config['PROPAGATE_EXCEPTIONS'] = True
app.config['API_TITLE'] = 'Quebec GISOO Workflow API'
app.config['API_VERSION'] = 'v1'
app.config['OPENAPI_VERSION'] = '3.0.2'
app.config['OPENAPI_URL_PREFIX'] = '/'
app.config['OPENAPI_SWAGGER_UI_PATH'] = '/swagger-ui'
app.config['OPENAPI_SWAGGER_UI_URL'] = (
    'https://cdn.jsdelivr.net/npm/swagger-ui-dist/'
)

api = Api(app)
api.register_blueprint(gis_components_blueprint)


@app.before_request
def _before():
    request_id = (
        request.headers.get('X-Request-ID')
        or request.headers.get('X-Correlation-ID')
        or secrets.token_hex(8)
    )
    set_request_id(request_id)
    g._t0 = perf_counter()


@app.after_request
def _after(response):
    try:
        duration_ms = int(
            (perf_counter() - getattr(g, '_t0', perf_counter())) * 1000
        )
        client_ip = request.headers.get(
            'X-Forwarded-For',
            request.remote_addr,
        )
        logger.info(
            'http_request',
            extra={
                'method': request.method,
                'path': request.path,
                'status': response.status_code,
                'latency_ms': duration_ms,
                'client_ip': client_ip,
            },
        )
        response.headers['X-Request-ID'] = get_request_id()
    finally:
        return response


@app.errorhandler(Exception)
def _unhandled(error):
    if isinstance(error, HTTPException):
        return error
    logger.exception('unhandled_exception')
    return {'message': 'Internal Server Error'}, 500
