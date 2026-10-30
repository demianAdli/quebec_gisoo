"""
quebec_gisoo package
Application-layer orchestration for city GIS cleaning components.
Project Designer and Developer: Alireza Adli
alireza.adli@mail.concordia.ca
alireza.adli4@gmail.com
www.demianadli.com
"""
from __future__ import annotations

import ast
import gc
import inspect
import importlib
import importlib.util
import multiprocessing
import os
import re
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from time import perf_counter

from sabu_chassis.logging import get_logger


logger = get_logger(__name__)

_COMPONENT_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_FSA_PATTERN = re.compile(r'^[A-Z][0-9][A-Z]$')


def _initialize_worker_qgis():
    """Create a headless QGIS application when the process does not have one."""
    try:
        from qgis.core import QgsApplication
    except ImportError:
        return None

    qgis_application = QgsApplication.instance()
    if qgis_application is not None:
        return qgis_application

    qgis_prefix_path = (
        os.getenv('QUEBEC_GISOO_QGIS_PATH')
        or os.getenv('QGIS_PREFIX_PATH'))
    if qgis_prefix_path:
        QgsApplication.setPrefixPath(qgis_prefix_path, True)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    qgis_application = QgsApplication([], False)
    qgis_application.initQgis()
    logger.info(
        'Initialized headless QGIS application. Prefix=%s',
        QgsApplication.prefixPath())
    return qgis_application


def _shutdown_worker_qgis(qgis_application=None):
    """Release project layers and shut down an owned QGIS application."""
    try:
        from qgis.core import QgsApplication, QgsProject
    except ImportError:
        return

    try:
        QgsProject.instance().removeAllMapLayers()
        gc.collect()
        active_application = qgis_application or QgsApplication.instance()
        if active_application is not None:
            active_application.exitQgis()
        logger.info('Shut down headless QGIS application.')
    except Exception:
        # Process termination still releases operating-system file handles.
        logger.exception('Failed to shut down QGIS cleanly.')


@contextmanager
def qgis_session():
    """Keep QGIS alive for a CLI run, releasing only an application we own."""
    try:
        from qgis.core import QgsApplication
    except ImportError:
        # Allow argument handling and orchestration without QGIS installed.
        yield None
        return

    existing_application = QgsApplication.instance()
    application = _initialize_worker_qgis()
    try:
        yield application
    finally:
        if existing_application is None and application is not None:
            _shutdown_worker_qgis(application)


def _execute_component_worker(
        component_name,
        mode,
        fsa,
        non_null_required_fields):
    """Execute one component inside a disposable spawned process."""
    qgis_application = None
    try:
        from ..logging_setup import configure_service_logging

        configure_service_logging('quebec_gisoo-worker')
        qgis_application = _initialize_worker_qgis()
        return GISCitiesApplicationService.run_component(
            component_name=component_name,
            mode=mode,
            fsa=fsa,
            non_null_required_fields=non_null_required_fields,
            cleanup_outputs=False,
            keep_outputs=None)
    finally:
        _shutdown_worker_qgis(qgis_application)


def _run_component_in_fresh_process(
        component_name,
        mode,
        fsa,
        non_null_required_fields):
    """Run one component and wait until its QGIS process fully terminates."""
    spawn_context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(
            max_workers=1,
            mp_context=spawn_context) as executor:
        future = executor.submit(
            _execute_component_worker,
            component_name,
            mode,
            fsa,
            non_null_required_fields)
        return future.result()


class GisComponentRunMode(str, Enum):
    """Supported direct execution modes for a GIS city component."""

    INDEPENDENT = 'independent'
    STANDARDIZE = 'standardize'


@dataclass(frozen=True)
class GisComponentRunResult:
    """Result envelope for a GIS city component run."""

    component_name: str
    mode: GisComponentRunMode
    workflow_output_path: str
    standardized_output_path: str | None = None
    fsa: str | None = None
    cleaned_output_paths: tuple[str, ...] = ()


class GisComponentError(RuntimeError):
    """Base error for GIS component application orchestration failures."""


class GisComponentNotFoundError(GisComponentError):
    """Raised when a requested component package cannot be found."""


class GisComponentContractError(GisComponentError):
    """Raised when a component does not implement the expected interface."""


class GisComponentCleanupError(GisComponentError):
    """Raised when outputs were produced but post-process cleanup failed."""


class GISCitiesApplicationService:
    """Run a quebec_gisoo component through a stable application contract."""

    _PACKAGE_NAME = 'quebec_gisoo'

    @classmethod
    def run_component(
            cls,
            component_name,
            mode=GisComponentRunMode.STANDARDIZE,
            fsa=None,
            non_null_required_fields=None,
            cleanup_outputs=False,
            keep_outputs=None):
        """Run a component workflow in independent or standardized mode.

        independent:
            Run only the component's workflow.run_workflow().

        standardize:
            Run workflow.run_workflow(), then
            contract_adapter.run_contract_adapter().
        """
        normalized_component_name = cls._normalize_component_name(
            component_name)
        normalized_mode = cls._normalize_mode(mode)
        normalized_fsa = cls._normalize_fsa(fsa)
        normalized_non_null_required_fields = (
            cls._normalize_non_null_required_fields(non_null_required_fields))
        normalized_cleanup_outputs = cls._normalize_cleanup_outputs(
            cleanup_outputs)
        normalized_keep_outputs = cls._normalize_keep_outputs(keep_outputs)
        if normalized_keep_outputs and not normalized_cleanup_outputs:
            raise ValueError(
                'keep_outputs requires cleanup_outputs=True.')

        if normalized_cleanup_outputs:
            return cls._run_component_with_isolated_cleanup(
                component_name=normalized_component_name,
                mode=normalized_mode,
                fsa=normalized_fsa,
                non_null_required_fields=(
                    normalized_non_null_required_fields),
                keep_outputs=normalized_keep_outputs)

        run_t0 = perf_counter()
        logger.info(
            'Starting GIS city component. Component=%s Mode=%s FSA=%s',
            normalized_component_name,
            normalized_mode.value,
            normalized_fsa)

        try:
            cls._ensure_component_callable(
                component_name=normalized_component_name,
                module_name='workflow',
                callable_name='run_workflow')
            if normalized_mode == GisComponentRunMode.STANDARDIZE:
                cls._ensure_component_callable(
                    component_name=normalized_component_name,
                    module_name='contract_adapter',
                    callable_name='run_contract_adapter')

            workflow_runner = cls._import_component_callable(
                component_name=normalized_component_name,
                module_name='workflow',
                callable_name='run_workflow')
            workflow_output_path = cls._run_component_callable(
                runner=workflow_runner,
                component_name=normalized_component_name,
                callable_label='workflow.run_workflow',
                fsa=normalized_fsa)

            standardized_output_path = None
            if normalized_mode == GisComponentRunMode.STANDARDIZE:
                contract_adapter_runner = cls._import_component_callable(
                    component_name=normalized_component_name,
                    module_name='contract_adapter',
                    callable_name='run_contract_adapter')
                standardized_output_path = cls._run_component_callable(
                    runner=contract_adapter_runner,
                    component_name=normalized_component_name,
                    callable_label='contract_adapter.run_contract_adapter',
                    fsa=normalized_fsa,
                    optional_kwargs={
                        'non_null_required_fields':
                            normalized_non_null_required_fields,
                    })

            cleaned_output_paths = ()

        except GisComponentError:
            logger.exception(
                'GIS city component failed before execution completed. '
                'Component=%s Mode=%s FSA=%s',
                normalized_component_name,
                normalized_mode.value,
                normalized_fsa)
            raise
        except (TypeError, ValueError):
            logger.exception(
                'GIS city component run parameters rejected. Component=%s '
                'Mode=%s FSA=%s',
                normalized_component_name,
                normalized_mode.value,
                normalized_fsa)
            raise
        except Exception as exc:
            logger.exception(
                'GIS city component execution failed. Component=%s Mode=%s '
                'FSA=%s',
                normalized_component_name,
                normalized_mode.value,
                normalized_fsa)
            raise GisComponentError(
                'GIS city component execution failed: '
                f'{normalized_component_name} ({normalized_mode.value})'
            ) from exc

        result = GisComponentRunResult(
            component_name=normalized_component_name,
            mode=normalized_mode,
            workflow_output_path=workflow_output_path,
            fsa=normalized_fsa,
            standardized_output_path=standardized_output_path,
            cleaned_output_paths=cleaned_output_paths)

        logger.info(
            'Completed GIS city component. Component=%s Mode=%s '
            'FSA=%s WorkflowOutput=%s StandardizedOutput=%s Cleaned=%s '
            'Elapsed=%.3fs',
            result.component_name,
            result.mode.value,
            result.fsa,
            result.workflow_output_path,
            result.standardized_output_path,
            len(result.cleaned_output_paths),
            perf_counter() - run_t0)
        return result

    @classmethod
    def _run_component_with_isolated_cleanup(
            cls,
            component_name,
            mode,
            fsa,
            non_null_required_fields,
            keep_outputs):
        """Run QGIS in a disposable process, then clean from the parent."""
        run_t0 = perf_counter()
        logger.info(
            'Starting isolated GIS city component. Component=%s Mode=%s '
            'FSA=%s',
            component_name,
            mode.value,
            fsa)

        cls._ensure_component_callable(
            component_name=component_name,
            module_name='output_cleanup',
            callable_name='cleanup_outputs')
        output_cleanup_runner = cls._import_component_callable(
            component_name=component_name,
            module_name='output_cleanup',
            callable_name='cleanup_outputs')
        cls._run_component_callable(
            runner=output_cleanup_runner,
            component_name=component_name,
            callable_label='output_cleanup.cleanup_outputs',
            fsa=fsa,
            optional_kwargs={
                'keep_outputs': keep_outputs,
                'validate_only': True,
                'release_qgis_layers': False,
            })

        try:
            worker_result = _run_component_in_fresh_process(
                component_name=component_name,
                mode=mode.value,
                fsa=fsa,
                non_null_required_fields=non_null_required_fields)
        except (GisComponentError, TypeError, ValueError):
            logger.exception(
                'Isolated GIS city component failed. Component=%s Mode=%s '
                'FSA=%s',
                component_name,
                mode.value,
                fsa)
            raise
        except Exception as exc:
            logger.exception(
                'Disposable GIS city component worker failed. Component=%s '
                'Mode=%s FSA=%s',
                component_name,
                mode.value,
                fsa)
            raise GisComponentError(
                'Disposable GIS component worker failed: '
                f'{component_name} ({mode.value})') from exc

        try:
            cleaned_output_paths = cls._run_component_callable(
                runner=output_cleanup_runner,
                component_name=component_name,
                callable_label='output_cleanup.cleanup_outputs',
                fsa=fsa,
                optional_kwargs={
                    'keep_outputs': keep_outputs,
                    'validate_only': False,
                    'release_qgis_layers': False,
                })
        except Exception as exc:
            logger.exception(
                'GIS city component completed but output cleanup failed. '
                'Component=%s Mode=%s FSA=%s WorkflowOutput=%s '
                'StandardizedOutput=%s',
                component_name,
                mode.value,
                fsa,
                worker_result.workflow_output_path,
                worker_result.standardized_output_path)
            raise GisComponentCleanupError(
                'GIS component outputs were created, but cleanup failed: '
                f'{component_name} ({mode.value}) FSA={fsa}') from exc

        result = GisComponentRunResult(
            component_name=worker_result.component_name,
            mode=worker_result.mode,
            workflow_output_path=worker_result.workflow_output_path,
            standardized_output_path=worker_result.standardized_output_path,
            fsa=worker_result.fsa,
            cleaned_output_paths=tuple(cleaned_output_paths or ()))
        logger.info(
            'Completed isolated GIS city component. Component=%s Mode=%s '
            'FSA=%s Cleaned=%s Elapsed=%.3fs',
            result.component_name,
            result.mode.value,
            result.fsa,
            len(result.cleaned_output_paths),
            perf_counter() - run_t0)
        return result

    @classmethod
    def _normalize_component_name(cls, component_name):
        if not isinstance(component_name, str):
            raise TypeError('component_name must be a string.')

        normalized_component_name = component_name.strip()
        if not normalized_component_name:
            raise ValueError('component_name is required.')
        if not _COMPONENT_NAME_PATTERN.match(normalized_component_name):
            raise ValueError(
                'component_name must be a valid Python package name.')

        component_package = (
            f'{cls._PACKAGE_NAME}.{normalized_component_name}')
        if importlib.util.find_spec(component_package) is None:
            raise GisComponentNotFoundError(
                f'GIS city component not found: {normalized_component_name}')

        return normalized_component_name

    @staticmethod
    def _normalize_mode(mode):
        if isinstance(mode, GisComponentRunMode):
            return mode
        if isinstance(mode, str):
            normalized_mode = mode.strip().lower()
            try:
                return GisComponentRunMode(normalized_mode)
            except ValueError as exc:
                valid_modes = ', '.join(item.value for item in
                                        GisComponentRunMode)
                raise ValueError(
                    f'Unsupported GIS component mode: {mode}. '
                    f'Supported modes: {valid_modes}.') from exc
        raise TypeError('mode must be a string or GisComponentRunMode.')

    @staticmethod
    def _normalize_fsa(fsa):
        if fsa is None:
            return None
        if not isinstance(fsa, str):
            raise TypeError('fsa must be a string when provided.')

        normalized_fsa = fsa.strip().upper()
        if not normalized_fsa:
            return None
        if not _FSA_PATTERN.match(normalized_fsa):
            raise ValueError(
                'fsa must be a three-character Canadian FSA.')
        return normalized_fsa

    @staticmethod
    def _normalize_non_null_required_fields(non_null_required_fields):
        if non_null_required_fields is None:
            return None
        if isinstance(non_null_required_fields, (str, bytes)):
            raise TypeError(
                'non_null_required_fields must be a list, tuple, set, '
                'or None.')

        try:
            raw_fields = list(non_null_required_fields)
        except TypeError as exc:
            raise TypeError(
                'non_null_required_fields must be a list, tuple, set, '
                'or None.') from exc

        if any(not isinstance(field_name, str) for field_name in raw_fields):
            raise TypeError(
                'non_null_required_fields must contain only strings.')

        normalized_fields = [
            field_name.strip()
            for field_name in raw_fields
        ]

        normalized_fields = [
            field_name for field_name in normalized_fields if field_name
        ]
        return normalized_fields or None

    @staticmethod
    def _normalize_cleanup_outputs(cleanup_outputs):
        if not isinstance(cleanup_outputs, bool):
            raise TypeError('cleanup_outputs must be a boolean.')
        return cleanup_outputs

    @staticmethod
    def _normalize_keep_outputs(keep_outputs):
        if keep_outputs is None:
            return None
        if isinstance(keep_outputs, (str, bytes)):
            raise TypeError(
                'keep_outputs must be a list, tuple, set, or None.')

        try:
            raw_output_keys = list(keep_outputs)
        except TypeError as exc:
            raise TypeError(
                'keep_outputs must be a list, tuple, set, or None.') from exc

        if any(not isinstance(output_key, str)
               for output_key in raw_output_keys):
            raise TypeError('keep_outputs must contain only strings.')

        normalized_output_keys = []
        seen = set()
        for output_key in raw_output_keys:
            normalized_output_key = output_key.strip()
            if not normalized_output_key:
                raise ValueError(
                    'keep_outputs cannot contain empty output keys.')
            if normalized_output_key not in seen:
                normalized_output_keys.append(normalized_output_key)
                seen.add(normalized_output_key)
        return normalized_output_keys or None

    @classmethod
    def _run_component_callable(
            cls,
            runner,
            component_name,
            callable_label,
            fsa,
            optional_kwargs=None):
        supports_fsa = cls._callable_accepts_parameter(runner, 'fsa')
        requires_fsa = cls._callable_requires_parameter(runner, 'fsa')
        optional_kwargs = optional_kwargs or {}
        supported_optional_kwargs = {
            name: value
            for name, value in optional_kwargs.items()
            if value is not None
            and cls._callable_accepts_parameter(runner, name)
        }

        if fsa is None:
            if requires_fsa:
                raise ValueError(
                    f'fsa is required for GIS city component: '
                    f'{component_name}.')
            return runner(**supported_optional_kwargs)

        if not supports_fsa:
            raise ValueError(
                f'fsa is not supported by GIS city component: '
                f'{component_name}.')
        logger.info(
            'Running GIS city component callable with FSA. Component=%s '
            'Callable=%s FSA=%s',
            component_name,
            callable_label,
            fsa)
        return runner(fsa=fsa, **supported_optional_kwargs)

    @staticmethod
    def _callable_accepts_parameter(runner, parameter_name):
        try:
            callable_signature = inspect.signature(runner)
        except (TypeError, ValueError):
            return False

        for parameter in callable_signature.parameters.values():
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                return True
            if parameter.name == parameter_name:
                return True
        return False

    @staticmethod
    def _callable_requires_parameter(runner, parameter_name):
        try:
            callable_signature = inspect.signature(runner)
        except (TypeError, ValueError):
            return False

        parameter = callable_signature.parameters.get(parameter_name)
        if parameter is None:
            return False
        return (
            parameter.default is inspect.Parameter.empty
            and parameter.kind in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        )

    @classmethod
    def _ensure_component_callable(
            cls,
            component_name,
            module_name,
            callable_name):
        module_path = f'{cls._PACKAGE_NAME}.{component_name}.{module_name}'
        module_spec = importlib.util.find_spec(module_path)
        if module_spec is None:
            raise GisComponentContractError(
                f'GIS city component {component_name} is missing '
                f'{module_name}.py.')

        cls._ensure_module_declares_callable(
            component_name=component_name,
            module_name=module_name,
            module_path=module_path,
            module_spec=module_spec,
            callable_name=callable_name)

    @classmethod
    def _import_component_callable(
            cls,
            component_name,
            module_name,
            callable_name):
        module_path = f'{cls._PACKAGE_NAME}.{component_name}.{module_name}'
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError as exc:
            if exc.name == module_path:
                raise GisComponentContractError(
                    f'GIS city component {component_name} is missing '
                    f'{module_name}.py.') from exc
            raise

        runner = getattr(module, callable_name, None)
        if runner is None or not callable(runner):
            raise GisComponentContractError(
                f'GIS city component {component_name}.{module_name} must '
                f'define callable {callable_name}().')
        return runner

    @staticmethod
    def _ensure_module_declares_callable(
            component_name,
            module_name,
            module_path,
            module_spec,
            callable_name):
        module_origin = getattr(module_spec, 'origin', None)
        if not module_origin or not module_origin.endswith('.py'):
            logger.debug(
                'Skipping static callable inspection for module %s. '
                'Origin=%s',
                module_path,
                module_origin)
            return

        try:
            with open(module_origin, encoding='utf-8') as module_file:
                module_tree = ast.parse(
                    module_file.read(),
                    filename=module_origin)
        except OSError as exc:
            raise GisComponentContractError(
                f'Unable to inspect GIS city component module: {module_path}'
            ) from exc

        for node in module_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == callable_name:
                    return

        raise GisComponentContractError(
            f'GIS city component {component_name}.{module_name} must define '
            f'callable {callable_name}().')
    