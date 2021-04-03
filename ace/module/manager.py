# vim: ts=4:sw=4:et:cc=120
#

import asyncio
import concurrent.futures
import multiprocessing
import os
import signal
import sys
import threading
import uuid

from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Optional

from ace.analysis import RootAnalysis, Analysis, AnalysisModuleType
from ace.api.base import AceAPI, AnalysisRequest
from ace.error_reporting.reporter import format_error_report
from ace.exceptions import AnalysisModuleTypeVersionError, AnalysisModuleTypeExtendedVersionError
from ace.logging import get_logger
from ace.module.base import AnalysisModule
from ace.system import ACESystem
from ace.system.remote import RemoteACESystem

import psutil

# possible results of compute_scaling
SCALE_UP = 1
NO_SCALING = 0
SCALE_DOWN = -1

#
# concurrency routines
#

# concurrency mode for multi-process analysis modules
# defaults to threaded
CONCURRENCY_MODE_THREADED = 1
CONCURRENCY_MODE_PROCESS = 2

#
# process-based concurrency uses empty processes to do the work
# all the arguments to the process are serialized (using pickle)
# we don't want to have to serialize the instance of the analysis module
# that would not work for module that load large data sets to do their work
# (such as yara analyzers)
# so instead, when the process starts, we use the initializer to load
# all the analysis modules
# these are passed in as a dict { name: [type, amt] }
# where name is AnalysisModuleType.name
# type is type(AnalysisModule)
# amt is AnalysisModuleType
# we use these arguments to instantiate copies of the analysis modules
# and these instances of the analysis modules are kept in the global sync_module_map
# then to execute them, we just pass the name and look up the name
# in the global sync_module_map to get the analysis module to use
# then all that needs to be serialized is the name of the module and the analysis request
#

sync_module_map = None
# for each new process (or thread) we create a new async event loop
event_loop_map = {}  # key = thread_id, value = event loop
# we need this at the start as we build out the threads/processes
event_loop_sync = threading.RLock()
# global reference to the system to use for remote api purposes
sync_system = None


def _get_executor_event_loop():
    """Returns the event loop to use for the current executor."""
    with event_loop_sync:
        return event_loop_map[threading.current_thread()]


def _initialize_executor(module_map, system_class):
    """Initializes the executor. Creates a new event loop and loads the
    analysis modules into memory. Initializes an instance of the system to use."""
    global sync_system

    if sync_system is None:
        sync_system = system_class()
        # this has to be a remote api based system interface
        assert isinstance(sync_system, RemoteACESystem)

    with event_loop_sync:
        event_loop_map[threading.current_thread()] = asyncio.new_event_loop()

    _get_executor_event_loop().run_until_complete(_initialize_executor_async(module_map))


async def _initialize_executor_async(module_map):
    global sync_module_map
    try:
        sync_module_map = {}
        # TODO probably need to initialize logging here
        for module_name, params in module_map.items():
            _type, amt = params
            # create a new instance of the analysis module
            sync_module_map[module_name] = _type(type=amt)
            # load any additional resources
            await sync_module_map[module_name].load()

        import logging

        get_logger().setLevel(logging.DEBUG)

    except Exception as e:
        sys.stderr.write(e)


def _execute_multi_process_module(module_type: str, request_json: str) -> str:
    """Processes the request with the analysis module."""
    amt = AnalysisModuleType.from_json(module_type)
    module = sync_module_map[amt.name]

    # run_until_complete just keeps going until it returns
    # there's no way to "cancel" it
    # the only way out is to kill the process
    # so we start a thread to monitor the timeout
    def _module_timeout():
        get_logger().critical(f"analysis module {module} timed out analyzing request {request_json}")
        # and then die if we hit it
        sys.exit(1)

    get_logger().info(f"starting timer for {module.timeout} seconds")
    t = threading.Timer(module.timeout, _module_timeout)
    t.start()

    try:
        result = _get_executor_event_loop().run_until_complete(
            _execute_multi_process_module_async(module_type, request_json)
        )
    finally:
        # if we did't time out make sure we cancel the timer
        t.cancel()

    return result


async def _execute_multi_process_module_async(module_type: str, request_json: str) -> str:
    # XXX ???
    # use a dummy system here...
    from ace.system.threaded import ThreadedACESystem

    system = ThreadedACESystem()

    request = AnalysisRequest.from_json(request_json, system)
    amt = AnalysisModuleType.from_json(module_type)
    module = sync_module_map[amt.name]
    if not module.type.extended_version_matches(amt):
        await module.upgrade()

    if not module.type.extended_version_matches(amt):
        raise AnalysisModuleTypeExtendedVersionError(amt, module.type)

    analysis = request.modified_observable.add_analysis(Analysis(type=module.type, details={}))
    await module.execute_analysis(request.modified_root, request.modified_observable, analysis)
    return request.to_json()


def _upgrade_multi_process_module(amt_json: str) -> str:
    """Upgrades the module type."""
    return _get_executor_event_loop().run_until_complete(_upgrade_multi_process_module_async(amt_json))


async def _upgrade_multi_process_module_async(amt_json: str) -> str:
    if not sync_module_map:
        raise RuntimeError("_upgrade_multi_process_module called before _initialize_executor")

    amt = AnalysisModuleType.from_json(amt_json)
    module = sync_module_map[amt.name]
    await module.upgrade()
    return module.type.to_json()


class AnalysisModuleManager:
    """Executes and manages ace.module.AnalysisModule objects."""

    def __init__(self, system: ACESystem, concurrency_mode=CONCURRENCY_MODE_THREADED, wait_time=0):
        assert isinstance(system, ACESystem)
        assert isinstance(concurrency_mode, int)
        assert isinstance(wait_time, int) and wait_time >= 0

        # reference to the remote system
        self.system = system

        # the analysis modules this manager is running
        self.analysis_modules = []

        # current list of tasks
        self.module_tasks = []  # asyncio.Task
        self.module_task_count = {}  # key = AnalysisModule, value = int

        # executor for non-async modules
        self.concurrency_mode = concurrency_mode  # determines threading or multiprocessing
        self.executor = None

        # the amount of time (in seconds) to wait for analysis requests
        self.wait_time = wait_time  # defaults to not waiting

        #
        # asyncio events
        #

        # set right before entering processing loop
        self.event_loop_starting_event = asyncio.Event()

        #
        # state flags
        #

        # set to True to stop the manager gracefully (allowing existing tasks to complete)
        self.shutdown = False

        # set to True to stop immediately
        self.immediate_shutdown = False

    async def verify_registration(self) -> bool:
        """Ensure analysis modules are registered and up to date."""
        tasks = []
        for module in self.analysis_modules:

            async def check_type(module):
                result = await self.system.get_analysis_module_type(module.type.name)
                return module, result

            task = asyncio.get_event_loop().create_task(check_type(module))
            tasks.append(task)

        verification_ok = True
        for task in asyncio.as_completed(tasks):
            module, existing_type = await task
            if not existing_type:
                get_logger().critical(f"analysis module type {module.type.name} is not registered")
                verification_ok = False
                continue

            # is the version we have for this module different than the version already registered?
            if not module.type.version_matches(existing_type):
                get_logger().critical(f"analysis module type {module.type.name} has a different version")
                verification_ok = False
                continue

            # is the extended version different?
            if not module.type.extended_version_matches(existing_type):
                # try to upgrade the module
                await self.upgrade_module(module)

                # is it still different?
                if not module.type.extended_version_matches(existing_type):
                    get_logger().critical(
                        f"analysis module type {module.type.name} has a different extended version after upgrade"
                    )
                    verification_ok = False
                    continue

        return verification_ok

    def compute_scaling(self, module: AnalysisModule) -> int:
        """Compute the scaling for the given module. Returns
        SCALE_UP: to increase the number of workers by 1.
        SCALE_DOWN: to decrease the number of workers by 1.
        NO_SCALING: to keep current levels."""
        # by default we never scale up
        # implement custom algorithms in subclasses
        return SCALE_DOWN

    def add_module(self, module: AnalysisModule) -> AnalysisModule:
        """Adds the given AnalysisModule to this manager. Duplicate modules are ignored.
        Returns the added module, or None if the module already existed."""
        if type(module) not in [type(_) for _ in self.analysis_modules]:
            self.analysis_modules.append(module)
            self.module_task_count[module] = 0
            return module
        else:
            return None

    def _new_module_task(self, module: AnalysisModule, whoami: str):
        # adds a new analysis module task to the event loop
        task = asyncio.create_task(self.module_loop(module, whoami), name=f"module {module.type.name}:{whoami}")
        self.module_tasks.append(task)

    def initialize_module_tasks(self):
        """Creates the initial set of analysis module tasks, one for each loaded analysis module."""
        for module in self.analysis_modules:
            self.create_module_task(module)

    def create_module_task(self, module: AnalysisModule, whoami: Optional[str] = None):
        """Creates a new analysis module task if the limit of the module allows it."""
        if whoami is None:
            whoami = str(uuid.uuid4())

        if self.module_task_count[module] < module.limit:
            self._new_module_task(module, whoami)
            self.module_task_count[module] += 1
        else:
            pass  # TODO notify we are trying to scale above the limit

    def continue_module_task(self, module: AnalysisModule, whoami: str):
        """Continues execution of the module."""
        self._new_module_task(module, whoami)

    def stop_module_task(self, module: AnalysisModule, whoami: str):
        """Stops execution of the module."""
        self.module_task_count[module] -= 1

    def start_executor(self):
        module_map = {_.type.name: [type(_), _.type] for _ in self.analysis_modules}

        # executor for non-async modules
        if self.concurrency_mode == CONCURRENCY_MODE_THREADED:
            self.executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=multiprocessing.cpu_count(), initializer=_initialize_executor, initargs=(module_map,)
            )
        else:
            self.executor = concurrent.futures.ProcessPoolExecutor(
                initializer=_initialize_executor, initargs=(module_map,)
            )

    def kill_executor(self):
        if self.concurrency_mode != CONCURRENCY_MODE_PROCESS:
            return

        for process in psutil.Process(os.getpid()).children():
            get_logger().warning(f"sending KILL to {process}")
            process.send_signal(signal.SIGTERM)

    async def run_once(self) -> bool:
        """Run once through the analysis routine and exit."""
        self.shutdown = True
        return await self.run()

    async def run(self) -> bool:
        """Run the analysis routine. Does not return until all tasks have completed."""
        # download current registration and compare
        if not await self.verify_registration():
            return False

        # start the executor for the non-async analysis modules
        self.start_executor()

        # start initial analysis tasks
        self.initialize_module_tasks()
        self.event_loop_starting_event.set()

        # primary loop
        module_tasks = self.module_tasks[:]
        self.module_tasks = []
        while module_tasks:
            # done, pending = await asyncio.wait(module_tasks, timeout=0.1, return_when=asyncio.FIRST_COMPLETED)
            done, pending = await asyncio.wait(module_tasks, timeout=0.01)
            # if the system is shutting down then we go ahead and cancel any new and/or pending tasks
            if self.immediate_shutdown:
                for task in pending:
                    task.cancel()
                for task in self.module_tasks:
                    task.cancel()

            self.module_tasks.extend(pending)
            module_tasks = self.module_tasks[:]
            self.module_tasks = []
            for completed_task in done:
                try:
                    await completed_task
                except asyncio.CancelledError:
                    get_logger().warning(f"task {completed_task.get_name()} was cancelled before it completed")

        self.executor.shutdown(wait=False, cancel_futures=True)
        self.kill_executor()
        return True

    def stop(self):
        """Gracefully stops the manager. Allows existing jobs to complete."""
        self.shutdown = True

    def force_stop(self):
        """Stops the manager now, cancelling all running jobs."""
        self.shutdown = True
        self.immediate_shutdown = True

    async def upgrade_module(self, module: AnalysisModule) -> bool:
        """Attempts to upgrade the extended version of the analysis module.
        Returns True if the upgrade was successful, False otherwise."""

        # if the module is async then we attempt to upgrade it here
        try:
            if module.is_multi_process:
                module.type = AnalysisModuleType.from_json(
                    await asyncio.get_event_loop().run_in_executor(
                        self.executor, _upgrade_multi_process_module, module.type.to_json()
                    )
                )
            else:
                await module.upgrade()

            return True

        except Exception as e:
            get_logger().error(f"unable to upgrade module {module.type}: {e}")
            return False

    async def module_loop(self, module: AnalysisModule, whoami: str):
        """Entrypoint for analysis module execution."""
        request = None

        try:
            request = await self.system.get_next_analysis_request(
                whoami, module.type, self.wait_time, module.type.version, module.type.extended_version
            )
        except AnalysisModuleTypeExtendedVersionError as e:
            get_logger().warning(f"module {module.type.name} has invalid extended version: {e}")
            if not await self.upgrade_module(module):
                self.shutdown = True

        except AnalysisModuleTypeVersionError as e:
            get_logger().error(f"module {module.type.name} has invalid version: {e}")
            self.shutdown = True

        scaling = self.compute_scaling(module)
        if not self.shutdown and scaling == SCALE_UP:
            self.create_module_task(module)

        if request:
            request = await self.execute_module(module, whoami, request)

        # we just continue executing if there is no scaling required
        # OR this is the last task for this module
        # (there should always be one running)
        if not self.shutdown and (scaling == NO_SCALING or self.module_task_count[module] == 1):
            self.continue_module_task(module, whoami)
        elif self.shutdown or scaling == SCALE_DOWN:
            self.stop_module_task(module, whoami)

        # it is ok to wait here
        # we continue analysis on a new task
        if request:
            await self.system.process_analysis_request(request)

        return module

    async def execute_module(self, module: AnalysisModule, whoami: str, request: AnalysisRequest) -> AnalysisRequest:
        """Processes the request with the analysis module.
        Returns a copy of the original request with the results added"""

        assert isinstance(module, AnalysisModule)
        assert isinstance(whoami, str) and whoami
        assert isinstance(request, AnalysisRequest)

        request.initialize_result()
        if module.is_multi_process:
            try:
                request_json = request.to_json()
                request_result_json = await asyncio.get_event_loop().run_in_executor(
                    self.executor, _execute_multi_process_module, module.type.to_json(), request_json
                )
                return AnalysisRequest.from_json(request_result_json, self.system)
            except BrokenProcessPool as e:
                # when this happens you have to create and start a new one
                self.process_exception(
                    module,
                    request,
                    e,
                    error_message=f"{module.type} process crashed when analyzing type {request.modified_observable.type} value {request.modified_observable.value}",
                )
                # we have to start a new executor
                self.start_executor()
                return request
            except Exception as e:
                return self.process_exception(
                    module,
                    request,
                    e,
                    f"{module.type} failed analyzing type {request.modified_observable.type} value {request.modified_observable.value}: {e}",
                )
        else:
            try:
                analysis = request.modified_observable.add_analysis(Analysis(type=module.type, details={}))
                await asyncio.wait_for(
                    module.execute_analysis(request.modified_root, request.modified_observable, analysis),
                    timeout=module.timeout,
                )
                return request
            except asyncio.TimeoutError as e:
                return self.process_exception(
                    module,
                    request,
                    e,
                    f"{module.type} timed out analyzing type {request.modified_observable.type} value {request.modified_observable.value} after {module.timeout} seconds",
                )
            except Exception as e:
                return self.process_exception(
                    module,
                    request,
                    e,
                    f"{module.type} failed analyzing type {request.modified_observable.type} value {request.modified_observable.value}: {e}",
                )

    def process_exception(
        self, module: AnalysisModule, request: AnalysisRequest, e: Exception, error_message: Optional[str] = None
    ) -> AnalysisRequest:
        assert isinstance(module, AnalysisModule)
        assert isinstance(request, AnalysisRequest)
        assert isinstance(e, Exception)

        # use existing analysis if it already exists
        analysis = request.modified_observable.get_analysis(module.type)
        if analysis is None:
            analysis = request.modified_observable.add_analysis(Analysis(type=module.type))

        # set the error message and stack trace details
        if not error_message:
            analysis.error_message = f"{type(e).__name__}: {e}"
        else:
            analysis.error_message = error_message

        analysis.stack_trace = format_error_report(e)
        get_logger().error(error_message)
        return request
