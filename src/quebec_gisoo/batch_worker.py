"""
QuebecGISOO project
Persistent worker process for asynchronous FSA batch jobs.
Project Designer and Developer: Alireza Adli
alireza.adli@mail.concordia.ca
alireza.adli4@gmail.com
www.demianadli.com
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import socket
import sys
import time
import uuid

from sabu_chassis.logging import get_logger

from .application.batch_jobs import get_batch_job_store
from .application.fsa_batch_runner import FsaBatchRunner
from .logging_setup import configure_service_logging


logger = get_logger(__name__)


class FsaBatchJobWorker:
    """Claim and execute persistent FSA batch jobs one batch at a time."""

    def __init__(self, store=None, worker_id=None, poll_interval=2.0):
        self.store = store or get_batch_job_store()
        self.worker_id = worker_id or (
            f'{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}')
        self.poll_interval = float(poll_interval)
        if self.poll_interval <= 0:
            raise ValueError('poll_interval must be greater than zero.')

    @staticmethod
    def _result_to_dict(result):
        return dataclasses.asdict(result)

    def run_once(self):
        job = self.store.claim_next_job(self.worker_id)
        if job is None:
            return False

        logger.info(
            'Claimed FSA batch job. BatchId=%s Component=%s',
            job.batch_id,
            job.component_name)
        runner = FsaBatchRunner(
            component_name=job.component_name,
            mode=job.mode,
            max_workers=job.max_workers,
            non_null_required_fields=job.non_null_required_fields,
            cleanup_outputs=job.cleanup_outputs,
            keep_outputs=job.keep_outputs,
            configure_worker_logging=True,
            result_callback=lambda result: self.store.record_result(
                job.batch_id,
                self._result_to_dict(result)))

        try:
            runner.validate_component()
            selected_fsas = runner.resolve_fsas(
                None if job.all_fsas else job.requested_fsas)
            self.store.set_resolved_fsas(job.batch_id, selected_fsas)
            if not self.store.acquire_fsa_locks(
                    job.batch_id,
                    job.component_name,
                    selected_fsas):
                self.store.requeue_job(
                    job.batch_id,
                    'Waiting for another run to release an FSA output lock.')
                logger.info(
                    'Requeued locked FSA batch job. BatchId=%s',
                    job.batch_id)
                return True

            result = runner.run(fsas=selected_fsas)
            ordered_results = [
                self._result_to_dict(item) for item in result.results
            ]
            self.store.set_results(job.batch_id, ordered_results)
            self.store.complete_job(job.batch_id, result.succeeded)
            logger.info(
                'Completed FSA batch job. BatchId=%s Succeeded=%s Failed=%s',
                job.batch_id,
                result.succeeded_count,
                result.failed_count)
        except Exception as exc:
            logger.exception(
                'FSA batch job failed. BatchId=%s Component=%s',
                job.batch_id,
                job.component_name)
            self.store.fail_job(
                job.batch_id,
                f'{type(exc).__name__}: {exc}')
        finally:
            self.store.release_fsa_locks(job.batch_id)
        return True

    def run_forever(self):
        recovered_count = self.store.recover_running_jobs()
        if recovered_count:
            logger.warning(
                'Recovered interrupted FSA batch jobs. Count=%s',
                recovered_count)
        logger.info('FSA batch worker started. WorkerId=%s', self.worker_id)
        while True:
            if not self.run_once():
                time.sleep(self.poll_interval)


def _build_parser():
    parser = argparse.ArgumentParser(
        description='Run the quebec_gisoo asynchronous FSA batch worker.')
    parser.add_argument(
        '--once',
        action='store_true',
        help='Process at most one queued job and exit.')
    parser.add_argument(
        '--poll-interval',
        type=float,
        default=float(os.getenv('QUEBEC_GISOO_JOB_POLL_SECONDS', '2')),
        help='Seconds to wait between empty queue polls.')
    return parser


def main(argv=None):
    configure_service_logging('quebec_gisoo-batch-worker')
    args = _build_parser().parse_args(argv)
    worker = FsaBatchJobWorker(poll_interval=args.poll_interval)
    if args.once:
        worker.store.recover_running_jobs()
        return 0 if worker.run_once() else 2
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        logger.info('FSA batch worker stopped.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
