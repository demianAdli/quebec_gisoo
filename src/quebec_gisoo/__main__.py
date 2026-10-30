"""
QuebecGISOO project
Direct Python execution entrypoint for quebec_gisoo.
Project Designer and Developer: Alireza Adli
alireza.adli@mail.concordia.ca
alireza.adli4@gmail.com
www.demianadli.com
"""
from __future__ import annotations

import argparse
import sys

from sabu_chassis.logging import get_logger

from .application import (
    GISCitiesApplicationService,
    GisComponentRunMode,
    qgis_session,
    run_fsa_batch,
)
from .logging_setup import configure_service_logging


logger = get_logger(__name__)


def _build_parser():
    parser = argparse.ArgumentParser(
        description='Run a quebec_gisoo component directly.')
    parser.add_argument(
        '--component',
        required=True,
        help=(
            'Component package name, for example gatineau_fsa_gisoo.'))
    parser.add_argument(
        '--mode',
        default=GisComponentRunMode.STANDARDIZE.value,
        choices=[mode.value for mode in GisComponentRunMode],
        help=(
            'Execution mode. independent runs only workflow.py; '
            'standardize runs workflow.py and contract_adapter.py.'))
    fsa_selection = parser.add_mutually_exclusive_group()
    fsa_selection.add_argument(
        '--fsa',
        help=(
            'Three-character Canadian FSA for components that require '
            'district selection.'))
    fsa_selection.add_argument(
        '--fsas',
        nargs='+',
        metavar='FSA',
        help='Selected FSAs to run as a batch.')
    fsa_selection.add_argument(
        '--all-fsas',
        action='store_true',
        help=(
            'Discover and run every FSA configured by the selected '
            'component.'))
    parser.add_argument(
        '--max-workers',
        type=int,
        default=1,
        metavar='COUNT',
        help='Maximum parallel FSA workers for batch execution.')
    parser.add_argument(
        '--drop-null-fields',
        nargs='+',
        default=None,
        metavar='FIELD',
        help=(
            'Optional standardized field names that must be non-null when '
            'running standardize mode. Features with null or empty values in '
            'any listed field are deleted. By default, no features are '
            'deleted based on null attributes.'))
    parser.add_argument(
        '--cleanup-outputs',
        action='store_true',
        help=(
            'Delete unretained intermediate datasets after a successful '
            'component run. By default, every generated output is kept.'))
    parser.add_argument(
        '--keep-output',
        action='append',
        default=None,
        metavar='OUTPUT_KEY',
        help=(
            'Additional workflow output key to retain when cleanup is '
            'enabled. Repeat this option to retain multiple outputs.'))
    return parser


def main(argv=None):
    configure_service_logging('quebec_gisoo-direct')
    parser = _build_parser()
    args = parser.parse_args(argv)
    is_batch = args.all_fsas or args.fsas is not None
    if not is_batch and args.max_workers != 1:
        parser.error('--max-workers requires --fsas or --all-fsas.')

    try:
        with qgis_session():
            if is_batch:
                result = run_fsa_batch(
                    component_name=args.component,
                    fsas=None if args.all_fsas else args.fsas,
                    mode=args.mode,
                    max_workers=args.max_workers,
                    non_null_required_fields=args.drop_null_fields,
                    cleanup_outputs=args.cleanup_outputs,
                    keep_outputs=args.keep_output)
            else:
                result = GISCitiesApplicationService.run_component(
                    component_name=args.component,
                    mode=args.mode,
                    fsa=args.fsa,
                    non_null_required_fields=args.drop_null_fields,
                    cleanup_outputs=args.cleanup_outputs,
                    keep_outputs=args.keep_output)
    except Exception as exc:
        logger.error(
            'Direct quebec_gisoo execution failed. Component=%s Mode=%s '
            'FSA=%s Error=%s',
            args.component,
            args.mode,
            args.fsa,
            exc)
        return 1

    print(f'Component: {result.component_name}')
    print(f'Mode: {result.mode if is_batch else result.mode.value}')
    if is_batch:
        print(f'FSAs: {len(result.results)}')
        print(f'Succeeded: {result.succeeded_count}')
        print(f'Failed: {result.failed_count}')
        for item in result.results:
            if not item.succeeded:
                print(f'{item.fsa}: {item.error}')
        return 0 if result.succeeded else 1
    if result.fsa is not None:
        print(f'FSA: {result.fsa}')
    print(f'Workflow output: {result.workflow_output_path}')
    if result.standardized_output_path is not None:
        print(f'Standardized output: {result.standardized_output_path}')
    if result.cleaned_output_paths:
        print(f'Cleaned outputs: {len(result.cleaned_output_paths)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
    