"""
quebec_gisoo package
Municipality: Gatineau FSA
output_cleanup module
Safe cleanup of generated Gatineau FSA workflow outputs.

Project Designer and Developer: Alireza Adli
alireza.adli@mail.concordia.ca
alireza.adli4@gmail.com
www.demianadli.com
"""
from __future__ import annotations

import gc
import os
import shutil
import time
from pathlib import Path

from sabu_chassis.logging import get_logger

try:
    from . import workflow_config as paths
except ImportError:
    import workflow_config as paths


logger = get_logger(__name__)
