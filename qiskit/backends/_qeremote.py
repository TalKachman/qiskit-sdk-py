# -*- coding: utf-8 -*-

# Copyright 2017 IBM RESEARCH. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =============================================================================
"""QeRemote module

This module is used for connecting to the Quantum Experience.
"""
import time
import logging
import pprint
from qiskit.backends._basebackend import BaseBackend
from qiskit import _openquantumcompiler as openquantumcompiler
from qiskit import QISKitError
from qiskit._result import Result
from qiskit._resulterror import ResultError

logger = logging.getLogger(__name__)


class QeRemote(BaseBackend):
    """Backend class interfacing with the Quantum Experience remotely.

    Attributes:
        _api (IBMQuantumExperience): api for communicating with the Quantum
            Experience.
    """
    _api = None

    def __init__(self, configuration=None):
        """Initialize remote backend for IBM Quantum Experience.

        Args:
            configuration (dict, optional): configuration of backend
        """
        super().__init__(configuration)
        self._configuration = configuration
        self._configuration['local'] = False

    def run(self, q_job):
        """Run jobs

        Args:
            q_job (QuantumJob): job to run

        Returns:
            Result: Result object.

        Raises:
            ResultError: if the api put 'error' in its output
        """
        qobj = q_job.qobj
        wait = q_job.wait
        timeout = q_job.timeout
        api_jobs = []
        for circuit in qobj['circuits']:
            if (('compiled_circuit_qasm' not in circuit) or
                    (circuit['compiled_circuit_qasm'] is None)):
                compiled_circuit = openquantumcompiler.compile(
                    circuit['circuit'].qasm())
                circuit['compiled_circuit_qasm'] = compiled_circuit.qasm(qeflag=True)
            if isinstance(circuit['compiled_circuit_qasm'], bytes):
                api_jobs.append({'qasm': circuit['compiled_circuit_qasm'].decode()})
            else:
                api_jobs.append({'qasm': circuit['compiled_circuit_qasm']})

        seed0 = qobj['circuits'][0]['config']['seed']
        hpc = None
        if (qobj['config']['backend'] == 'ibmqx_hpc_qasm_simulator' and
                'hpc' in qobj['config']):
            try:
                # Use CamelCase when passing the hpc parameters to the API.
                hpc = {
                    'multiShotOptimization':
                        qobj['config']['hpc']['multi_shot_optimization'],
                    'ompNumThreads':
                        qobj['config']['hpc']['omp_num_threads']
                }
            except (KeyError, TypeError):
                hpc = None

        output = self._api.run_job(api_jobs, qobj['config']['backend'],
                                   shots=qobj['config']['shots'],
                                   max_credits=qobj['config']['max_credits'],
                                   seed=seed0,
                                   hpc=hpc)
        if 'error' in output:
            raise ResultError(output['error'])

        logger.debug('Running on remote backend %s with job id: %s',
                     qobj['config']['backend'], output['id'])
        job_result = _wait_for_job(output['id'], self._api, wait=wait,
                                   timeout=timeout)
        job_result['name'] = qobj['id']
        job_result['backend'] = qobj['config']['backend']
        this_result = Result(job_result, qobj)
        return this_result

    @classmethod
    def set_api(cls, api):
        """Associate API with class"""
        cls._api = api


def _wait_for_job(jobid, api, wait=5, timeout=60):
    """Wait until all online ran circuits of a qobj are 'COMPLETED'.

    Args:
        jobid (list(str)):  is a list of id strings.
        api (IBMQuantumExperience): IBMQuantumExperience API connection
        wait (int):  is the time to wait between requests, in seconds
        timeout (int):  is how long we wait before failing, in seconds

    Returns:
        list: A list of results that correspond to the jobids.

    Raises:
        QISKitError: job didn't return status or reported error in status
    """
    timer = 0
    job_result = api.get_job(jobid)
    if 'status' not in job_result:
        raise QISKitError("get_job didn't return status: %s" %
                          (pprint.pformat(job_result)))

    while job_result['status'] == 'RUNNING':
        if timer >= timeout:
            return {'job_id': jobid, 'status': 'ERROR',
                    'result': 'QISkit Time Out'}
        time.sleep(wait)
        timer += wait
        logger.info('status = %s (%d seconds)', job_result['status'], timer)
        job_result = api.get_job(jobid)

        if 'status' not in job_result:
            raise QISKitError("get_job didn't return status: %s" %
                              (pprint.pformat(job_result)))
        if (job_result['status'] == 'ERROR_CREATING_JOB' or
                job_result['status'] == 'ERROR_RUNNING_JOB'):
            return {'job_id': jobid, 'status': 'ERROR',
                    'result': job_result['status']}

    # Get the results
    job_result_return = []
    for index in range(len(job_result['qasms'])):
        job_result_return.append({'data': job_result['qasms'][index]['data'],
                                  'status': job_result['qasms'][index]['status']})
    return {'job_id': jobid, 'status': job_result['status'],
            'result': job_result_return}
