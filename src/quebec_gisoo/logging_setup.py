"""
QuebecGISOO project
Logging defaults for quebec_gisoo entrypoints.
Project Designer and Developer: Alireza Adli
alireza.adli@mail.concordia.ca
alireza.adli4@gmail.com
www.demianadli.com
"""
from __future__ import annotations

import os
from pathlib import Path

from sabu_chassis.logging import configure_logging


DEFAULT_LOG_FILE_NAME = 'logs/quebec_gisoo.log'


def _service_root():
    return Path(__file__).resolve().parents[2]


def configure_service_logging(service_name):
    """Configure sabu-chassis logging with quebec_gisoo file defaults."""
    os.environ.setdefault('LOG_SERVICE', service_name)
    os.environ.setdefault('LOG_DIR_BASE', str(_service_root()))
    os.environ.setdefault('LOG_FILE_NAME', DEFAULT_LOG_FILE_NAME)
    configure_logging()
