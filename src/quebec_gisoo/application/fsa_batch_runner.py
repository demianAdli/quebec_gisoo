"""
QuebecGISOO project
Generic batch orchestration for FSA-capable GIS city components.
Project Designer and Developer: Alireza Adli
alireza.adli@mail.concordia.ca
alireza.adli4@gmail.com
www.demianadli.com
"""
from __future__ import annotations

import importlib
import multiprocessing
import os
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Iterable

from sabu_chassis.logging import get_logger

from .quebec_gisoo import (
    GisComponentContractError,
    GisComponentRunMode,
    GISCitiesApplicationService,
)


logger = get_logger(__name__)

_COMPONENT_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_FSA_PATTERN = re.compile(r'^[A-Z][0-9][A-Z]$')


@dataclass(frozen=True)
class FsaBatchItemResult:
    """Outcome for one FSA in a component batch run."""

    fsa: str
    succeeded: bool
    workflow_output_path: str | None = None
    standardized_output_path: str | None = None
    error: str | None = None
    elapsed_seconds: float = 0.0
    cleaned_output_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class FsaBatchRunResult:
    """Outcome summary for an FSA component batch run."""

    component_name: str
    mode: str
    max_workers: int
    results: tuple[FsaBatchItemResult, ...]

    @property
    def fsas(self):
        return tuple(result.fsa for result in self.results)

    @property
    def succeeded_count(self):
        return sum(1 for result in self.results if result.succeeded)

    @property
    def failed_count(self):
        return sum(1 for result in self.results if not result.succeeded)

    @property
    def succeeded(self):
        return self.failed_count == 0


def _normalize_component_name(component_name):
    if not isinstance(component_name, str):
        raise TypeError('component_name must be a string.')
    normalized_component_name = component_name.strip()
    if not normalized_component_name:
        raise ValueError('component_name is required.')
    if not _COMPONENT_NAME_PATTERN.match(normalized_component_name):
        raise ValueError(
            'component_name must be a valid Python package name.')
    return normalized_component_name


def _mode_value(mode):
    if isinstance(mode, GisComponentRunMode):
        return mode.value
    if not isinstance(mode, str):
        raise TypeError('mode must be a string or GisComponentRunMode.')
    normalized_mode = mode.strip().lower()
    if not normalized_mode:
        raise ValueError('mode is required.')
    return normalized_mode


def _normalize_fsa(fsa):
    if not isinstance(fsa, str):
        raise TypeError('fsa values must be strings.')
    normalized_fsa = fsa.strip().upper()
    if not _FSA_PATTERN.match(normalized_fsa):
        raise ValueError(
            'fsa must be a three-character Canadian FSA.')
    return normalized_fsa


def normalize_fsas(fsas):
    """Normalize FSA values while preserving order and removing duplicates."""
    if fsas is None:
        raise ValueError('fsas is required.')

    normalized_fsas = []
    seen = set()
    for fsa in fsas:
        normalized_fsa = _normalize_fsa(fsa)
        if normalized_fsa in seen:
            continue
        normalized_fsas.append(normalized_fsa)
        seen.add(normalized_fsa)

    if not normalized_fsas:
        raise ValueError('At least one FSA is required.')
    return tuple(normalized_fsas)


def _ensure_fsa_component(component_name):
    """Validate that a component workflow declares an FSA parameter."""
    GISCitiesApplicationService._normalize_component_name(component_name)
    GISCitiesApplicationService._ensure_component_callable(
        component_name=component_name,
        module_name='workflow',
        callable_name='run_workflow')
    workflow_runner = GISCitiesApplicationService._import_component_callable(
        component_name=component_name,
        module_name='workflow',
        callable_name='run_workflow')
    if not GISCitiesApplicationService._callable_accepts_parameter(
            workflow_runner, 'fsa'):
        raise GisComponentContractError(
            f'GIS city component {component_name} is not FSA-capable: '
            'workflow.run_workflow must accept an fsa parameter.')


def _load_fsa_discovery_config(component_name):
    module_path = (
        f'{GISCitiesApplicationService._PACKAGE_NAME}.'
        f'{component_name}.workflow_config')
    try:
        workflow_config = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        if exc.name == module_path:
            raise GisComponentContractError(
                f'GIS city component {component_name} is missing '
                'workflow_config.py required for FSA discovery.') from exc
        raise

    missing_fields = [
        field_name
        for field_name in ('qgis_path', 'input_paths', 'fsa_field_name')
        if not hasattr(workflow_config, field_name)
    ]
    if missing_fields:
        raise GisComponentContractError(
            f'GIS city component {component_name} workflow_config is missing '
            f'FSA discovery settings: {", ".join(missing_fields)}.')

    input_paths = workflow_config.input_paths
    if not isinstance(input_paths, dict) or not input_paths.get('fsa'):
        raise GisComponentContractError(
            f'GIS city component {component_name} workflow_config must define '
            'a non-empty input_paths["fsa"] value.')
    if not isinstance(workflow_config.qgis_path, str) \
            or not workflow_config.qgis_path.strip():
        raise GisComponentContractError(
            f'GIS city component {component_name} workflow_config must define '
            'a non-empty qgis_path string.')
    if not isinstance(workflow_config.fsa_field_name, str) \
            or not workflow_config.fsa_field_name.strip():
        raise GisComponentContractError(
            f'GIS city component {component_name} workflow_config must define '
            'a non-empty fsa_field_name string.')
    return workflow_config


def discover_component_fsas(component_name):
    """Discover unique FSAs from a component's configured boundary layer."""
    normalized_component_name = _normalize_component_name(component_name)
    workflow_config = _load_fsa_discovery_config(normalized_component_name)

    from citygisoo.scrub_layer_class import ScrubLayer

    try:
        fsa_layer = ScrubLayer(
            workflow_config.qgis_path,
            workflow_config.input_paths['fsa'],
            f'{normalized_component_name}_fsa_boundaries')
    except Exception as exc:
        raise ValueError(
            f'Unable to load the configured FSA layer for GIS city component '
            f'{normalized_component_name}: {exc}') from exc

    discovered_fsas = set()
    try:
        for feature in fsa_layer.layer.getFeatures():
            value = feature[workflow_config.fsa_field_name]
            if value is None:
                continue
            value = str(value).strip()
            if value:
                discovered_fsas.add(_normalize_fsa(value))
    except (KeyError, LookupError) as exc:
        raise GisComponentContractError(
            f'Configured FSA field {workflow_config.fsa_field_name!r} was not '
            f'found for GIS city component {normalized_component_name}.') \
            from exc

    if not discovered_fsas:
        raise ValueError(
            f'No FSA values were found in the configured layer for GIS city '
            f'component {normalized_component_name}.')
    return tuple(sorted(discovered_fsas))


def _configure_fsa_worker_logging(component_name, fsa):
    from ..logging_setup import configure_service_logging

    service_name = f'quebec_gisoo-{component_name}-{fsa.lower()}'
    os.environ['LOG_SERVICE'] = service_name
    os.environ['LOG_FILE_NAME'] = os.path.join(
        'logs',
        'fsa',
        component_name,
        f'{fsa}.log')
    configure_service_logging(service_name)


def run_one_fsa(
        component_name,
        fsa,
        mode=GisComponentRunMode.STANDARDIZE,
        non_null_required_fields=None,
        configure_worker_logging=False,
        component_runner=None,
        cleanup_outputs=False,
        keep_outputs=None):
    """Run one FSA for a component and return a batch result item."""
    normalized_component_name = _normalize_component_name(component_name)
    normalized_fsa = _normalize_fsa(fsa)
    normalized_mode = _mode_value(mode)
    run_t0 = perf_counter()

    if configure_worker_logging:
        _configure_fsa_worker_logging(
            normalized_component_name,
            normalized_fsa)

    runner = component_runner or GISCitiesApplicationService.run_component
    try:
        runner_kwargs = dict(
            component_name=normalized_component_name,
            mode=normalized_mode,
            fsa=normalized_fsa,
            non_null_required_fields=non_null_required_fields)
        if cleanup_outputs or keep_outputs is not None:
            runner_kwargs.update(
                cleanup_outputs=cleanup_outputs,
                keep_outputs=keep_outputs)
        result = runner(**runner_kwargs)
    except Exception as exc:
        logger.exception(
            'FSA batch item failed. Component=%s FSA=%s Mode=%s',
            normalized_component_name,
            normalized_fsa,
            normalized_mode)
        return FsaBatchItemResult(
            fsa=normalized_fsa,
            succeeded=False,
            error=f'{type(exc).__name__}: {exc}',
            elapsed_seconds=perf_counter() - run_t0)

    return FsaBatchItemResult(
        fsa=normalized_fsa,
        succeeded=True,
        workflow_output_path=getattr(result, 'workflow_output_path', None),
        standardized_output_path=getattr(
            result,
            'standardized_output_path',
            None),
        cleaned_output_paths=tuple(getattr(
            result,
            'cleaned_output_paths',
            ()) or ()),
        elapsed_seconds=perf_counter() - run_t0)


def _run_fsa_batch_sequential(
        component_name,
        fsas,
        mode,
        non_null_required_fields,
        cleanup_outputs,
        keep_outputs,
        configure_worker_logging,
        component_runner,
        result_callback):
    results = []
    for fsa in fsas:
        result = run_one_fsa(
            component_name=component_name,
            fsa=fsa,
            mode=mode,
            non_null_required_fields=non_null_required_fields,
            cleanup_outputs=cleanup_outputs,
            keep_outputs=keep_outputs,
            configure_worker_logging=configure_worker_logging,
            component_runner=component_runner)
        results.append(result)
        if result_callback is not None:
            result_callback(result)
    return tuple(results)


def _run_fsa_batch_parallel(
        component_name,
        fsas,
        mode,
        non_null_required_fields,
        cleanup_outputs,
        keep_outputs,
        max_workers,
        result_callback):
    results_by_fsa = {}
    spawn_context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=spawn_context) as executor:
        futures = {
            executor.submit(
                run_one_fsa,
                component_name=component_name,
                fsa=fsa,
                mode=mode,
                non_null_required_fields=non_null_required_fields,
                configure_worker_logging=True,
                cleanup_outputs=cleanup_outputs,
                keep_outputs=keep_outputs): fsa
            for fsa in fsas
        }

        for future in as_completed(futures):
            fsa = futures[future]
            try:
                results_by_fsa[fsa] = future.result()
            except Exception as exc:
                logger.exception(
                    'FSA worker process failed. Component=%s FSA=%s Mode=%s',
                    component_name,
                    fsa,
                    mode)
                results_by_fsa[fsa] = FsaBatchItemResult(
                    fsa=fsa,
                    succeeded=False,
                    error=f'{type(exc).__name__}: {exc}')
            if result_callback is not None:
                result_callback(results_by_fsa[fsa])

    return tuple(results_by_fsa[fsa] for fsa in fsas)


@dataclass(frozen=True)
class FsaBatchRunner:
    """Configured batch runner for an FSA-capable GIS city component."""

    component_name: str
    mode: str | GisComponentRunMode = GisComponentRunMode.STANDARDIZE
    max_workers: int = 1
    non_null_required_fields: Iterable[str] | None = None
    fsa_provider: Callable[[], Iterable[str]] | None = None
    component_runner: Callable | None = None
    configure_worker_logging: bool = False
    cleanup_outputs: bool = False
    keep_outputs: Iterable[str] | None = None
    result_callback: Callable[[FsaBatchItemResult], None] | None = None

    def __post_init__(self):
        normalized_component_name = _normalize_component_name(
            self.component_name)
        normalized_mode = _mode_value(self.mode)
        if not isinstance(self.max_workers, int):
            raise TypeError('max_workers must be an integer.')
        if self.max_workers < 1:
            raise ValueError('max_workers must be at least 1.')
        if not isinstance(self.cleanup_outputs, bool):
            raise TypeError('cleanup_outputs must be a boolean.')
        normalized_keep_outputs = self.keep_outputs
        if normalized_keep_outputs is not None:
            if isinstance(normalized_keep_outputs, (str, bytes)):
                raise TypeError(
                    'keep_outputs must be an iterable of output keys.')
            normalized_keep_outputs = tuple(normalized_keep_outputs)
            if any(not isinstance(output_key, str)
                   for output_key in normalized_keep_outputs):
                raise TypeError('keep_outputs must contain only strings.')
            normalized_keep_outputs = normalized_keep_outputs or None
        if normalized_keep_outputs and not self.cleanup_outputs:
            raise ValueError('keep_outputs requires cleanup_outputs=True.')
        if self.max_workers > 1 and self.component_runner is not None:
            raise ValueError(
                'component_runner injection is only supported for '
                'sequential runs.')
        if self.result_callback is not None \
                and not callable(self.result_callback):
            raise TypeError('result_callback must be callable or None.')
        object.__setattr__(self, 'component_name', normalized_component_name)
        object.__setattr__(self, 'mode', normalized_mode)
        object.__setattr__(self, 'keep_outputs', normalized_keep_outputs)

    def discover_fsas(self):
        if self.fsa_provider is not None:
            return normalize_fsas(self.fsa_provider())
        return discover_component_fsas(self.component_name)

    def validate_component(self):
        """Validate the selected component's FSA workflow capability."""
        _ensure_fsa_component(self.component_name)

    def resolve_fsas(self, fsas=None):
        if fsas is None:
            return self.discover_fsas()
        return normalize_fsas(fsas)

    def run_one(self, fsa):
        return run_one_fsa(
            component_name=self.component_name,
            fsa=fsa,
            mode=self.mode,
            non_null_required_fields=self.non_null_required_fields,
            cleanup_outputs=self.cleanup_outputs,
            keep_outputs=self.keep_outputs,
            configure_worker_logging=self.configure_worker_logging,
            component_runner=self.component_runner)

    def run_fsas(self, fsas):
        return self.run(fsas=fsas)

    def run_all(self):
        return self.run()

    def run(self, fsas=None):
        if self.component_runner is None:
            self.validate_component()
        selected_fsas = self.resolve_fsas(fsas)
        logger.info(
            'Starting FSA batch. Component=%s Count=%s Mode=%s MaxWorkers=%s',
            self.component_name,
            len(selected_fsas),
            self.mode,
            self.max_workers)

        batch_t0 = perf_counter()
        if self.max_workers == 1:
            results = _run_fsa_batch_sequential(
                self.component_name,
                selected_fsas,
                self.mode,
                self.non_null_required_fields,
                self.cleanup_outputs,
                self.keep_outputs,
                self.configure_worker_logging,
                self.component_runner,
                self.result_callback)
        else:
            results = _run_fsa_batch_parallel(
                self.component_name,
                selected_fsas,
                self.mode,
                self.non_null_required_fields,
                self.cleanup_outputs,
                self.keep_outputs,
                self.max_workers,
                self.result_callback)

        batch_result = FsaBatchRunResult(
            component_name=self.component_name,
            mode=self.mode,
            max_workers=self.max_workers,
            results=results)
        logger.info(
            'Completed FSA batch. Component=%s Count=%s Succeeded=%s '
            'Failed=%s Mode=%s MaxWorkers=%s Elapsed=%.3fs',
            self.component_name,
            len(selected_fsas),
            batch_result.succeeded_count,
            batch_result.failed_count,
            self.mode,
            self.max_workers,
            perf_counter() - batch_t0)
        return batch_result


def run_fsa_batch(
        component_name,
        fsas=None,
        mode=GisComponentRunMode.STANDARDIZE,
        max_workers=1,
        non_null_required_fields=None,
        fsa_provider: Callable[[], Iterable[str]] | None = None,
        component_runner=None,
        configure_worker_logging=False,
        cleanup_outputs=False,
        keep_outputs=None,
        result_callback=None):
    """Run an FSA-capable GIS city component for selected or all FSAs."""
    runner = FsaBatchRunner(
        component_name=component_name,
        mode=mode,
        max_workers=max_workers,
        non_null_required_fields=non_null_required_fields,
        cleanup_outputs=cleanup_outputs,
        keep_outputs=keep_outputs,
        fsa_provider=fsa_provider,
        component_runner=component_runner,
        configure_worker_logging=configure_worker_logging,
        result_callback=result_callback)
    return runner.run(fsas=fsas)


__all__ = [
    'FsaBatchItemResult',
    'FsaBatchRunResult',
    'FsaBatchRunner',
    'discover_component_fsas',
    'normalize_fsas',
    'run_fsa_batch',
    'run_one_fsa',
]
