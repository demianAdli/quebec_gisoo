"""
quebec_gisoo package
Municipality: Gatineau FSA
workflow module
Cleaning and updating Gatineau buildings by FSA district.

Project Designer and Developer: Alireza Adli
alireza.adli@mail.concordia.ca
alireza.adli4@gmail.com
www.demianadli.com
"""

import argparse
import os
from contextlib import contextmanager
from time import perf_counter

from citygisoo import GeoPackageFeatureProcessor
from citygisoo.scrub_layer_class import ScrubLayer
from sabu_chassis.logging import configure_logging, get_logger

try:
  from . import workflow_config as paths
except ImportError:
  import workflow_config as paths


logger = get_logger(__name__)


@contextmanager
def _workflow_step(step_name, fsa):
  step_t0 = perf_counter()
  logger.info('Starting Gatineau %s workflow step: %s.', fsa, step_name)
  try:
    yield
  except Exception:
    logger.error(
      'Failed Gatineau %s workflow step: %s after %.3fs.',
      fsa,
      step_name,
      perf_counter() - step_t0)
    raise
  logger.info(
    'Completed Gatineau %s workflow step: %s in %.3fs.',
    fsa,
    step_name,
    perf_counter() - step_t0)


def _log_layer_summary(layer):
  logger.info('%s', layer)


def _resolve_output_key(output_key, fsa):
  return output_key.format(fsa=fsa)


def _create_geopackage_output_paths(output_paths, output_paths_dir, fsa):
  resolved_output_paths = {}
  for output_key in output_paths:
    resolved_key = _resolve_output_key(output_key, fsa)
    output_folder = os.path.join(output_paths_dir, resolved_key)
    os.makedirs(output_folder, exist_ok=True)
    resolved_output_paths[resolved_key] = os.path.join(
      output_folder,
      f'{resolved_key}.gpkg')
  output_paths.clear()
  output_paths.update(resolved_output_paths)


def _load_output_layer(output_paths, output_key, fsa, layer_name=None):
  loaded_layer = ScrubLayer(
    paths.qgis_path,
    output_paths[output_key],
    layer_name or f'{output_key}_{fsa}')
  loaded_layer.create_spatial_index()
  _log_layer_summary(loaded_layer)
  return loaded_layer


def run_workflow(fsa):
  """Run the Gatineau FSA GISOO cleaning workflow."""
  normalized_fsa = paths.normalize_fsa(fsa)
  output_paths = dict(paths.output_paths)
  output_paths_dir = paths.get_fsa_output_paths_dir(normalized_fsa)
  processor = GeoPackageFeatureProcessor()
  workflow_t0 = perf_counter()
  logger.info(
    'Starting Gatineau FSA GISOO workflow. FSA=%s Output directory=%s',
    normalized_fsa,
    output_paths_dir)

  try:
    with _workflow_step('prepare output folders', normalized_fsa):
      _create_geopackage_output_paths(
        output_paths,
        output_paths_dir,
        normalized_fsa)

    with _workflow_step('load input layers', normalized_fsa):
      roll_Gatineau = ScrubLayer(
        paths.qgis_path,
        paths.input_paths['gatineau_property_roll_2025'],
        'roll_Gatineau')
      nrcan_Gatineau = ScrubLayer(
        paths.qgis_path,
        paths.input_paths['gatineau_nrcan_heights'],
        'nrcan_Gatineau')
      nrcan_preserved_Gatineau = ScrubLayer(
        paths.qgis_path,
        paths.input_paths['gatineau_nrcan_preserved'],
        'nrcan_preserved_Gatineau')
      usage_Gatineau = ScrubLayer(
        paths.qgis_path,
        paths.input_paths['gatineau_mahm_usage_2026_gpkg'],
        'usage_Gatineau')
      usage_dup_Gatineau = ScrubLayer(
        paths.qgis_path,
        paths.input_paths['gatineau_usage_dup'],
        'usage_dup_Gatineau')
      fsa_layer = ScrubLayer(
        paths.qgis_path,
        paths.input_paths['fsa'],
        'fsa_boundaries')
      _log_layer_summary(roll_Gatineau)
      _log_layer_summary(nrcan_Gatineau)
      _log_layer_summary(nrcan_preserved_Gatineau)
      _log_layer_summary(usage_Gatineau)
      _log_layer_summary(usage_dup_Gatineau)
      _log_layer_summary(fsa_layer)

    with _workflow_step('extract FSA boundary', normalized_fsa):
      fsa_layer.extract_by_attribute(
        paths.fsa_field_name,
        '=',
        normalized_fsa,
        output_paths['fsa_boundary'])
      fsa_boundary = _load_output_layer(
        output_paths,
        'fsa_boundary',
        normalized_fsa)
      if fsa_boundary.data_count != 1:
        raise ValueError(
          f'Expected exactly one Gatineau FSA boundary for {normalized_fsa}; '
          f'found {fsa_boundary.data_count}.')

    with _workflow_step('clip input layers to FSA boundary', normalized_fsa):
      nrcan_Gatineau.clip_layer(
        fsa_boundary.layer_path,
        output_paths['nrcan'])
      nrcan = _load_output_layer(
        output_paths,
        'nrcan',
        normalized_fsa,
        layer_name=f'nrcan_clipped_{normalized_fsa}')

      nrcan_preserved_Gatineau.clip_layer(
        fsa_boundary.layer_path,
        output_paths['nrcan_preserved'])
      nrcan_preserved = _load_output_layer(
        output_paths,
        'nrcan_preserved',
        normalized_fsa)

      roll_Gatineau.clip_layer(
        fsa_boundary.layer_path,
        output_paths['roll'])
      roll = _load_output_layer(
        output_paths,
        'roll',
        normalized_fsa,
        layer_name=f'roll_clipped_{normalized_fsa}')

      usage_Gatineau.clip_layer(
        fsa_boundary.layer_path,
        output_paths['usage'])
      usage = _load_output_layer(
        output_paths,
        'usage',
        normalized_fsa,
        layer_name=f'usage_clipped_{normalized_fsa}')

      usage_dup_Gatineau.clip_layer(
        fsa_boundary.layer_path,
        output_paths['usage_dup'])
      usage_dup = _load_output_layer(
        output_paths,
        'usage_dup',
        normalized_fsa)

    with _workflow_step('fix nrcan geometries', normalized_fsa):
      nrcan.fix_geometries(output_paths['nrcan_fixed'])
      nrcan_fixed = _load_output_layer(
        output_paths,
        'nrcan_fixed',
        normalized_fsa)

    with _workflow_step('assign nrcan area field', normalized_fsa):
      processor.add_area_field(nrcan_fixed, 'nrcan_area')

    with _workflow_step('fix nrcan preserved geometries', normalized_fsa):
      nrcan_preserved.fix_geometries(output_paths['nrcan_preserved_fixed'])
      nrcan_preserved_fixed = _load_output_layer(
        output_paths,
        'nrcan_preserved_fixed',
        normalized_fsa)

    with _workflow_step('assign nrcan preserved area field', normalized_fsa):
      processor.add_area_field(nrcan_preserved_fixed, 'nrcan_area')

    with _workflow_step('fix usage geometries', normalized_fsa):
      usage.fix_geometries(output_paths['usage_fixed'])
      usage_fixed = _load_output_layer(
        output_paths,
        'usage_fixed',
        normalized_fsa)

    with _workflow_step('fix usage duplicate geometries', normalized_fsa):
      usage_dup.fix_geometries(output_paths['usage_dup_fixed'])
      usage_dup_fixed = _load_output_layer(
        output_paths,
        'usage_dup_fixed',
        normalized_fsa)

    # Procedure: Roll joins Usage Workflow
    with _workflow_step('extract usage records missing from roll',
                        normalized_fsa):
      processor.extract_by_membership(
        source_layer=usage_fixed,
        lookup_layer=roll,
        source_field='g_id_provi',
        lookup_field='id_provinc',
        output_path=output_paths['usage_margin_san'],
        include_matches=False,
        layer_name=f'usage_margin_san_{normalized_fsa}')
      usage_margin_san = _load_output_layer(
        output_paths,
        'usage_margin_san',
        normalized_fsa)

    with _workflow_step('difference usage with usage margin san',
                        normalized_fsa):
      usage.difference_layer(
        overlay_layer=usage_margin_san,
        output_path=output_paths['usage_clean'])
      usage_clean = _load_output_layer(
        output_paths,
        'usage_clean',
        normalized_fsa)

    with _workflow_step('extract usage margin records with provincial id',
                        normalized_fsa):
      processor.extract_where(
        source_layer=usage_margin_san,
        predicate=(
          lambda feature:
          processor.is_not_null_value(feature['g_id_provi'])
          and feature['g_id_provi'] != 'Sans correspondance'),
        output_path=output_paths['usage_margin'],
        layer_name=f'usage_margin_{normalized_fsa}')
      usage_margin = _load_output_layer(
        output_paths,
        'usage_margin',
        normalized_fsa)

    with _workflow_step('assign usage margin area field', normalized_fsa):
      processor.add_area_field(usage_margin, 'area_ex')

    with _workflow_step('extract usage-only records by area',
                        normalized_fsa):
      processor.extract_where(
        source_layer=usage_margin,
        predicate=(
          lambda feature:
          processor.is_not_null_value(feature['area_ex'])
          and processor.is_not_null_value(feature['g_sup_tota'])
          and float(feature['area_ex']) > 0.9 * float(feature['g_sup_tota'])),
        output_path=output_paths['usage_only'],
        layer_name=f'usage_only_{normalized_fsa}')
      usage_only = _load_output_layer(
        output_paths,
        'usage_only',
        normalized_fsa)

    with _workflow_step('extract roll records missing from usage',
                        normalized_fsa):
      processor.extract_by_membership(
        source_layer=roll,
        lookup_layer=usage,
        source_field='id_provinc',
        lookup_field='g_id_provi',
        output_path=output_paths['roll_only'],
        include_matches=False,
        layer_name=f'roll_only_{normalized_fsa}')
      roll_only = _load_output_layer(
        output_paths,
        'roll_only',
        normalized_fsa)

    with _workflow_step('spatial join usage with roll-only',
                        normalized_fsa):
      usage.spatial_join_with_predicate(
        joining_layer_path=roll_only.layer_path,
        joined_layer_path=output_paths['usage_roll_only_all'],
        predicate='contains',
        join_method='one-to-many',
        prefix='ro_')
      usage_roll_only_all = _load_output_layer(
        output_paths,
        'usage_roll_only_all',
        normalized_fsa)

    with _workflow_step('extract usage-roll-only matched records',
                        normalized_fsa):
      processor.extract_where(
        source_layer=usage_roll_only_all,
        predicate=(
          lambda feature:
          processor.is_not_null_value(feature['ro_roll_id'])),
        output_path=output_paths['usage_roll_only'],
        layer_name=f'usage_roll_only_{normalized_fsa}')
      usage_roll_only = _load_output_layer(
        output_paths,
        'usage_roll_only',
        normalized_fsa)

    with _workflow_step('extract unique usage-roll-only records',
                        normalized_fsa):
      processor.extract_unique_by_field(
        source_layer=usage_roll_only,
        field_name='ro_id_provinc',
        output_path=output_paths['usage_roll_only_unique'],
        include_null=False,
        layer_name=f'usage_roll_only_unique_{normalized_fsa}')
      usage_roll_only_unique = _load_output_layer(
        output_paths,
        'usage_roll_only_unique',
        normalized_fsa)

    with _workflow_step('difference roll with roll-only', normalized_fsa):
      roll.difference_layer(
        overlay_layer=roll_only,
        output_path=output_paths['roll_clean'])
      roll_clean = _load_output_layer(
        output_paths,
        'roll_clean',
        normalized_fsa)

    with _workflow_step('duplicate roll provincial id field',
                        normalized_fsa):
      roll_clean.duplicate_text_field(
        source_field='id_provinc',
        target_field='r_id_provinc',
        field_length=36)

    with _workflow_step('join usage clean with roll clean',
                        normalized_fsa):
      usage_clean.add_layer_join(
        joining_layer_path=roll_clean.layer_path,
        joining_layer_name=roll_clean.layer_name,
        join_field='r_id_provinc',
        target_field='g_id_provi',
        prefix='r_',
        output_path=output_paths['usage_roll'])
      usage_roll = _load_output_layer(
        output_paths,
        'usage_roll',
        normalized_fsa)

    with _workflow_step('merge usage roll layers', normalized_fsa):
      ScrubLayer.merge_layer_paths(
        layer_paths=[
          usage_roll.layer_path,
          usage_only.layer_path,
          usage_roll_only_unique.layer_path,
        ],
        output_path=output_paths['usage_roll_all'])
      usage_roll_all = _load_output_layer(
        output_paths,
        'usage_roll_all',
        normalized_fsa)

    with _workflow_step('assign usage roll uuid field', normalized_fsa):
      usage_roll_all.assign_field_expression(
        target_field='usage_roll_id',
        expression="replace(replace(uuid(), '{', ''), '}', '')",
        field_type=10,
        field_length=36)

    # Procedure: NRCan Intersection by Usage begins from here.
    with _workflow_step('delete duplicate usage geometries', normalized_fsa):
      usage_dup_fixed.delete_duplicate_geometries(
        output_paths['usage_dup_clean'])
      clean_usage_dup = _load_output_layer(
        output_paths,
        'usage_dup_clean',
        normalized_fsa)

    with _workflow_step('intersect nrcan with clean usage duplicate',
                        normalized_fsa):
      nrcan_fixed.intersection_layer(
        overlay_layer=clean_usage_dup,
        output_path=output_paths['inter_nrcan'],
        overlay_fields=['usage_id'])
      inter_nrcan = _load_output_layer(
        output_paths,
        'inter_nrcan',
        normalized_fsa)

    with _workflow_step('assign inter nrcan area field', normalized_fsa):
      processor.add_area_field(inter_nrcan, 'inter_area')

    with _workflow_step('assign inter nrcan area ratio field',
                        normalized_fsa):
      processor.add_ratio_field(
        inter_nrcan,
        target_field='area_ratio',
        numerator_field='inter_area',
        denominator_field='nrcan_area')

    with _workflow_step('summarize inter nrcan by nrcan id',
                        normalized_fsa):
      processor.aggregate_by_group(
        source_layer=inter_nrcan,
        group_field='nrcan_id',
        aggregates=[
          {
            'output_field': 'nrcan_id',
            'aggregate_function': 'first_value',
            'input_field': 'nrcan_id',
            'field_type': 10,
          },
          {
            'output_field': 'number_parts',
            'aggregate_function': 'count',
            'input_field': 'nrcan_id',
            'field_type': 2,
          },
          {
            'output_field': 'min_inter_area',
            'aggregate_function': 'minimum',
            'input_field': 'inter_area',
            'field_type': 6,
          },
          {
            'output_field': 'max_inter_area',
            'aggregate_function': 'maximum',
            'input_field': 'inter_area',
            'field_type': 6,
          },
          {
            'output_field': 'max_area_ratio',
            'aggregate_function': 'maximum',
            'input_field': 'area_ratio',
            'field_type': 6,
          },
          {
            'output_field': 'nrcan_area',
            'aggregate_function': 'first_value',
            'input_field': 'nrcan_area',
            'field_type': 6,
          },
          {
            'output_field': 'sum_inter_area',
            'aggregate_function': 'sum',
            'input_field': 'inter_area',
            'field_type': 6,
          },
          {
            'output_field': 'sum_area_ratio',
            'aggregate_function': 'sum',
            'input_field': 'area_ratio',
            'field_type': 6,
          },
        ],
        output_path=output_paths['inter_summary'],
        layer_name=f'inter_summary_{normalized_fsa}')
      inter_summary = _load_output_layer(
        output_paths,
        'inter_summary',
        normalized_fsa)

    with _workflow_step('assign inter summary restore group field',
                        normalized_fsa):
      inter_summary.assign_field_expression(
        target_field='restore_group',
        expression=(
          'CASE\n'
          'WHEN\n'
          '    "number_parts" > 1\n'
          '    AND "min_inter_area" < 30\n'
          '    AND "max_area_ratio" >= 0.70\n'
          'THEN 1\n'
          'WHEN\n'
          '    "number_parts" >= 3\n'
          '    AND "nrcan_area" <= 75\n'
          '    AND "max_inter_area" < 30\n'
          '    AND "sum_area_ratio" >= 0.95\n'
          'THEN 1\n'
          'ELSE 0\n'
          'END'),
        field_type=2)

    with _workflow_step('assign inter summary restore reason field',
                        normalized_fsa):
      inter_summary.assign_field_expression(
        target_field='restore_reason',
        expression=(
          'CASE\n'
          'WHEN\n'
          '    "number_parts" > 1\n'
          '    AND "min_inter_area" < 30\n'
          '    AND "max_area_ratio" >= 0.70\n'
          "THEN 'dominant_piece'\n"
          'WHEN\n'
          '    "number_parts" >= 3\n'
          '    AND "nrcan_area" <= 75\n'
          '    AND "max_inter_area" < 30\n'
          '    AND "sum_area_ratio" >= 0.95\n'
          "THEN 'small_building_multi_split'\n"
          "ELSE 'keep'\n"
          'END'),
        field_type=10,
        field_length=32)

    with _workflow_step('join inter summary with inter nrcan',
                        normalized_fsa):
      inter_nrcan.field_join(
        joining_layer_path=inter_summary.layer_path,
        joining_layer_name=inter_summary.layer_name,
        target_field='nrcan_id',
        join_field='nrcan_id',
        join_fields=[
          'restore_group',
          'restore_reason',
          'number_parts',
          'min_inter_area',
          'max_inter_area',
          'max_area_ratio',
        ],
        prefix='sum_',
        output_path=output_paths['summary_joined'],
        selected_features_only=False,
        joining_selected_features_only=False,
        join_method='first match',
        discard_nonmatching=False)
      summary_joined = _load_output_layer(
        output_paths,
        'summary_joined',
        normalized_fsa)

    with _workflow_step('extract kept summary joined records',
                        normalized_fsa):
      processor.extract_where(
        source_layer=summary_joined,
        predicate=(
          lambda feature:
          feature['sum_restore_group'] == 0
          or processor.is_null_value(feature['sum_restore_group'])),
        output_path=output_paths['inter_kept'],
        layer_name=f'inter_kept_{normalized_fsa}')
      inter_kept = _load_output_layer(
        output_paths,
        'inter_kept',
        normalized_fsa)

    with _workflow_step('join nrcan with inter summary', normalized_fsa):
      nrcan_preserved_fixed.field_join(
        joining_layer_path=inter_summary.layer_path,
        joining_layer_name=inter_summary.layer_name,
        target_field='nrcan_id',
        join_field='nrcan_id',
        join_fields=[
          'restore_group',
          'restore_reason',
        ],
        output_path=output_paths['nrcan_joined_summary'])
      nrcan_joined_summary = _load_output_layer(
        output_paths,
        'nrcan_joined_summary',
        normalized_fsa)

    with _workflow_step('extract nrcan restored records', normalized_fsa):
      processor.extract_where(
        source_layer=nrcan_joined_summary,
        predicate=(
          lambda feature:
          feature['restore_group'] == 1),
        output_path=output_paths['nrcan_restored'],
        layer_name=f'nrcan_restored_{normalized_fsa}')
      nrcan_restored = _load_output_layer(
        output_paths,
        'nrcan_restored',
        normalized_fsa)

    with _workflow_step('extract dominant summary joined parts',
                        normalized_fsa):
      processor.extract_where(
        source_layer=summary_joined,
        predicate=(
          lambda feature:
          feature['sum_restore_group'] == 1
          and feature['inter_area'] == feature['sum_max_inter_area']),
        output_path=output_paths['dominant_parts'],
        layer_name=f'dominant_parts_{normalized_fsa}')
      dominant_parts = _load_output_layer(
        output_paths,
        'dominant_parts',
        normalized_fsa)

    with _workflow_step('join nrcan restored with dominant usage id',
                        normalized_fsa):
      nrcan_restored.field_join(
        joining_layer_path=dominant_parts.layer_path,
        joining_layer_name=dominant_parts.layer_name,
        target_field='nrcan_id',
        join_field='nrcan_id',
        join_fields=['usage_id'],
        output_path=output_paths['nrcan_restored_with_usage_id'])
      nrcan_restored_with_usage_id = _load_output_layer(
        output_paths,
        'nrcan_restored_with_usage_id',
        normalized_fsa)

    with _workflow_step('merge kept and restored nrcan intersections',
                        normalized_fsa):
      nrcan_intersected_layer_name = (
        f'c_nrcan_intersected_{normalized_fsa}')
      ScrubLayer.merge_layer_paths(
        layer_paths=[
          inter_kept.layer_path,
          nrcan_restored_with_usage_id.layer_path,
        ],
        output_path=output_paths['nrcan_intersected'])
      nrcan_intersected = _load_output_layer(
        output_paths,
        'nrcan_intersected',
        normalized_fsa,
        layer_name=nrcan_intersected_layer_name)

    # Procedure: Joining usage_roll_all attributes to the
    # nrcan_intersected features

    with _workflow_step('assign nrcan intersected uuid field',
                        normalized_fsa):
      nrcan_intersected.assign_field_expression(
        target_field='nrcan_in_id',
        expression="replace(replace(uuid(), '{', ''), '}', '')",
        field_type=10,
        field_length=36)

    with _workflow_step('create nrcan intersected points', normalized_fsa):
      nrcan_intersected.point_on_surface(
        output_path=output_paths['nrcan_intersected_points'])
      nrcan_intersected_points = _load_output_layer(
        output_paths,
        'nrcan_intersected_points',
        normalized_fsa,
        layer_name='nrcan_intersected_points')

    with _workflow_step('spatial join nrcan intersected points with usage roll',
                        normalized_fsa):
      nrcan_intersected_points.spatial_join_with_predicate(
        joining_layer_path=usage_roll_all.layer_path,
        joined_layer_path=output_paths['nrcan_in_usage_roll_points'],
        predicate='within',
        join_method='one-to-many',
        prefix='ur_')
      nrcan_in_usage_roll_points = _load_output_layer(
        output_paths,
        'nrcan_in_usage_roll_points',
        normalized_fsa)

    with _workflow_step('restore nrcan geometry on usage roll points',
                        normalized_fsa):
      nrcan_in_usage_roll_points.geometry_by_expression(
        expression=(
          "geometry(\n"
          "    get_feature(\n"
          f"        '{nrcan_intersected_layer_name}',\n"
          "        'nrcan_in_id',\n"
          "        attribute(@feature, 'nrcan_in_id')\n"
          "    )\n"
          ")"),
        output_path=output_paths['nrcan_usage_roll_with_missing'],
        output_geometry_type='polygon')
      nrcan_usage_roll_with_missing = _load_output_layer(
        output_paths,
        'nrcan_usage_roll_with_missing',
        normalized_fsa,
        layer_name='nrcan_usage_roll_with_missing')

    with _workflow_step('extract usage roll missing nrcan geometry',
                        normalized_fsa):
      processor.extract_by_membership(
        source_layer=usage_roll_all,
        lookup_layer=nrcan_usage_roll_with_missing,
        source_field='id_provinc',
        lookup_field='ur_id_provinc',
        output_path=output_paths['usage_roll_all_only'],
        include_matches=False,
        layer_name=f'usage_roll_all_only_{normalized_fsa}')
      usage_roll_all_only = _load_output_layer(
        output_paths,
        'usage_roll_all_only',
        normalized_fsa)

    with _workflow_step('merge nrcan usage roll layers',
                        normalized_fsa):
      ScrubLayer.merge_layer_paths(
        layer_paths=[
          nrcan_usage_roll_with_missing.layer_path,
          usage_roll_all_only.layer_path,
        ],
        output_path=output_paths['nrcan_usage_roll'])
      nrcan_usage_roll = _load_output_layer(
        output_paths,
        'nrcan_usage_roll',
        normalized_fsa)

    with _workflow_step('assign nrcan usage roll FSA field',
                        normalized_fsa):
      nrcan_usage_roll.assign_field_expression(
        target_field='FSA',
        expression=f"'{normalized_fsa}'",
        field_type=10,
        field_length=3)

    with _workflow_step('assign nrcan usage roll citygisoo id field',
                        normalized_fsa):
      nrcan_usage_roll.assign_field_expression(
        target_field='citygisoo_id',
        expression="replace(replace(uuid(), '{', ''), '}', '')",
        field_type=10,
        field_length=36)

    with _workflow_step('assign nrcan usage roll citygisoo area field',
                        normalized_fsa):
      processor.add_area_field(nrcan_usage_roll, 'citygisoo_area')

    with _workflow_step('assign nrcan usage roll processing tool field',
                        normalized_fsa):
      nrcan_usage_roll.assign_field_expression(
        target_field='processing_tool',
        expression="'citygisoo'",
        field_type=10,
        field_length=32)

    with _workflow_step('assign nrcan usage roll processed by field',
                        normalized_fsa):
      nrcan_usage_roll.assign_field_expression(
        target_field='processed_by',
        expression="'Sabu GIS Cities'",
        field_type=10,
        field_length=32)

    final_output_key = f'Gatineau_{normalized_fsa}_gisoo'
    with _workflow_step('create finalized GISOO layer', normalized_fsa):
      processor.extract_where(
        source_layer=nrcan_usage_roll,
        predicate=lambda feature: True,
        output_path=output_paths[final_output_key],
        layer_name=final_output_key)
      finalized_layer = _load_output_layer(
        output_paths,
        final_output_key,
        normalized_fsa,
        layer_name=final_output_key)

  except Exception:
    logger.exception(
      'Gatineau FSA GISOO workflow failed. FSA=%s',
      normalized_fsa)
    raise

  output_path = finalized_layer.layer_path
  logger.info(
    'Completed Gatineau FSA GISOO workflow. FSA=%s Output=%s Elapsed=%.3fs',
    normalized_fsa,
    output_path,
    perf_counter() - workflow_t0)
  return output_path


def _build_parser():
  parser = argparse.ArgumentParser(
    description='Run the Gatineau FSA GISOO workflow directly.')
  parser.add_argument(
    '--fsa',
    required=True,
    help='Three-character Gatineau FSA, for example H3H.')
  parser.add_argument(
    '--cleanup-outputs',
    action='store_true',
    help=(
      'Delete unretained intermediate datasets after a successful run. '
      'By default, every generated output is kept.'))
  parser.add_argument(
    '--keep-output',
    action='append',
    default=None,
    metavar='OUTPUT_KEY',
    help=(
      'Additional workflow output key to retain when cleanup is enabled. '
      'Repeat this option to retain multiple outputs.'))
  return parser


if __name__ == '__main__':
  configure_logging()
  parser = _build_parser()
  args = parser.parse_args()
  if args.keep_output and not args.cleanup_outputs:
    parser.error('--keep-output requires --cleanup-outputs.')
  if args.cleanup_outputs:
    try:
      from ..application import GISCitiesApplicationService
    except ImportError:
      try:
        from quebec_gisoo.application import GISCitiesApplicationService
      except ImportError as exc:
        raise RuntimeError(
          'Cleanup-enabled direct workflow execution requires the '
          'quebec_gisoo package to be installed.') from exc
    GISCitiesApplicationService.run_component(
      component_name='gatineau_fsa_gisoo',
      mode='independent',
      fsa=args.fsa,
      cleanup_outputs=True,
      keep_outputs=args.keep_output)
  else:
    run_workflow(args.fsa)
