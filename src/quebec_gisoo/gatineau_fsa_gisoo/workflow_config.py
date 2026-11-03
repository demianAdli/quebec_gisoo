"""
quebec_gisoo package
Municipality: Gatineau FSA
workflow_config module

Project Designer and Developer: Alireza Adli
alireza.adli@mail.concordia.ca
alireza.adli4@gmail.com
www.demianadli.com
"""

import os
import re


_FSA_PATTERN = re.compile(r'^[A-Z][0-9][A-Z]$')

default_data_dir = 'D:/GIS/quebec_gisoo/gatineau/run_gatineau'
data_dir = os.getenv(
  'QUEBEC_GISOO_GATINEAU_FSA_DATA_DIR',
  default_data_dir)
input_data_dir = os.path.join(data_dir, 'input_data')

# Application's path
qgis_path = os.getenv(
    'QUEBEC_GISOO_QGIS_PATH',
    'C:/Program Files/QGIS 3.34.1/apps/qgis')

# Gathering input data layers paths
input_paths = {
  'gatineau_property_roll_2025':
  os.path.join(
    input_data_dir,
    'role_2025_unit_eval_et_address',
    'roll_gatineau.gpkg'),
  'gatineau_nrcan_heights':
  os.path.join(
    input_data_dir,
    'auto_buildings',
    'auto_height_gatineau.gpkg'),
  'gatineau_nrcan_preserved':
  os.path.join(
    input_data_dir,
    'auto_buildings_preserved',
    'auto_height_gatineau_preserved.gpkg'),
  'gatineau_mahm_usage_2026_gpkg':
  os.path.join(
    input_data_dir,
    'mamh_usage_predo_2026',
    'mahm_gatineau_2026.gpkg'),
  'gatineau_usage_dup':
  os.path.join(
    input_data_dir,
    'mamh_usage_predo_2026_dup',
    'mahm_gatineau_2026_dup.gpkg'),
  'fsa':
  os.path.join(
    input_data_dir,
    'fsa_boundaries',
    'gatineau_fsa.gpkg')
}
fsa_field_name = 'g_fsa'

nrcan_usage_roll_unnecessary_fields = []

# Defining a directory for all the output data layers
output_paths_dir = os.getenv(
  'QUEBEC_GISOO_GATINEAU_FSA_OUTPUT_DIR',
  os.path.join(data_dir, 'output_data'))


def normalize_fsa(fsa):
  if fsa is None:
    raise ValueError('fsa is required for the Montreal FSA workflow.')
  if not isinstance(fsa, str):
    raise TypeError('fsa must be a string.')

  normalized_fsa = fsa.strip().upper()
  if not _FSA_PATTERN.match(normalized_fsa):
    raise ValueError(
      'fsa must be a three-character Canadian FSA, for example H3H.')
  return normalized_fsa


def get_fsa_output_paths_dir(fsa):
  return os.path.join(output_paths_dir, normalize_fsa(fsa))


# Preparing a bedding for output data layers paths
output_paths = {
  'fsa_boundary': '',
  'nrcan_preserved': '',
  'usage_dup': '',
  'nrcan': '',
  'usage': '',
  'roll': '',
  'nrcan_fixed': '',
  'nrcan_preserved_fixed': '',
  'usage_fixed': '',
  'usage_dup_fixed': '',
  'usage_margin_san': '',
  'usage_clean': '',
  'usage_margin': '',
  'usage_only': '',
  'roll_only': '',
  'usage_roll_only_all': '',
  'usage_roll_only': '',
  'usage_roll_only_unique': '',
  'roll_clean': '',
  'usage_roll': '',
  'usage_roll_all': '',
  'usage_dup_clean': '',
  'inter_nrcan': '',
  'inter_summary': '',
  'summary_joined': '',
  'inter_kept': '',
  'nrcan_joined_summary': '',
  'nrcan_restored': '',
  'dominant_parts': '',
  'nrcan_restored_with_usage_id': '',
  'nrcan_intersected': '',
  'nrcan_intersected_points': '',
  'nrcan_in_usage_roll_points': '',
  'nrcan_usage_roll_with_missing': '',
  'usage_roll_all_only': '',
  'nrcan_usage_roll': '',
  'gatineau_{fsa}_gisoo': '',
  'gatineau_{fsa}_gisoo_standardized': '',
}

# Outputs retained when opt-in cleanup is enabled.
default_retained_output_keys = frozenset({
  'fsa_boundary',
  'nrcan_fixed',
  'roll',
  'usage_fixed',
  'gatineau_{fsa}_gisoo',
  'gatineau_{fsa}_gisoo_standardized',
})